import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

import { createAccount, expectNoHorizontalScroll, mockApi, signIn } from "./support";

// A real turn recorded from the backend: the sections the statute search returned.
const recorded = JSON.parse(readFileSync(new URL("../fixtures/conversation-turn.json", import.meta.url)));
const SOURCES = recorded.events[0][1].sources;
const STARTER = "Someone posted private photos of me online without my consent.";
// What a model answer looks like, written over the recorded sections.
const ANSWER =
  'Sharing a photo of your private area without your consent is an offence: the IT Act covers anyone who "captures, publishes or transmits the image of a private area" [1].\n\n' +
  "What you can do now:\n- Keep screenshots with dates and links.\n- Report it to the police [1].\n\n" +
  "Did you share the photos with the person who posted them?";

const summaryOf = (conversation) => Object.fromEntries(Object.entries(conversation).filter(([key]) => key !== "messages"));
const sse = (name, data) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;

/** An in-memory backend for /api/v1/conversations. `fail` makes the next reply fail. */
async function companionApi(page) {
  const state = { conversations: new Map(), fail: 0, sent: [] };
  const now = () => new Date().toISOString();
  const conversationRoute = "^(GET|POST|PATCH|DELETE) /api/v1/conversations";

  const calls = await mockApi(page, {
    [conversationRoute]: async (route, request) => {
      if (!request.headers().authorization?.startsWith("Bearer ")) {
        return route.fulfill({ status: 401, json: { detail: "Sign in to continue." } });
      }
      const url = new URL(request.url());
      const [, , , , id, tail] = url.pathname.split("/");
      const method = request.method();

      if (!id && method === "GET") {
        const items = [...state.conversations.values()]
          .filter((c) => c.title)
          .map(summaryOf)
          .reverse();
        return route.fulfill({ json: { items, has_more: false } });
      }
      if (!id && method === "POST") {
        const created = { conversation_id: `c${state.conversations.size + 1}`, title: null, created_at: now(), updated_at: now(), messages: [] };
        state.conversations.set(created.conversation_id, created);
        return route.fulfill({ status: 201, json: summaryOf(created) });
      }
      const conversation = state.conversations.get(id);
      if (!conversation) return route.fulfill({ status: 404, json: { detail: "We can't find that conversation." } });

      if (tail === "messages") {
        const { content } = request.postDataJSON();
        state.sent.push(content);
        if (state.fail > 0) {
          state.fail -= 1;
          return route.fulfill({
            contentType: "text/event-stream",
            body: sse("sources", { sources: SOURCES }) + sse("error", { detail: "The answer stopped part-way. Try sending your message again." }),
          });
        }
        const question = { message_id: `m${Math.random()}`, role: "user", content, sources: [], cited: [], degraded: false, created_at: now() };
        const answer = { message_id: `m${Math.random()}`, role: "assistant", content: ANSWER, sources: SOURCES, cited: [1], degraded: false, created_at: now() };
        conversation.messages.push(question, answer);
        conversation.title ??= content.slice(0, 60);
        const pieces = ANSWER.match(/[\s\S]{1,25}/g).map((text) => sse("delta", { text }));
        return route.fulfill({
          contentType: "text/event-stream",
          body: sse("sources", { sources: SOURCES }) + pieces.join("") + sse("done", { question, answer, title: conversation.title }),
        });
      }
      if (method === "GET") return route.fulfill({ json: conversation });
      if (method === "PATCH") {
        conversation.title = request.postDataJSON().title;
        return route.fulfill({ json: summaryOf(conversation) });
      }
      if (method === "DELETE") {
        state.conversations.delete(id);
        return route.fulfill({ status: 204, body: "" });
      }
      return route.fulfill({ status: 405, json: { detail: "no mock" } });
    },
  });
  return { state, calls };
}

