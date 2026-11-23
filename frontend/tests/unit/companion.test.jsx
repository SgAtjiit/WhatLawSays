import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError, configureAuth, createEventParser, stream } from "@/api/client";
import { chatEvents } from "@/api/schemas";
import { AnswerText } from "@/features/companion/AnswerText";
import { parseAnswer, parseInline, situationFrom } from "@/lib/answerText";
import turn from "../fixtures/conversation-turn.json";

afterEach(() => {
  vi.unstubAllGlobals();
  configureAuth({ token: async () => null, signedOut: () => {} });
});

const sse = (name, data) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;

function streamResponse(pieces, status = 200) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const piece of pieces) controller.enqueue(encoder.encode(piece));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

describe("createEventParser", () => {
  it("reassembles events split across arbitrary pieces", () => {
    const seen = [];
    const parser = createEventParser((name, data) => seen.push([name, data]));
    const text = sse("delta", { text: "Hello" }) + sse("delta", { text: " there" }) + sse("done", { ok: true });
    for (let i = 0; i < text.length; i += 7) parser.push(text.slice(i, i + 7));
    parser.end();
    expect(seen).toEqual([
      ["delta", { text: "Hello" }],
      ["delta", { text: " there" }],
      ["done", { ok: true }],
    ]);
  });

  it("accepts CRLF line endings and a last event without a blank line", () => {
    const seen = [];
    const parser = createEventParser((name, data) => seen.push([name, data]));
    parser.push('event: sources\r\ndata: {"sources": []}\r\n\r\nevent: done\r\ndata: {"x": 1}');
    parser.end();
    expect(seen).toEqual([
      ["sources", { sources: [] }],
      ["done", { x: 1 }],
    ]);
  });
});

describe("stream", () => {
  it("checks each event against its schema and hands it over in order", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => streamResponse(turn.events.map(([n, d]) => sse(n, d)))));
    const seen = [];
    await stream("/api/v1/conversations/x/messages", {
      body: { content: "hi" },
      schemas: chatEvents,
      onEvent: (name) => seen.push(name),
    });
    expect(seen).toEqual(turn.events.map(([name]) => name));
  });

  it("retries once with a fresh token when the first is refused", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "expired" }), { status: 401 }))
      .mockResolvedValueOnce(streamResponse([sse("delta", { text: "ok" })]));
    vi.stubGlobal("fetch", fetch);
    const token = vi.fn(async (fresh) => (fresh ? "new" : "old"));
    configureAuth({ token, signedOut: () => {} });
    const seen = [];
    await stream("/x", { body: {}, onEvent: (name, data) => seen.push(data.text) });
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe("Bearer new");
    expect(seen).toEqual(["ok"]);
  });

  it("turns a refusal before the stream into the server's message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Wait for the current answer to finish." }), { status: 409 })),
    );
    const error = await stream("/x", { body: {}, onEvent: () => {} }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("Wait for the current answer to finish.");
  });

  it("lets an error raised by the caller's handler through unchanged", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => streamResponse([sse("error", { detail: "The answer stopped part-way." })])));
    const error = await stream("/x", {
      body: {},
      onEvent: (name, data) => {
        if (name === "error") throw new ApiError("server", data.detail);
      },
    }).catch((e) => e);
    expect(error.kind).toBe("server");
    expect(error.message).toBe("The answer stopped part-way.");
  });

  it("rejects an event in the wrong shape", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => streamResponse([sse("delta", { words: "no text field" })])));
    const error = await stream("/x", { body: {}, schemas: chatEvents, onEvent: () => {} }).catch((e) => e);
    expect(error.kind).toBe("shape");
  });
});

describe("answer text", () => {
  it("finds citations, bold and quoted statute words", () => {
    expect(parseInline('It covers anyone who "captures, publishes or transmits" an image [1][2]. **Act now.**')).toEqual([
      { text: "It covers anyone who " },
      { quote: "captures, publishes or transmits" },
      { text: " an image " },
      { cite: 1 },
      { cite: 2 },
      { text: ". " },
      { bold: "Act now." },
    ]);
  });

  it("does not set a one- or two-word quote as statute", () => {
    expect(parseInline('the "seller" and "the buyer"')).toEqual([{ text: 'the "seller" and "the buyer"' }]);
  });

  it("splits paragraphs and both kinds of list", () => {
    const blocks = parseAnswer("First paragraph\ncontinues.\n\nSteps:\n- one [1]\n- two\n\n1. first\n2. second");
    expect(blocks.map((b) => b.type)).toEqual(["p", "p", "ul", "ol"]);
    expect(blocks[0].inline).toEqual([{ text: "First paragraph continues." }]);
    expect(blocks[2].items[0]).toEqual([{ text: "one " }, { cite: 1 }]);
  });

  it("renders markup in an answer as text, never as HTML", () => {
    const { container } = render(<AnswerText text={'<img src=x onerror="alert(1)"> [1]'} sources={[]} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it("names each citation button after its section, and reports which was chosen", async () => {
    const sources = turn.events[0][1].sources;
    const chosen = vi.fn();
    render(<AnswerText text="Covered by the IT Act [1]." sources={sources} onCite={chosen} />);
    await userEvent.click(screen.getByRole("button", { name: "Source 1: IT Act, section 66E" }));
    expect(chosen).toHaveBeenCalledWith(1);
  });

  it("sends only the person's own words to the full analysis", () => {
    const messages = [
      { role: "user", content: "He took my phone." },
      { role: "assistant", content: "That may be theft [1]." },
      { role: "user", content: " It was at my office. " },
    ];
    expect(situationFrom(messages)).toBe("He took my phone.\n\nIt was at my office.");
  });
});
