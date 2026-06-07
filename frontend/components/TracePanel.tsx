"use client";

import { useState } from "react";
import { TraceSummary } from "@/lib/api";

// Trace visibility is a feature. Plain-language steps, each expandable to the full
// agent reasoning, with a link to the hosted Weave dashboard.
export function TracePanel({ trace }: { trace: TraceSummary }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="hint">{trace.span_count} traced steps</span>
        <div className="spacer" />
        {Object.entries(trace.by_kind).map(([k, n]) => (
          <span className="pill" key={k}>{k}: {n}</span>
        ))}
      </div>
      {trace.weave_url && (
        <div className="banner" style={{ marginBottom: 12 }}>
          Full trace on the W&B Weave dashboard:{" "}
          <a href={trace.weave_url} target="_blank" rel="noreferrer">{trace.weave_url}</a>
        </div>
      )}
      <div>
        {trace.steps.map((s) => (
          <div key={s.id}>
            <div className="trace-step" onClick={() => setOpen(open === s.id ? null : s.id)}>
              <span className="trace-kind">{s.category}</span>
              <span className="trace-label">
                {s.label}
                {s.error ? <span style={{ color: "var(--danger)" }}> · error</span> : null}
              </span>
              <span className="trace-dur">{s.duration_ms} ms</span>
            </div>
            {open === s.id && (
              <div className="trace-detail">
                {JSON.stringify(s.detail, null, 2)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
