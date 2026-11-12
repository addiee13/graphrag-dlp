export type Claims = {
  user_id: string;
  name: string;
  tenant_id: string;
  clearance_level: number;
  departments: string[];
  roles: string[];
};
export type Identity = Claims & { identity_id: string };
export type Session = {
  access_token: string;
  expires_in: number;
  claims: Claims;
  identity_id: string;
};
export type Health = {
  status: string;
  version?: string;
  mode: string;
  auth_enforced: boolean;
  adapters: Record<string, string | boolean>;
};
export type Citation = {
  citation_id: string;
  document_id: string;
  document_title: string;
  chunk_id?: string;
  snippet: string;
  classification_level: number;
  source_node_ids?: string[];
  source_edge_ids?: string[];
};
export type GraphNode = {
  data: {
    id: string;
    label: string;
    type?: string;
    classification_level?: number;
  };
};
export type GraphEdge = {
  data: { id: string; source: string; target: string; label?: string };
};
export type GraphPayload = {
  elements: { nodes: GraphNode[]; edges: GraphEdge[] };
};
export type Source = {
  document_id: string;
  title: string;
  content: string;
  classification_level: number;
  department: string;
  content_hash: string;
  source_uri: string;
};
export type Metadata = {
  mode?: string;
  transformed_cypher?: string;
  pipeline?: (string | { name?: string; stage?: string; status?: string })[];
};
export type StreamEvent = { event: string; data: unknown };
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Same-origin by default. Deployments can set an explicit trusted API origin at build time.
const base = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(
  /\/$/,
  "",
);
export async function request<T>(
  path: string,
  options: {
    token?: string;
    signal?: AbortSignal;
    body?: unknown;
  } = {},
): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method: options.body === undefined ? "GET" : "POST",
    signal: options.signal,
    credentials: "omit",
    cache: "no-store",
    headers: {
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
      ...(options.body === undefined
        ? {}
        : { "Content-Type": "application/json" }),
    },
    ...(options.body === undefined
      ? {}
      : { body: JSON.stringify(options.body) }),
  });
  if (!response.ok)
    throw new ApiError(response.status, `Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export function errorMessage(error: unknown, resource = "request") {
  if (error instanceof ApiError) {
    if (error.status === 401)
      return "Your session is no longer valid. Reconnect your demo identity.";
    if (error.status === 403)
      return "This action is not available for your current identity.";
    if (error.status === 404) return "This source is unavailable.";
    if (error.status === 429)
      return "Too many requests. Wait a moment, then try again.";
    if (error.status === 400 || error.status === 422)
      return "The request could not be accepted. Check your input and try again.";
  }
  return `Could not complete the ${resource}. Check the API connection and try again.`;
}

// Handles fragmented UTF-8, multiline SSE data, CRLF and a final unterminated event.
// Unknown event types never become rendered content.
export async function readEvents(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let event = "message";
  let lines: string[] = [];
  const dispatch = () => {
    if (lines.length) onEvent({ event, data: JSON.parse(lines.join("\n")) });
    event = "message";
    lines = [];
  };
  const line = (value: string) => {
    if (value === "") {
      dispatch();
      return;
    }
    if (value.startsWith("event:")) event = value.slice(6).trim();
    if (value.startsWith("data:")) lines.push(value.slice(5).replace(/^ /, ""));
  };
  const abort = () => {
    void reader.cancel();
  };
  signal?.addEventListener("abort", abort, { once: true });
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      let end: number;
      while ((end = pending.indexOf("\n")) !== -1) {
        line(pending.slice(0, end).replace(/\r$/, ""));
        pending = pending.slice(end + 1);
      }
      if (done) {
        if (pending) line(pending.replace(/\r$/, ""));
        dispatch();
        break;
      }
    }
  } finally {
    signal?.removeEventListener("abort", abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function chat(
  token: string,
  message: string,
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
) {
  const response = await fetch(`${base}/chat`, {
    method: "POST",
    credentials: "omit",
    cache: "no-store",
    signal,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ message, include_graph: true }),
  });
  if (!response.ok)
    throw new ApiError(response.status, `Request failed (${response.status})`);
  if (
    !response.body ||
    !response.headers.get("content-type")?.includes("text/event-stream")
  ) {
    throw new Error("Expected event stream");
  }
  await readEvents(response.body, onEvent, signal);
}

export const emptyGraph = (): GraphPayload => ({
  elements: { nodes: [], edges: [] },
});
export function isGraph(value: unknown): value is GraphPayload {
  const data = value as GraphPayload | undefined;
  return (
    !!data?.elements &&
    Array.isArray(data.elements.nodes) &&
    Array.isArray(data.elements.edges) &&
    data.elements.nodes.every(
      (n) =>
        typeof n.data?.id === "string" && typeof n.data?.label === "string",
    ) &&
    data.elements.edges.every(
      (e) =>
        typeof e.data?.id === "string" &&
        typeof e.data?.source === "string" &&
        typeof e.data?.target === "string",
    )
  );
}