test("talk it through: an answer cites its sections, and the conversation is kept", async ({ page }) => {
  const { state } = await companionApi(page);
  await signIn(page, await createAccount(), "/talk");

  await expect(page.getByRole("heading", { name: "Talk it through" })).toBeVisible();
  await page.getByRole("button", { name: STARTER }).click();

  await expect(page).toHaveURL(/\/talk\/c1$/);
  await expect(page.getByText("Did you share the photos with the person who posted them?")).toBeVisible();
  expect(state.sent).toEqual([STARTER]);

  // The quoted statute words are set as source text, and the number opens its section.
  await expect(page.locator("q", { hasText: "captures, publishes or transmits" })).toBeVisible();
  const margin = page.getByRole("complementary", { name: "Sources" });
  await expect(margin.getByRole("heading", { name: "The law behind this answer" })).toBeVisible();
  await page.getByRole("button", { name: "Source 1: IT Act, section 66E" }).first().click();
  await expect(margin.getByRole("article", { name: "Source 1: IT Act, section 66E" })).toContainText("Whoever");

  // Saved: it is listed, and a reload brings it back.
  await expect(page.getByRole("link", { name: new RegExp(STARTER.slice(0, 30)) }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByText("Did you share the photos with the person who posted them?")).toBeVisible();

  // A follow-up goes to the same conversation.
  await page.getByLabel("Your message").fill("They were sent to my ex privately.");
  await page.keyboard.press("Enter");
  await expect(page.getByText("They were sent to my ex privately.")).toBeVisible();
  await expect(page.getByText("Did you share the photos")).toHaveCount(2);
  expect(state.sent).toEqual([STARTER, "They were sent to my ex privately."]);
});

test("a reply that fails keeps the message and can be tried again", async ({ page }) => {
  const { state } = await companionApi(page);
  state.fail = 1;
  await signIn(page, await createAccount(), "/talk");

  await page.getByLabel("Your message").fill("The police refused to register my FIR.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("alert")).toContainText("The answer stopped part-way.");
  await expect(page.getByLabel("Your message")).toHaveValue("The police refused to register my FIR.");

  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Did you share the photos with the person who posted them?")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("rename and delete a conversation, and take it to the full analysis", async ({ page }) => {
  await companionApi(page);
  await signIn(page, await createAccount(), "/talk");
  await page.getByRole("button", { name: STARTER }).click();
  await expect(page.getByText("Did you share the photos")).toBeVisible();

  const list = page.getByRole("navigation", { name: "Your conversations" }).first();
  await list.getByRole("button", { name: /^Options for/ }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Photos posted online");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(list.getByRole("link", { name: /Photos posted online/ })).toBeVisible();

  await page.getByRole("button", { name: "Turn this into a full analysis" }).click();
  await expect(page).toHaveURL(/\/scenario$/);
  await expect(page.getByLabel("What happened")).toHaveValue(STARTER);
  await page.goBack();

  await list.getByRole("button", { name: /^Options for/ }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/talk$/);
  await expect(page.getByRole("heading", { name: "Talk it through" })).toBeVisible();
});

test("someone else's conversation link shows not found", async ({ page }) => {
  await companionApi(page);
  await signIn(page, await createAccount(), "/talk/not-yours");
  await expect(page.getByRole("heading", { name: "We can't find that conversation" })).toBeVisible();
});

test("talk it through fits a phone screen @mobile", async ({ page }) => {
  await companionApi(page);
  await signIn(page, await createAccount(), "/talk");
  await expectNoHorizontalScroll(page);
  await page.getByRole("button", { name: STARTER }).click();
  await expect(page.getByText("Did you share the photos")).toBeVisible();

  // Sections sit under the answer as one-line rows; the number opens its row.
  const row = page.getByRole("article", { name: "Source 1: IT Act, section 66E" });
  await expect(row).not.toContainText("Whoever");
  await page.getByRole("button", { name: "Source 1: IT Act, section 66E" }).first().click();
  await expect(row).toContainText("Whoever");
  await expectNoHorizontalScroll(page);

  await page.getByRole("button", { name: "Conversations" }).click();
  await expect(page.getByRole("dialog").getByRole("link", { name: /Someone posted private photos/ })).toBeVisible();
});
