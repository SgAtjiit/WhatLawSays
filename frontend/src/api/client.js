// The one way this app talks to the backend.
//
// Every response is checked against a schema on arrival, so a backend change
// fails loudly with the field's name instead of rendering as a blank space.

const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(kind, message, { status = null, cause } = {}) {
    super(message, { cause });
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

// Set by the auth provider, which owns the Firebase user. Kept as hooks rather
// than an import so this module has no dependency on Firebase.
let getToken = async () => null;
let onSignedOut = () => {};

export function configureAuth({ token, signedOut }) {
  getToken = token;
  onSignedOut = signedOut;
}

const KIND_BY_STATUS = {
  401: "unauthorized",
  403: "forbidden",
  404: "not_found",
  413: "too_large",
  422: "invalid",
  429: "rate_limited",
  503: "unavailable",
};

function detailOf(body, fallback) {
  const detail = body && typeof body === "object" ? body.detail : null;
  if (typeof detail === "string" && detail.trim()) return detail;
  // FastAPI validation errors arrive as a list.
  if (Array.isArray(detail)) {
    return detail.map((d) => d?.msg || String(d)).join("; ");
  }
  return fallback;
}

async function errorFrom(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON: a proxy error page, for instance.
  }
  const status = response.status;
  const kind = KIND_BY_STATUS[status] || (status >= 500 ? "server" : "unexpected");
  const fallback =
    kind === "server"
      ? "Something went wrong on our side. Try again in a moment."
      : `The request failed (${status}).`;
  return new ApiError(kind, detailOf(body, fallback), { status });
}

function withTimeout(signal, ms) {
  const timeout = AbortSignal.timeout(ms);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

async function send(path, { method, body, form, signal, timeout }, forceRefresh) {
  const headers = { Accept: "application/json" };
  const token = await getToken(forceRefresh);
  if (token) headers.Authorization = `Bearer ${token}`;

  let payload;
  if (form) {
    payload = form;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  try {
    return await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: payload,
      signal: withTimeout(signal, timeout),
    });
  } catch (error) {
    if (signal?.aborted) {
      throw new ApiError("aborted", "Cancelled.", { cause: error });
    }
    if (error?.name === "TimeoutError") {
      throw new ApiError(
        "timeout",
        "This is taking longer than the server allows. Try a shorter document, or try again.",
        { cause: error },
      );
    }
    throw new ApiError(
      "offline",
      "Can't reach the WhatLawSays server. Check your connection, or make sure the backend is running.",
      { cause: error },
    );
  }
}

/**
 * @param {string} path
 * @param {{method?: string, body?: unknown, form?: FormData, signal?: AbortSignal,
 *          timeout?: number, schema?: import("zod").ZodType, as?: "json" | "blob"}} options
 */
export async function request(path, options = {}) {
  const settings = { method: "GET", timeout: 60_000, as: "json", ...options };
  const response = await respond(path, settings);
  if (settings.as === "blob") return response.blob();
  if (response.status === 204) return null;
  return checked(path, await response.json(), settings.schema);
}

/** Send, retrying once on 401 with a fresh token; any failure becomes an ApiError. */
async function respond(path, settings) {
  let response = await send(path, settings, false);
  if (response.status === 401) {
    // The token may have expired between being read and being checked.
    response = await send(path, settings, true);
    if (response.status === 401) {
      const error = await errorFrom(response);
      onSignedOut();
      throw error;
    }
  }
  if (!response.ok) throw await errorFrom(response);
  return response;
}

function checked(path, data, schema) {
  if (!schema) return data;
  const parsed = schema.safeParse(data);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const where = issue?.path?.join(".") || "response";
    console.error("Unexpected response shape", path, parsed.error.issues);
    throw new ApiError(
      "shape",
      `The server's answer was not in the shape this page expects (${where}: ${issue?.message}). The app and the server may be out of date with each other.`,
    );
  }
  return parsed.data;
}

/**
 * Reads server-sent events from text arriving in arbitrary pieces.
 * Calls onEvent(name, data) for each complete event; data is parsed JSON.
 */
export function createEventParser(onEvent) {
  let buffer = "";
  const flush = (block) => {
    let name = "message";
    const data = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (data.length) onEvent(name, JSON.parse(data.join("\n")));
  };
  return {
    push(text) {
      buffer += text.replace(/\r\n/g, "\n");
      let end;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        flush(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
      }
    },
    end() {
      if (buffer.trim()) flush(buffer);
      buffer = "";
    },
  };
}

/**
 * POST and read the reply as server-sent events. Each event's data is checked
 * against schemas[name] when one is given; onEvent(name, data) gets it.
 * Resolves when the stream ends; rejects with an ApiError, as request() does.
 */
export async function stream(path, { body, signal, timeout = 180_000, schemas = {}, onEvent }) {
  const settings = { method: "POST", body, signal, timeout };
  const response = await respond(path, settings);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = createEventParser((name, data) => onEvent(name, checked(path, data, schemas[name])));
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      parser.push(value);
    }
    parser.end();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal?.aborted) throw new ApiError("aborted", "Stopped.", { cause: error });
    if (error?.name === "TimeoutError") {
      throw new ApiError("timeout", "The answer took too long. Try sending it again.", { cause: error });
    }
    throw new ApiError("offline", "The connection dropped before the answer finished. Try again.", { cause: error });
  } finally {
    reader.releaseLock?.();
  }
}
