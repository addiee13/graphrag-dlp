import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import App from "./App";
import type { GraphPayload } from "./api";

// Canvas is exercised by real-browser verification. These tests cover session and API behavior.
vi.mock("./GraphView", () => ({
  default: ({ graph }: { graph: GraphPayload }) => (
    <div aria-label="Test graph">
      {graph.elements.nodes.map((node) => (
        <span key={node.data.id}>{node.data.label}</span>
      ))}
    </div>
  ),
}));

const identities = [
  {
    identity_id: "admin",
    user_id: "a",
    name: "Test Administrator",
    tenant_id: "acme",
    clearance_level: 4,
    departments: ["engineering", "procurement"],
    roles: ["admin"],
  },
  {
    identity_id: "contractor",
    user_id: "c",
    name: "Test Contractor",
    tenant_id: "acme",
    clearance_level: 1,
    departments: ["engineering"],
    roles: ["reader"],
  },
];
const health = {
  status: "healthy",
  mode: "deterministic_local",
  adapters: { graph_store: "local", vector_engine: "tfidf" },
  auth_enforced: true,
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
let chatController: ReadableStreamDefaultController<Uint8Array>;
let chatSignal: AbortSignal;
let sourceSignal: AbortSignal;
type FetchFixture = (
  url: string,
  init: RequestInit,
) => Response | Promise<Response>;
let fetchMock: Mock<FetchFixture>;
function emit(event: string, data: unknown) {
  chatController.enqueue(
    new TextEncoder().encode(
      `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
    ),
  );
}

beforeEach(() => {
  fetchMock = vi.fn<FetchFixture>(async (url: string, init: RequestInit) => {
    if (url.endsWith("/health")) return json(health);
    if (url.endsWith("/auth/identities")) return json({ identities });
    if (url.endsWith("/auth/token")) {
      const id = JSON.parse(init.body as string).identity_id;
      const identity = identities.find((i) => i.identity_id === id)!;
      return json({
        access_token: `${id}-signed-token`,
        token_type: "bearer",
        expires_in: 3600,
        claims: identity,
      });
    }
    if (url.endsWith("/chat")) {
      chatSignal = init.signal as AbortSignal;
      return new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            chatController = controller;
          },
        }),
        { headers: { "Content-Type": "text/event-stream" } },
      );
    }
    if (url.includes("/sources/")) {
      sourceSignal = init.signal as AbortSignal;
      return new Promise<Response>(() => {});
    }
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

async function connect(id = "admin") {
  const user = userEvent.setup();
  render(<App />);
  await waitFor(() =>
    expect(screen.getByLabelText("Demo identity")).toBeEnabled(),
  );
  await user.selectOptions(screen.getByLabelText("Demo identity"), id);
  await screen.findByRole("button", { name: "Ask question" });
  return user;
}

async function startQuery(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Your question"), "What is available?");
  await user.click(screen.getByRole("button", { name: "Ask question" }));
  await waitFor(() => expect(chatController).toBeDefined());
}

describe("secure workspace", () => {
  it("uses only an identity ID to authenticate and sends the returned bearer token on chat", async () => {
    const user = await connect();
    await startQuery(user);
    const authCall = fetchMock.mock.calls.find(([url]) =>
      url.endsWith("/auth/token"),
    )!;
    expect(JSON.parse(String(authCall[1].body))).toEqual({
      identity_id: "admin",
    });
    const queryCall = fetchMock.mock.calls.find(([url]) =>
      url.endsWith("/chat"),
    )!;
    expect(new Headers(queryCall[1].headers).get("Authorization")).toBe(
      "Bearer admin-signed-token",
    );
    expect(JSON.parse(String(queryCall[1].body))).toEqual({
      message: "What is available?",
      include_graph: true,
    });
  });

  it("clears high-role answer, citations, graph, source drawer and input; aborts outstanding requests on an identity switch", async () => {
    const user = await connect();
    await startQuery(user);
    await act(async () => {
      emit("token", { delta: "Sensitive answer from test fixture" });
      emit("citation", {
        citation_id: "c1",
        document_id: "private-doc",
        document_title: "Private fixture source",
        snippet: "Fixture evidence",
        classification_level: 4,
      });
      emit("graph_update", {
        elements: {
          nodes: [
            { data: { id: "sensitive", label: "Private fixture entity" } },
          ],
          edges: [],
        },
      });
    });
    await screen.findByText("Sensitive answer from test fixture");
    await user.click(
      screen.getByRole("button", { name: /Private fixture source/ }),
    );
    await screen.findByRole("dialog");
    expect(sourceSignal.aborted).toBe(false);
    await user.selectOptions(
      screen.getByLabelText("Demo identity"),
      "contractor",
    );
    await screen.findByRole("button", { name: "Ask question" });
    expect(chatSignal.aborted).toBe(true);
    expect(sourceSignal.aborted).toBe(true);
    expect(
      screen.queryByText("Sensitive answer from test fixture"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Private fixture entity"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Private fixture source"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue("");
    expect(
      screen.queryByRole("button", { name: "Add knowledge" }),
    ).not.toBeInTheDocument();
  });

  it("marks a truncated stream incomplete and does not expose arbitrary metadata", async () => {
    const user = await connect("contractor");
    await startQuery(user);
    await act(async () => {
      emit("metadata", {
        mode: "deterministic_local",
        blocked_nodes: 6,
        secret_name: "DO-NOT-RENDER",
      });
      emit("token", { delta: "Partial response" });
      chatController.close();
    });
    await screen.findByText("The answer did not finish.");
    await user.click(screen.getByRole("button", { name: "Query inspector" }));
    expect(
      screen.queryByText(/DO-NOT-RENDER|blocked_nodes/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
  });

  it("shows connection failures honestly and offers a retry without fabricating results", async () => {
    fetchMock.mockRejectedValue(new TypeError("Connection refused"));
    render(<App />);
    await screen.findByRole("button", { name: "Retry connection" });
    expect(screen.getByText("API disconnected")).toBeInTheDocument();
    expect(screen.getByLabelText("Demo identity")).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Ask question" }),
    ).not.toBeInTheDocument();
  });

  it("ignores a late authentication response after a different identity is selected", async () => {
    const user = userEvent.setup();
    let resolveAdmin!: (value: Response) => void;
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((url: string, init: RequestInit) => {
      if (
        url.endsWith("/auth/token") &&
        JSON.parse(init.body as string).identity_id === "admin"
      )
        return new Promise<Response>((resolve) => {
          resolveAdmin = resolve;
        });
      return original(url, init);
    });
    render(<App />);
    await waitFor(() =>
      expect(screen.getByLabelText("Demo identity")).toBeEnabled(),
    );
    await user.selectOptions(screen.getByLabelText("Demo identity"), "admin");
    await user.selectOptions(
      screen.getByLabelText("Demo identity"),
      "contractor",
    );
    await screen.findByText("Public");
    await act(async () =>
      resolveAdmin(
        json({
          access_token: "late-admin-token",
          expires_in: 3600,
          claims: identities[0],
        }),
      ),
    );
    expect(screen.getByText("Public")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add knowledge" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Demo identity")).toHaveValue("contractor");
  });

  it("clears the entire workspace when the API rejects an expired session", async () => {
    const user = await connect();
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((url: string, init: RequestInit) =>
      url.endsWith("/chat") ? json({}, 401) : original(url, init),
    );
    await startQuery(user);
    await screen.findByText(
      "Your session is no longer valid. Choose an identity to reconnect.",
    );
    expect(screen.queryByLabelText("Your question")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Demo identity")).toHaveValue("");
  });

  it("sends graph queries with the current token and renders only allowed response fields", async () => {
    const user = await connect("contractor");
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((url: string, init: RequestInit) =>
      url.endsWith("/query/cypher")
        ? json({
            columns: ["n.name"],
            rows: [["Public fixture"]],
            transformed_cypher: "MATCH (n) RETURN n.name LIMIT 10",
            blocked_node_count: 7,
          })
        : original(url, init),
    );
    await user.click(screen.getByRole("button", { name: "Query inspector" }));
    await user.click(screen.getByRole("button", { name: "Run graph query" }));
    await screen.findByText("Public fixture");
    const call = fetchMock.mock.calls.find(([url]) =>
      url.endsWith("/query/cypher"),
    )!;
    expect(new Headers(call[1].headers).get("Authorization")).toBe(
      "Bearer contractor-signed-token",
    );
    expect(JSON.parse(String(call[1].body))).toEqual({
      cypher: "MATCH (n) RETURN n.name LIMIT 10",
      parameters: {},
    });
    expect(screen.queryByText("blocked_node_count")).not.toBeInTheDocument();
  });

  it("ingests through the authenticated API without supplying tenant or identity claims", async () => {
    const user = await connect();
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((url: string, init: RequestInit) =>
      url.endsWith("/ingest")
        ? json(
            {
              document_id: "new-doc",
              content_hash: "fixture-hash",
              chunks_created: 1,
            },
            201,
          )
        : original(url, init),
    );
    await user.click(screen.getByRole("button", { name: "Add knowledge" }));
    await user.type(screen.getByLabelText("Document title"), "Source fixture");
    await user.type(
      screen.getByLabelText("Document content"),
      "Public fixture text",
    );
    await user.click(screen.getByRole("button", { name: "Add document" }));
    await screen.findByText("Document added");
    const call = fetchMock.mock.calls.find(([url]) => url.endsWith("/ingest"))!;
    expect(new Headers(call[1].headers).get("Authorization")).toBe(
      "Bearer admin-signed-token",
    );
    expect(JSON.parse(String(call[1].body))).toEqual({
      title: "Source fixture",
      content: "Public fixture text",
      source_uri: "",
      classification_level: 1,
      department: "public",
      extract_entities: true,
    });
  });
});
