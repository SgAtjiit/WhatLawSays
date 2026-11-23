import { afterEach, describe, expect, it, vi } from "vitest";

async function load(env) {
  vi.resetModules();
  for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value);
  return import("@/auth/demo");
}

afterEach(() => vi.unstubAllEnvs());

describe("demo accounts", () => {
  it("do not exist outside demo mode", async () => {
    const demo = await load({ VITE_DEMO: "", VITE_FIREBASE_AUTH_EMULATOR: "http://127.0.0.1:9099" });
    expect(demo.DEMO_ENABLED).toBe(false);
    expect(demo.DEMO_ACCOUNTS).toEqual([]);
  });

  it("never sign in to a real Firebase project, even with demo mode on", async () => {
    const demo = await load({ VITE_DEMO: "true", VITE_FIREBASE_AUTH_EMULATOR: "" });
    expect(demo.DEMO_ENABLED).toBe(false);
    expect(demo.DEMO_ACCOUNTS).toEqual([]);
  });

  it("are offered against the emulator in demo mode, and found by uid", async () => {
    const demo = await load({ VITE_DEMO: "true", VITE_FIREBASE_AUTH_EMULATOR: "http://127.0.0.1:9099" });
    expect(demo.DEMO_ACCOUNTS.map((a) => a.id)).toEqual(["priya", "arjun"]);
    expect(demo.demoAccountFor({ uid: "demo-arjun" })?.name).toBe("Arjun Mehta");
    expect(demo.demoAccountFor({ uid: "someone-else" })).toBeNull();
    expect(demo.demoAccount("nobody")).toBeNull();
  });

  it("link back to the page you were on", async () => {
    const demo = await load({ VITE_DEMO: "true", VITE_FIREBASE_AUTH_EMULATOR: "http://127.0.0.1:9099" });
    const [priya] = demo.DEMO_ACCOUNTS;
    expect(demo.demoHref(priya)).toBe("/demo/priya");
    expect(demo.demoHref(priya, "/contracts/abc?section=red-flags")).toBe(
      "/demo/priya?next=%2Fcontracts%2Fabc%3Fsection%3Dred-flags",
    );
  });
});
