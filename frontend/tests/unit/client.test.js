import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError, configureAuth, request } from "@/api/client";

function respond(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  configureAuth({ token: async () => null, signedOut: () => {} });
});

describe("request", () => {
  it("sends the signed-in user's token", async () => {
    const fetch = vi.fn(async () => respond(200, { ok: true }));
    vi.stubGlobal("fetch", fetch);
    configureAuth({ token: async () => "abc", signedOut: () => {} });
    await request("/api/v1/x");
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe("Bearer abc");
  });

  it.each([
    [413, { detail: "File exceeds the 15 MB limit." }, "too_large", "File exceeds the 15 MB limit."],
    [422, { detail: "Could not read the PDF." }, "invalid", "Could not read the PDF."],
    [422, { detail: [{ msg: "field required" }, { msg: "too short" }] }, "invalid", "field required; too short"],
    [429, { detail: "Contract uploads are limited to 6 per minute." }, "rate_limited", "Contract uploads are limited to 6 per minute."],
    [503, { detail: "The background review queue is unavailable." }, "unavailable", "The background review queue is unavailable."],
    [404, { detail: "No contract 'x'." }, "not_found", "No contract 'x'."],
    [500, {}, "server", "Something went wrong on our side. Try again in a moment."],
  ])("maps %i to a %s error carrying the server's message", async (status, body, kind, message) => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(status, body)));
    const error = await request("/api/v1/x").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe(kind);
    expect(error.message).toBe(message);
  });

  it("calls an unreachable server offline", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const error = await request("/api/v1/x").catch((e) => e);
    expect(error.kind).toBe("offline");
  });

  it("retries once with a fresh token, then signs out", async () => {
    const fetch = vi.fn(async () => respond(401, { detail: "Your session has expired. Sign in again." }));
    const signedOut = vi.fn();
    const token = vi.fn(async (force) => (force ? "fresh" : "stale"));
    vi.stubGlobal("fetch", fetch);
    configureAuth({ token, signedOut });

    const error = await request("/api/v1/x").catch((e) => e);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe("Bearer fresh");
    expect(signedOut).toHaveBeenCalledOnce();
    expect(error.kind).toBe("unauthorized");
  });

  it("recovers when the fresh token is accepted", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(respond(401, { detail: "expired" }))
      .mockResolvedValueOnce(respond(200, { ok: true }));
    vi.stubGlobal("fetch", fetch);
    configureAuth({ token: async () => "t", signedOut: vi.fn() });
    await expect(request("/api/v1/x")).resolves.toEqual({ ok: true });
  });

  it("rejects a response in the wrong shape with a clear error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(200, { count: "three" })));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const error = await request("/api/v1/x", { schema: z.object({ count: z.number() }) }).catch((e) => e);
    expect(error.kind).toBe("shape");
    expect(error.message).toContain("count");
  });
});
