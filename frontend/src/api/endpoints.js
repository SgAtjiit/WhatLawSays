import { request, stream } from "./client";
import {
  chatEvents,
  contractAnswer,
  contractDocument,
  contractList,
  contractRecord,
  contractReview,
  conversation,
  conversationList,
  conversationSummary,
  scenarioAnalysis,
  supportedOptions,
} from "./schemas";

// A contract review can take minutes: about thirty model calls on a long
// document. The backend allows 600 seconds.
const REVIEW_TIMEOUT = 610_000;

export function analyseScenario({ scenarioText, jurisdiction = "India", signal }) {
  return request("/api/v1/analyze", {
    method: "POST",
    body: { scenario_text: scenarioText, jurisdiction },
    signal,
    timeout: 300_000,
    schema: scenarioAnalysis,
  });
}

export function getSupportedOptions() {
  return request("/api/v1/contracts/meta/supported", { schema: supportedOptions });
}

export function reviewContract({ file, contractType, position, signal }) {
  const form = new FormData();
  form.append("file", file, file.name);
  if (contractType) form.append("contract_type", contractType);
  if (position) form.append("position", position);
  form.append("jurisdiction", "India");
  return request("/api/v1/contracts", {
    method: "POST",
    form,
    signal,
    timeout: REVIEW_TIMEOUT,
    schema: contractReview,
  });
}

export function getContract(contractId, { signal } = {}) {
  return request(`/api/v1/contracts/${encodeURIComponent(contractId)}`, {
    signal,
    schema: contractRecord,
  });
}

export function getContractDocument(contractId, { signal } = {}) {
  return request(`/api/v1/contracts/${encodeURIComponent(contractId)}/document`, {
    signal,
    schema: contractDocument,
  });
}

export function listContracts({ limit = 20, offset = 0, signal } = {}) {
  return request(`/api/v1/contracts?limit=${limit}&offset=${offset}`, {
    signal,
    schema: contractList,
  });
}

export function askContract({ contractId, question, signal }) {
  return request(`/api/v1/contracts/${encodeURIComponent(contractId)}/ask`, {
    method: "POST",
    body: { question },
    signal,
    timeout: 180_000,
    schema: contractAnswer,
  });
}

export function deleteContract(contractId) {
  return request(`/api/v1/contracts/${encodeURIComponent(contractId)}`, { method: "DELETE" });
}

// A plain link cannot carry the Authorization header, so the PDF is fetched
// and handed to the browser as a file.
export async function downloadReport(contractId) {
  const blob = await request(
    `/api/v1/contracts/${encodeURIComponent(contractId)}/report.pdf`,
    { as: "blob", timeout: 120_000 },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `contract-review-${contractId}.pdf`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

// --- Legal companion ------------------------------------------------------------

const conversationPath = (id) => `/api/v1/conversations/${encodeURIComponent(id)}`;

export function listConversations({ limit = 30, offset = 0, signal } = {}) {
  return request(`/api/v1/conversations?limit=${limit}&offset=${offset}`, { signal, schema: conversationList });
}

export function createConversation() {
  return request("/api/v1/conversations", { method: "POST", body: {}, schema: conversationSummary });
}

export function getConversation(id, { signal } = {}) {
  return request(conversationPath(id), { signal, schema: conversation });
}

export function renameConversation(id, title) {
  return request(conversationPath(id), { method: "PATCH", body: { title }, schema: conversationSummary });
}

export function deleteConversation(id) {
  return request(conversationPath(id), { method: "DELETE" });
}

/** Streams the reply: onEvent("sources" | "delta" | "done" | "error", data). */
export function sendMessage({ conversationId, content, signal, onEvent }) {
  return stream(`${conversationPath(conversationId)}/messages`, {
    body: { content },
    signal,
    schemas: chatEvents,
    onEvent,
  });
}
