import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowUp,
  BookOpen,
  Check,
  CheckCheck,
  ChevronRight,
  CircleHelp,
  Database,
  FileText,
  GitBranch,
  Layers,
  LoaderCircle,
  LogOut,
  Network,
  Plus,
  Search,
  ShieldCheck,
  Square,
  X,
} from "lucide-react";
import {
  ApiError,
  chat,
  emptyGraph,
  errorMessage,
  isGraph,
  request,
  type Citation,
  type GraphPayload,
  type Health,
  type Identity,
  type Metadata,
  type Session,
  type Source,
} from "./api";

const GraphView = lazy(() => import("./GraphView"));
const prompts = [
  "Which vendors support Project Chimera?",
  "What projects does Alice lead?",
  "Summarize the available project records.",
];
const levels = [
  "Unspecified",
  "Public",
  "Internal",
  "Confidential",
  "Restricted",
];
const classify = (level: number) => levels[level] || `Level ${level}`;

function Brand() {
  return (
    <div className="brand">
      <svg aria-hidden="true" viewBox="0 0 38 38">
        <path
          d="m8 8 24 11L10 31 8 8Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <circle cx="8" cy="8" r="4" />
        <circle cx="32" cy="19" r="4" />
        <circle cx="10" cy="31" r="4" />
      </svg>
      <span>
        GraphRAG<span className="brand-sub">Knowledge, in confidence.</span>
      </span>
      <span className="brand-dlp">DLP</span>
    </div>
  );
}

function useRequests() {
  const requests = useRef(new Set<AbortController>());
  useLayoutEffect(
    () => () => {
      requests.current.forEach((c) => c.abort());
      requests.current.clear();
    },
    [],
  );
  return useCallback(() => {
    const controller = new AbortController();
    requests.current.add(controller);
    return { controller, release: () => requests.current.delete(controller) };
  }, []);
}

