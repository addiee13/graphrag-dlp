import { useEffect, useRef, useState } from "react";
import cytoscape, { type Core } from "cytoscape";
import { Focus, Minus, Network, Plus } from "lucide-react";
import type { Citation, GraphPayload } from "./api";

export default function GraphView({
  graph,
  citations,
  openSource,
}: {
  graph: GraphPayload;
  citations: Citation[];
  openSource: (id: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<Core | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const { nodes, edges } = graph.elements;

  useEffect(() => {
    setSelected(null);
    setFailed(false);
    if (!container.current || !nodes.length) return;
    const ids = new Set(nodes.map((n) => n.data.id));
    try {
      // Explicitly map the server payload. No fabricated or placeholder graph entities.
      const cy = cytoscape({
        container: container.current,
        elements: [
          ...nodes.map(({ data }) => ({
            data: {
              id: data.id,
              label: data.label,
              type: data.type || "Entity",
            },
          })),
          ...edges
            .filter((e) => ids.has(e.data.source) && ids.has(e.data.target))
            .map(({ data }) => ({
              data: {
                id: data.id,
                source: data.source,
                target: data.target,
                label: data.label || "Related",
              },
            })),
        ],
        layout: {
          name: "cose",
          animate: false,
          padding: 45,
          nodeRepulsion: () => 16000,
          idealEdgeLength: () => 115,
        },
        minZoom: 0.3,
        maxZoom: 2.5,
        wheelSensitivity: 0.2,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "#486b95",
              "border-color": "#fff",
              "border-width": 3,
              width: 35,
              height: 35,
              label: "data(label)",
              color: "#23374e",
              "font-family": "IBM Plex Sans, sans-serif",
              "font-size": 12,
              "text-valign": "bottom",
              "text-margin-y": 9,
              "text-wrap": "wrap",
              "text-max-width": "110px",
              "text-background-color": "#f5f8fb",
              "text-background-opacity": 0.92,
              "text-background-padding": "3px",
            },
          },
          {
            selector: 'node[type="Project"]',
            style: {
              shape: "round-rectangle",
              "background-color": "#365de1",
              width: 43,
              height: 43,
            },
          },
          {
            selector: 'node[type="Person"]',
            style: { "background-color": "#2e796c" },
          },
          {
            selector: "edge",
            style: {
              width: 1.5,
              "line-color": "#98acc3",
              "target-arrow-color": "#98acc3",
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              label: "data(label)",
              "font-size": 9,
              color: "#50647c",
              "text-rotation": "autorotate",
              "text-background-color": "#f5f8fb",
              "text-background-opacity": 1,
              "text-background-padding": "4px",
            },
          },
          {
            selector: ":selected",
            style: { "border-color": "#10253d", "border-width": 4 },
          },
        ],
      });
      instance.current = cy;
      cy.on("tap", "node", (event) => setSelected(event.target.id()));
      const resize = new ResizeObserver(() => {
        cy.resize();
        cy.fit(undefined, 45);
      });
      resize.observe(container.current);
      return () => {
        resize.disconnect();
        cy.destroy();
        instance.current = null;
      };
    } catch {
      setFailed(true);
    }
  }, [nodes, edges]);

  function select(id: string) {
    setSelected(id);
    const cy = instance.current;
    if (cy) {
      cy.elements().unselect();
      cy.getElementById(id).select();
    }
  }
  const selectedNode = nodes.find((n) => n.data.id === selected);
  const evidence = citations.filter((c) =>
    c.source_node_ids?.includes(selected || ""),
  );
  return (
    <section className="graph-panel" aria-labelledby="graph-heading">
      <div className="section-heading">
        <div>
          <span className="section-icon">
            <Network size={18} />
          </span>
          <h2 id="graph-heading">Evidence graph</h2>
        </div>
        <span className="quiet-badge">
          {nodes.length ? `${nodes.length} returned nodes` : "Awaiting query"}
        </span>
      </div>
      <div className="graph-canvas-wrap">
        <div
          ref={container}
          className="graph-canvas"
          aria-hidden="true"
          data-testid="graph-canvas"
        />
        {!nodes.length && (
          <div className="graph-empty">
            <div className="graph-empty-mark">
              <Network size={32} strokeWidth={1.2} />
            </div>
            <strong>See how the answer connects</strong>
            <p>
              Run a query to explore the entities and relationships returned
              with its evidence.
            </p>
          </div>
        )}
        {!!nodes.length && (
          <div className="graph-tools" aria-label="Graph controls">
            <button
              aria-label="Zoom in"
              onClick={() =>
                instance.current?.zoom((instance.current?.zoom() || 1) * 1.2)
              }
            >
              <Plus size={17} />
            </button>
            <button
              aria-label="Zoom out"
              onClick={() =>
                instance.current?.zoom((instance.current?.zoom() || 1) / 1.2)
              }
            >
              <Minus size={17} />
            </button>
            <button
              aria-label="Fit graph"
              onClick={() => instance.current?.fit(undefined, 45)}
            >
              <Focus size={17} />
            </button>
          </div>
        )}
      </div>
      {failed && (
        <p className="inline-error" role="status">
          Graph rendering is unavailable. Explore the same returned entities
          below.
        </p>
      )}
      {!!nodes.length && (
        <div className="graph-accessible">
          <label htmlFor="graph-entity">Explore a returned entity</label>
          <select
            id="graph-entity"
            value={selected || ""}
            onChange={(e) => select(e.target.value)}
          >
            <option value="">Choose an entity</option>
            {nodes.map((n) => (
              <option key={n.data.id} value={n.data.id}>
                {n.data.label}
              </option>
            ))}
          </select>
          {selectedNode && (
            <div className="entity-detail">
              <strong>{selectedNode.data.label}</strong>
              <span>{selectedNode.data.type || "Entity"}</span>
              <ul>
                {edges
                  .filter(
                    (e) =>
                      e.data.source === selected || e.data.target === selected,
                  )
                  .map((e) => (
                    <li key={e.data.id}>
                      {
                        nodes.find((n) => n.data.id === e.data.source)?.data
                          .label
                      }{" "}
                      <span>
                        {(e.data.label || "related to")
                          .replaceAll("_", " ")
                          .toLowerCase()}
                      </span>{" "}
                      {
                        nodes.find((n) => n.data.id === e.data.target)?.data
                          .label
                      }
                    </li>
                  ))}
              </ul>
              {evidence.map((c) => (
                <button
                  className="text-button"
                  key={c.citation_id}
                  onClick={() => openSource(c.document_id)}
                >
                  Read {c.document_title}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      <p className="panel-footnote">
        <span className="evidence-dot" /> Only the graph returned for this query
        is shown.
      </p>
    </section>
  );
}