export default function App() {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [booting, setBooting] = useState(true);
  const [bootError, setBootError] = useState("");
  const [retry, setRetry] = useState(0);
  const [session, setSession] = useState<Session | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [identityId, setIdentityId] = useState("");
  const [authError, setAuthError] = useState("");
  const [generation, setGeneration] = useState(0);
  const authRequest = useRef<AbortController | null>(null);
  const epoch = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    setBooting(true);
    setBootError("");
    Promise.all([
      request<Health>("/health", { signal: controller.signal }),
      request<{ identities: Identity[] }>("/auth/identities", {
        signal: controller.signal,
      }),
    ])
      .then(([status, result]) => {
        if (controller.signal.aborted) return;
        setHealth(status);
        setIdentities(result.identities);
        if (!result.identities.length)
          setBootError("No demo identities are available from this API.");
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setHealth(null);
          setIdentities([]);
          setBootError(
            "The demo API is unavailable. Start the API, then retry the connection. Demo identities may be disabled on this server.",
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBooting(false);
      });
    return () => controller.abort();
  }, [retry]);

  const disconnect = useCallback((reason = "") => {
    epoch.current += 1;
    authRequest.current?.abort();
    setSession(null);
    setIdentityId("");
    setConnecting(false);
    setAuthError(reason);
    setGeneration((g) => g + 1);
  }, []);

  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(
      () =>
        disconnect(
          "Your demo session expired. Choose an identity to reconnect.",
        ),
      Math.min(session.expires_in * 1000, 2147483647),
    );
    return () => clearTimeout(timer);
  }, [session, disconnect]);
  useEffect(() => () => authRequest.current?.abort(), []);

  async function authenticate(id: string) {
    const version = ++epoch.current;
    authRequest.current?.abort();
    // Clear the entire old workspace before issuing the next authentication request.
    setSession(null);
    setGeneration((g) => g + 1);
    setIdentityId(id);
    setAuthError("");
    if (!id) {
      setConnecting(false);
      return;
    }
    setConnecting(true);
    const controller = new AbortController();
    authRequest.current = controller;
    try {
      const result = await request<Omit<Session, "identity_id">>(
        "/auth/token",
        { body: { identity_id: id }, signal: controller.signal },
      );
      if (controller.signal.aborted || epoch.current !== version) return;
      if (
        !result.access_token ||
        !result.claims ||
        !Number.isFinite(result.expires_in) ||
        result.expires_in <= 0
      )
        throw new Error("Invalid authentication response");
      setSession({ ...result, identity_id: id });
    } catch (error) {
      if (!controller.signal.aborted && epoch.current === version)
        setAuthError(errorMessage(error, "identity connection"));
    } finally {
      if (!controller.signal.aborted && epoch.current === version)
        setConnecting(false);
    }
  }

  const mode = health?.mode || "unavailable";
  const local = /local|deterministic|offline/i.test(mode);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>
      <aside className="sidebar">
        <Brand />
        <div className="workspace-label">
          <span className="workspace-initial">K</span>
          <div>
            Knowledge workspace<small>Secure intelligence portal</small>
          </div>
        </div>
        <div className="nav-current">
          <Network size={18} />
          <span>Explore knowledge</span>
          <ChevronRight size={15} />
        </div>
        <div className="identity-panel">
          <div className="sidebar-section-heading">
            <ShieldCheck size={17} />
            <h2>Access context</h2>
          </div>
          <label htmlFor="identity">Demo identity</label>
          <select
            id="identity"
            value={identityId}
            disabled={booting || !identities.length}
            onChange={(e) => void authenticate(e.target.value)}
          >
            <option value="">Choose an identity</option>
            {identities.map((i) => (
              <option key={i.identity_id} value={i.identity_id}>
                {i.name}
              </option>
            ))}
          </select>
          <p className="identity-hint">
            Demo identities are predefined by the server.
          </p>
          {connecting && (
            <p role="status" className="sidebar-status">
              <LoaderCircle className="spin" size={15} /> Connecting identity…
            </p>
          )}
          {session ? (
            <>
              <div className="identity-summary">
                <span className="avatar">
                  {session.claims.name?.slice(0, 1)}
                </span>
                <div>
                  <strong>{session.claims.name}</strong>
                  <span>Authenticated demo session</span>
                </div>
              </div>
              <dl className="policy-list">
                <div>
                  <dt>Tenant</dt>
                  <dd>{session.claims.tenant_id}</dd>
                </div>
                <div>
                  <dt>Clearance</dt>
                  <dd>
                    {classify(session.claims.clearance_level)}{" "}
                    <span className="level-number">
                      L{session.claims.clearance_level}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Departments</dt>
                  <dd>{session.claims.departments.join(", ") || "None"}</dd>
                </div>
                <div>
                  <dt>Roles</dt>
                  <dd>{session.claims.roles.join(", ")}</dd>
                </div>
              </dl>
              <p className="policy-note">
                <CheckCheck size={16} /> Claims issued by the API
              </p>
              <button className="sidebar-button" onClick={() => disconnect()}>
                <LogOut size={16} />
                Disconnect
              </button>
            </>
          ) : (
            <div className="identity-empty">
              <ShieldCheck size={25} strokeWidth={1.3} />
              <p>
                {connecting
                  ? "Creating a fresh access context."
                  : "Connect an identity to query the knowledge base."}
              </p>
            </div>
          )}
          {authError && (
            <p role="alert" className="sidebar-error">
              {authError}
            </p>
          )}
        </div>
        <div className="sidebar-bottom">
          <ShieldCheck size={18} />
          <p>
            Your identity defines your view.
            <span>
              Answers, sources, and graph evidence are requested with your
              session token.
            </span>
          </p>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <strong>Knowledge explorer</strong>
          </div>
          <span className={`connection ${health ? "online" : ""}`}>
            <span />
            {booting
              ? "Connecting to API"
              : health
                ? "API connected"
                : "API disconnected"}
          </span>
        </header>
        <main id="workspace">
          <div className="page-heading">
            <div>
              <p className="page-kicker">
                Connected knowledge. Controlled access.
              </p>
              <h1>Knowledge explorer</h1>
            </div>
            <div className={`mode-badge ${local ? "local" : ""}`}>
              <Activity size={15} />
              {health
                ? local
                  ? "No-key deterministic mode"
                  : mode.replaceAll("_", " ")
                : "Mode unavailable"}
            </div>
          </div>
          {local && (
            <p className="mode-note">
              Local retrieval and deterministic answer synthesis. No external
              language model is used.
            </p>
          )}
          {bootError && (
            <div className="connection-error" role="alert">
              <CircleHelp size={20} />
              <div>
                <strong>Connect the knowledge API</strong>
                <p>{bootError}</p>
              </div>
              <button
                className="secondary-button"
                onClick={() => setRetry((r) => r + 1)}
              >
                Retry connection
              </button>
            </div>
          )}
          {session ? (
            <Workspace
              key={generation}
              session={session}
              health={health}
              onExpired={() =>
                disconnect(
                  "Your session is no longer valid. Choose an identity to reconnect.",
                )
              }
            />
          ) : (
            <div className="workspace-grid">
              <section className="query-panel welcome-panel">
                <div className="section-heading">
                  <div>
                    <Search size={18} />
                    <h2>Ask your knowledge base</h2>
                  </div>
                  <span className="quiet-badge">New session</span>
                </div>
                <div className="welcome-content">
                  <div className="welcome-icon">
                    <GitBranch size={32} strokeWidth={1.3} />
                  </div>
                  <h2>Follow the evidence.</h2>
                  <p>
                    Connect an identity to ask a question, read its sources, and
                    explore the relationships behind the answer.
                  </p>
                  <div className="welcome-flow">
                    <span>
                      <Search size={17} /> Ask
                    </span>
                    <ChevronRight size={15} />
                    <span>
                      <BookOpen size={17} /> Verify
                    </span>
                    <ChevronRight size={15} />
                    <span>
                      <Network size={17} /> Explore
                    </span>
                  </div>
                </div>
                <div className="welcome-footer">
                  <ShieldCheck size={17} />
                  <span>
                    {connecting
                      ? "Establishing your access context…"
                      : "Start with a demo identity in the access panel."}
                  </span>
                </div>
              </section>
              <Suspense fallback={<GraphPlaceholder />}>
                <GraphView
                  graph={emptyGraph()}
                  citations={[]}
                  openSource={() => {}}
                />
              </Suspense>
            </div>
          )}
        </main>
        <footer className="app-footer">
          <span>GraphRAG DLP</span>
          <span>Source-grounded answers within your access context</span>
        </footer>
      </div>
    </div>
  );
}

function GraphPlaceholder() {
  return (
    <section className="graph-panel graph-placeholder" role="status">
      Loading graph explorer…
    </section>
  );
}
type QueryStatus = "idle" | "streaming" | "complete" | "stopped" | "error";

function Workspace({
  session,
  health,
  onExpired,
}: {
  session: Session;
  health: Health | null;
  onExpired: () => void;
}) {
  const [query, setQuery] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [graph, setGraph] = useState<GraphPayload>(emptyGraph);
  const [metadata, setMetadata] = useState<Metadata>({});
  const [status, setStatus] = useState<QueryStatus>("idle");
  const [error, setError] = useState("");
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [tab, setTab] = useState<"query" | "ingest">("query");
  const [inspector, setInspector] = useState(false);
  const activeQuery = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const composer = useRef<HTMLTextAreaElement>(null);
  const newRequest = useRequests();
  const canIngest = session.claims.roles.some((r) =>
    ["admin", "ingestor"].includes(r),
  );

  function clear() {
    sequence.current += 1;
    activeQuery.current?.abort();
    activeQuery.current = null;
    setQuery("");
    setQuestion("");
    setAnswer("");
    setCitations([]);
    setGraph(emptyGraph());
    setMetadata({});
    setStatus("idle");
    setError("");
    setSourceId(null);
    composer.current?.focus();
  }
  function stop() {
    sequence.current += 1;
    activeQuery.current?.abort();
    setStatus("stopped");
  }
  async function ask(event?: FormEvent) {
    event?.preventDefault();
    const message = query.trim();
    if (!message || status === "streaming") return;
    const version = ++sequence.current;
    activeQuery.current?.abort();
    const { controller, release } = newRequest();
    activeQuery.current = controller;
    setQuestion(message);
    setAnswer("");
    setCitations([]);
    setGraph(emptyGraph());
    setMetadata({});
    setSourceId(null);
    setError("");
    setStatus("streaming");
    let completed = false;
    try {
      await chat(session.access_token, message, controller.signal, (event) => {
        if (controller.signal.aborted || sequence.current !== version) return;
        const data = event.data as Record<string, unknown>;
        if (!data || typeof data !== "object")
          throw new Error("Invalid stream event");
        if (event.event === "token" && typeof data.delta === "string")
          setAnswer((a) => a + data.delta);
        if (
          event.event === "citation" &&
          typeof data.document_id === "string" &&
          typeof data.citation_id === "string"
        ) {
          const citation = data as unknown as Citation;
          setCitations((previous) => [
            ...previous.filter((c) => c.citation_id !== citation.citation_id),
            citation,
          ]);
        }
        if (event.event === "graph_update") {
          if (!isGraph(event.data)) throw new Error("Invalid graph response");
          setGraph(event.data);
        }
        // Only explicitly allowed inspector fields are retained, never a raw metadata dump.
        if (event.event === "metadata")
          setMetadata((previous) => ({
            ...previous,
            ...(typeof data.mode === "string" ? { mode: data.mode } : {}),
            ...(typeof data.transformed_cypher === "string"
              ? { transformed_cypher: data.transformed_cypher }
              : {}),
            ...(Array.isArray(data.pipeline)
              ? { pipeline: data.pipeline }
              : {}),
          }));
        if (event.event === "error") throw new Error("Stream rejected");
        if (event.event === "done") {
          if (data.status !== "complete")
            throw new Error("Incomplete response");
          completed = true;
          setStatus("complete");
        }
      });
      if (
        !controller.signal.aborted &&
        sequence.current === version &&
        !completed
      )
        throw new Error("Stream ended early");
    } catch (cause) {
      if (controller.signal.aborted || sequence.current !== version) return;
      if (cause instanceof ApiError && cause.status === 401) {
        onExpired();
        return;
      }
      setStatus("error");
      setError(errorMessage(cause, "answer stream"));
    } finally {
      release();
    }
  }

  return (
    <>
      <div className="workspace-toolbar">
        <div className="workspace-tabs" aria-label="Workspace views">
          <button
            className={tab === "query" ? "active" : ""}
            aria-pressed={tab === "query"}
            onClick={() => setTab("query")}
          >
            <Search size={16} />
            Query workspace
          </button>
          {canIngest && (
            <button
              className={tab === "ingest" ? "active" : ""}
              aria-pressed={tab === "ingest"}
              onClick={() => {
                stop();
                setTab("ingest");
              }}
            >
              <Plus size={16} />
              Add knowledge
            </button>
          )}
        </div>
        {tab === "query" && (
          <button className="text-button new-query" onClick={clear}>
            <Plus size={16} />
            New query
          </button>
        )}
      </div>
      {tab === "ingest" ? (
        <Ingestion session={session} onExpired={onExpired} />
      ) : (
        <div className="workspace-grid">
          <section className="query-panel" aria-labelledby="query-heading">
            <div className="section-heading">
              <div>
                <Search size={18} />
                <h2 id="query-heading">Ask your knowledge base</h2>
              </div>
              <span className="quiet-badge">{session.claims.tenant_id}</span>
            </div>
            <div className="query-body">
              {status === "idle" ? (
                <div className="query-intro">
                  <div className="intro-glyph">
                    <GitBranch size={30} strokeWidth={1.3} />
                  </div>
                  <h2>
                    Find the answer.
                    <br />
                    See the connections.
                  </h2>
                  <p>
                    Ask about people, projects, or vendors. Every answer starts
                    with the sources available to your identity.
                  </p>
                  <div className="suggestions">
                    <span>Start with a question</span>
                    {prompts.map((prompt) => (
                      <button
                        key={prompt}
                        onClick={() => {
                          setQuery(prompt);
                          composer.current?.focus();
                        }}
                      >
                        <span>{prompt}</span>
                        <ChevronRight size={17} />
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="answer-area">
                  <div className="question-bubble">
                    <span>Your question</span>
                    <h3>{question}</h3>
                  </div>
                  <div className="answer-label">
                    <span className="answer-symbol">
                      <GitBranch size={17} />
                    </span>
                    <strong>Grounded answer</strong>
                    <span className={`answer-status ${status}`} role="status">
                      {status === "streaming" ? (
                        <>
                          <LoaderCircle size={13} className="spin" />
                          Retrieving & composing
                        </>
                      ) : status === "complete" ? (
                        <>
                          <Check size={13} />
                          Complete
                        </>
                      ) : status === "stopped" ? (
                        "Stopped · partial answer"
                      ) : (
                        "Incomplete answer"
                      )}
                    </span>
                  </div>
                  <div
                    className="answer-text"
                    aria-busy={status === "streaming"}
                  >
                    {answer ? (
                      <CitedText
                        text={answer}
                        citations={citations}
                        openSource={setSourceId}
                      />
                    ) : status === "streaming" ? (
                      <span className="waiting-copy">
                        Searching the available evidence…
                      </span>
                    ) : (
                      "No answer was completed. You can retry this question."
                    )}{" "}
                    {status === "streaming" && (
                      <span className="stream-cursor" aria-hidden="true" />
                    )}
                  </div>
                  {error && (
                    <div role="alert" className="query-error">
                      <strong>The answer did not finish.</strong>
                      <p>{error}</p>
                      <button
                        className="secondary-button"
                        onClick={() => void ask()}
                      >
                        Retry question
                      </button>
                    </div>
                  )}
                  {status === "stopped" && (
                    <p className="partial-note">
                      Generation stopped. Any text and evidence above may be
                      incomplete.
                    </p>
                  )}
                  {!!citations.length && (
                    <section
                      className="citation-section"
                      aria-label="Answer sources"
                    >
                      <div className="sources-heading">
                        <BookOpen size={16} />
                        <h3>Source evidence</h3>
                        <span>{citations.length}</span>
                      </div>
                      <div className="citation-list">
                        {citations.map((citation, index) => (
                          <button
                            className="citation-card"
                            key={citation.citation_id}
                            onClick={() => setSourceId(citation.document_id)}
                          >
                            <span className="citation-number">{index + 1}</span>
                            <span>
                              <strong>{citation.document_title}</strong>
                              <span>{citation.snippet}</span>
                              <small>
                                {classify(citation.classification_level)} source{" "}
                                <span>Read document</span>
                              </small>
                            </span>
                            <ChevronRight size={16} />
                          </button>
                        ))}
                      </div>
                    </section>
                  )}
                  {status === "complete" && !citations.length && (
                    <p className="partial-note">
                      No source citations were returned for this answer.
                    </p>
                  )}
                </div>
              )}
            </div>
            <form className="composer" onSubmit={(event) => void ask(event)}>
              <label htmlFor="question">Your question</label>
              <div className="composer-input">
                <textarea
                  ref={composer}
                  id="question"
                  maxLength={2000}
                  rows={3}
                  placeholder="Ask a question about your knowledge base…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(event) => {
                    if (
                      event.key === "Enter" &&
                      !event.shiftKey &&
                      !event.nativeEvent.isComposing
                    ) {
                      event.preventDefault();
                      if (status !== "streaming") void ask();
                    }
                  }}
                  aria-describedby="composer-help"
                />
                {status === "streaming" ? (
                  <button
                    type="button"
                    className="send-button stop-button"
                    onClick={stop}
                    aria-label="Stop answer"
                  >
                    <Square size={17} fill="currentColor" />
                  </button>
                ) : (
                  <button
                    className="send-button"
                    type="submit"
                    disabled={!query.trim()}
                    aria-label="Ask question"
                  >
                    <ArrowUp size={20} />
                  </button>
                )}
              </div>
              <div className="composer-footnote" id="composer-help">
                <span>
                  <ShieldCheck size={13} />
                  Your current access context applies
                </span>
                <span>Enter to ask · Shift + Enter for a new line</span>
              </div>
            </form>
          </section>
          <div className="evidence-column">
            <Suspense fallback={<GraphPlaceholder />}>
              <GraphView
                graph={graph}
                citations={citations}
                openSource={setSourceId}
              />
            </Suspense>
            <section className="inspector-panel">
              <button
                className="inspector-toggle"
                onClick={() => setInspector((v) => !v)}
                aria-expanded={inspector}
                aria-controls="query-inspector"
              >
                <span>
                  <Layers size={17} />
                  <strong>Query inspector</strong>
                </span>
                <ChevronRight size={17} className={inspector ? "rotate" : ""} />
              </button>
              <p className="inspector-summary">
                Inspect the execution mode and server-reported query plan.
              </p>
              {inspector && (
                <div id="query-inspector" className="inspector-content">
                  <dl>
                    <div>
                      <dt>Answer mode</dt>
                      <dd>
                        {(
                          metadata.mode ||
                          health?.mode ||
                          "Not reported"
                        ).replaceAll("_", " ")}
                      </dd>
                    </div>
                    <div>
                      <dt>Graph store</dt>
                      <dd>
                        {String(
                          health?.adapters.graph_store || "Not reported",
                        ).replaceAll("_", " ")}
                      </dd>
                    </div>
                    <div>
                      <dt>Retrieval</dt>
                      <dd>
                        {String(
                          health?.adapters.vector_engine || "Not reported",
                        ).replaceAll("_", " ")}
                      </dd>
                    </div>
                    <div>
                      <dt>Reranker</dt>
                      <dd>
                        {String(
                          health?.adapters.reranker || "Not reported",
                        ).replaceAll("_", " ")}
                      </dd>
                    </div>
                  </dl>
                  {metadata.pipeline?.length ? (
                    <ol className="pipeline">
                      {metadata.pipeline.map((step, i) => (
                        <li key={i}>
                          <Check size={14} />
                          <span>
                            {typeof step === "string"
                              ? step
                              : step.name || step.stage || "Pipeline stage"}
                            {typeof step === "object" && step.status && (
                              <small>{step.status}</small>
                            )}
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="muted">
                      Run a query to receive its pipeline metadata.
                    </p>
                  )}
                  {metadata.transformed_cypher && (
                    <div className="cypher">
                      <h3>Server-transformed query</h3>
                      <pre>{metadata.transformed_cypher}</pre>
                    </div>
                  )}
                  <QueryConsole
                    token={session.access_token}
                    onExpired={onExpired}
                  />
                </div>
              )}
            </section>
            <div className="evidence-tip">
              <BookOpen size={17} />
              <p>
                Read beyond the answer.
                <span>
                  Open a citation to inspect the source document and its content
                  hash.
                </span>
              </p>
            </div>
          </div>
        </div>
      )}
      {sourceId && (
        <SourceDrawer
          documentId={sourceId}
          token={session.access_token}
          onClose={() => setSourceId(null)}
          onExpired={onExpired}
        />
      )}
    </>
  );
}

function CitedText({
  text,
  citations,
  openSource,
}: {
  text: string;
  citations: Citation[];
  openSource: (id: string) => void;
}) {
  return (
    <>
      {text.split(/(\[[^\]\n]{1,80}\])/g).map((part, index) => {
        if (!part.startsWith("[") || !part.endsWith("]")) return part;
        const key = part.slice(1, -1);
        const citation =
          citations.find(
            (c) => c.citation_id === key || c.document_id === key,
          ) ||
          (/^[1-9]\d*$/.test(key) ? citations[Number(key) - 1] : undefined);
        return citation ? (
          <button
            key={index}
            className="inline-citation"
            aria-label={`Read source: ${citation.document_title}`}
            onClick={() => openSource(citation.document_id)}
          >
            {part}
          </button>
        ) : (
          part
        );
      })}
    </>
  );
}

function QueryConsole({
  token,
  onExpired,
}: {
  token: string;
  onExpired: () => void;
}) {
  const [cypher, setCypher] = useState("MATCH (n) RETURN n.name LIMIT 10");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{
    columns: string[];
    rows: unknown[][];
    transformed_cypher?: string;
  } | null>(null);
  const newRequest = useRequests();
  async function run(event: FormEvent) {
    event.preventDefault();
    if (busy || !cypher.trim()) return;
    const { controller, release } = newRequest();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const response = await request<{
        columns: string[];
        rows: unknown[][];
        transformed_cypher?: string;
      }>("/query/cypher", {
        token,
        signal: controller.signal,
        body: { cypher, parameters: {} },
      });
      if (!Array.isArray(response.columns) || !Array.isArray(response.rows))
        throw new Error("Invalid query result");
      if (!controller.signal.aborted) setResult(response);
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (cause instanceof ApiError && cause.status === 401) {
        onExpired();
        return;
      }
      setError(
        cause instanceof ApiError && cause.status === 400
          ? "This query was rejected. Use a single bounded MATCH, optional WHERE, RETURN, and LIMIT."
          : errorMessage(cause, "graph query"),
      );
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      release();
    }
  }
  return (
    <section className="query-console">
      <h3>Read-only graph query</h3>
      <p>
        Explore returned records with the API’s restricted Cypher grammar. Your
        session policy applies to every request.
      </p>
      <form onSubmit={(event) => void run(event)}>
        <label htmlFor="cypher-query">Cypher query</label>
        <textarea
          id="cypher-query"
          value={cypher}
          rows={4}
          maxLength={4000}
          onChange={(event) => setCypher(event.target.value)}
          spellCheck={false}
        />
        <button className="secondary-button" disabled={busy || !cypher.trim()}>
          {busy ? (
            <LoaderCircle size={14} className="spin" />
          ) : (
            <GitBranch size={14} />
          )}
          {busy ? "Running query…" : "Run graph query"}
        </button>
      </form>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {result && (
        <div className="console-result">
          <p role="status">{result.rows.length} rows returned</p>
          {result.rows.length > 0 && (
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Graph query results"
            >
              <table>
                <thead>
                  <tr>
                    {result.columns.map((column, index) => (
                      <th key={index} scope="col">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, index) => (
                    <tr key={index}>
                      {result.columns.map((column, cell) => (
                        <td key={cell}>
                          {typeof (Array.isArray(row)
                            ? row[cell]
                            : (row as Record<string, unknown>)[column]) ===
                          "object"
                            ? JSON.stringify(
                                Array.isArray(row)
                                  ? row[cell]
                                  : (row as Record<string, unknown>)[column],
                              )
                            : String(
                                (Array.isArray(row)
                                  ? row[cell]
                                  : (row as Record<string, unknown>)[column]) ??
                                  "—",
                              )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {result.transformed_cypher && (
            <div className="cypher">
              <h3>Server-transformed query</h3>
              <pre>{result.transformed_cypher}</pre>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function SourceDrawer({
  documentId,
  token,
  onClose,
  onExpired,
}: {
  documentId: string;
  token: string;
  onClose: () => void;
  onExpired: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setSource(null);
    setError("");
    request<Source>(`/sources/${encodeURIComponent(documentId)}`, {
      token,
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setSource(result);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        if (cause instanceof ApiError && cause.status === 401) {
          onExpired();
          return;
        }
        setError(errorMessage(cause, "source request"));
      });
    return () => controller.abort();
  }, [documentId, token, retry, onExpired]);
  return (
    <dialog
      className="source-drawer"
      ref={dialog}
      onCancel={onClose}
      aria-labelledby="source-title"
      onClick={(event) => {
        if (
          event.target === dialog.current &&
          event.clientX < dialog.current.getBoundingClientRect().left
        )
          onClose();
      }}
    >
      <div className="drawer-header">
        <span>
          <FileText size={18} />
          Source document
        </span>
        <button
          className="icon-button"
          aria-label="Close source"
          onClick={onClose}
          autoFocus
        >
          <X size={21} />
        </button>
      </div>
      <div className="drawer-content">
        <h2 id="source-title">{source?.title || "Source evidence"}</h2>
        {!source && !error && (
          <p role="status" className="loading-line">
            <LoaderCircle className="spin" size={18} />
            Retrieving the source with your session…
          </p>
        )}
        {error && (
          <div role="alert" className="query-error">
            <p>{error}</p>
            <button
              className="secondary-button"
              onClick={() => setRetry((v) => v + 1)}
            >
              Retry source
            </button>
          </div>
        )}
        {source && (
          <>
            <div className="source-badges">
              <span>{classify(source.classification_level)}</span>
              <span>{source.department}</span>
            </div>
            <article className="source-content">{source.content}</article>
            <section className="provenance">
              <h3>
                <ShieldCheck size={17} />
                Provenance record
              </h3>
              <dl>
                <div>
                  <dt>Document ID</dt>
                  <dd>{source.document_id}</dd>
                </div>
                <div>
                  <dt>Source reference</dt>
                  <dd>{source.source_uri || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Content hash</dt>
                  <dd className="content-hash">{source.content_hash}</dd>
                </div>
              </dl>
              <p>
                Source references are shown as text. Content is retrieved
                through the authenticated knowledge API.
              </p>
            </section>
          </>
        )}
      </div>
    </dialog>
  );
}

function Ingestion({
  session,
  onExpired,
}: {
  session: Session;
  onExpired: () => void;
}) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [uri, setUri] = useState("");
  const [department, setDepartment] = useState("public");
  const [level, setLevel] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{
    document_id: string;
    content_hash: string;
    chunks_created: number;
    graph_indexing?: string;
  } | null>(null);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const newRequest = useRequests();
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const { controller, release } = newRequest();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const response = await request<{
        document_id: string;
        content_hash: string;
        chunks_created: number;
        graph_indexing?: string;
      }>("/ingest", {
        token: session.access_token,
        signal: controller.signal,
        body: {
          title: title.trim(),
          content,
          source_uri: uri.trim(),
          classification_level: level,
          department,
          extract_entities: true,
        },
      });
      if (!controller.signal.aborted) setResult(response);
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (cause instanceof ApiError && cause.status === 401) {
        onExpired();
        return;
      }
      setError(errorMessage(cause, "document ingestion"));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      release();
    }
  }
  return (
    <section className="ingest-panel">
      <div className="section-heading">
        <div>
          <Database size={19} />
          <h2>Add knowledge</h2>
        </div>
        <span className="quiet-badge">Authenticated ingestion</span>
      </div>
      <div className="ingest-layout">
        <form onSubmit={(event) => void submit(event)}>
          <h3>A new source, with provenance.</h3>
          <p className="muted">
            Add a text document to your current tenant. The API validates your
            permission and records the content hash.
          </p>
          <label htmlFor="document-title">Document title</label>
          <input
            id="document-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            maxLength={240}
            placeholder="Give this source a clear title"
          />
          <label htmlFor="document-content">Document content</label>
          <textarea
            id="document-content"
            rows={8}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            required
            maxLength={100000}
            placeholder="Paste the source text…"
          />
          <label htmlFor="document-uri">
            Source reference <span className="muted">(optional)</span>
          </label>
          <input
            id="document-uri"
            value={uri}
            onChange={(e) => setUri(e.target.value)}
            maxLength={1000}
            placeholder="e.g. internal://documents/project-notes"
          />
          <div className="form-row">
            <div>
              <label htmlFor="classification">Document classification</label>
              <select
                id="classification"
                value={level}
                onChange={(e) => setLevel(Number(e.target.value))}
              >
                {[1, 2, 3, 4]
                  .filter((l) => l <= session.claims.clearance_level)
                  .map((l) => (
                    <option key={l} value={l}>
                      {classify(l)} · L{l}
                    </option>
                  ))}
              </select>
            </div>
            <div>
              <label htmlFor="department">Document department</label>
              <select
                id="department"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
              >
                {Array.from(
                  new Set(["public", ...session.claims.departments]),
                ).map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {error && (
            <p className="inline-error" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            className="primary-button"
            disabled={busy || !title.trim() || !content.trim()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <ArrowDownToLine size={17} />
            )}
            {busy ? "Adding document…" : "Add document"}
          </button>
          {result && (
            <div className="ingest-success" role="status">
              <CheckCheck size={21} />
              <div>
                <strong>
                  {result.graph_indexing === "pending"
                    ? "Document stored, graph indexing pending"
                    : "Document added"}
                </strong>
                {result.graph_indexing === "pending" ? (
                  <p>
                    Document is stored, but graph indexing is pending and not
                    searchable yet. Retries occur on configured service restart
                    or next ingestion; consult docs/RUNBOOK.md.
                  </p>
                ) : (
                  <p>{result.chunks_created} chunks created by the API.</p>
                )}
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setSourceId(result.document_id)}
                >
                  Read added source
                </button>
                <code>{result.content_hash}</code>
              </div>
            </div>
          )}
        </form>
        <aside className="ingest-note">
          <ShieldCheck size={27} strokeWidth={1.3} />
          <h3>Stored within your tenant</h3>
          <p>{session.claims.tenant_id}</p>
          <p>
            Classification and department describe this document. Your
            identity’s permissions are set by the server.
          </p>
          <p>The API enforces ingestion permissions and source provenance.</p>
        </aside>
      </div>
      {sourceId && (
        <SourceDrawer
          documentId={sourceId}
          token={session.access_token}
          onClose={() => setSourceId(null)}
          onExpired={onExpired}
        />
      )}
    </section>
  );
}
