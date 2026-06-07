"use client";

import { NegotiationResult } from "@/lib/api";

// 2D utility space: buyer utility (x) vs seller utility (y). Shows the negotiation
// trajectory converging and, when an improved run is supplied, that the deal moved
// "up and to the right".
export function UtilityPlot({
  baseline,
  improved,
}: {
  baseline: NegotiationResult;
  improved?: NegotiationResult | null;
}) {
  const W = 460;
  const H = 360;
  const pad = 44;
  const sx = (v: number) => pad + (v / 100) * (W - pad * 2);
  const sy = (v: number) => H - pad - (v / 100) * (H - pad * 2);

  const path = (r: NegotiationResult) =>
    r.transcript.map((t) => ({ x: t.buyer_utility ?? 0, y: t.seller_utility ?? 0 }));

  const basePath = path(baseline);
  const baseDeal = baseline.score
    ? { x: baseline.score.buyer_score, y: baseline.score.seller_score }
    : null;
  const impDeal =
    improved && improved.score
      ? { x: improved.score.buyer_score, y: improved.score.seller_score }
      : null;

  const ticks = [0, 25, 50, 75, 100];

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W }}>
        {/* grid */}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={sx(t)} y1={pad} x2={sx(t)} y2={H - pad} stroke="#f0f0ee" />
            <line x1={pad} y1={sy(t)} x2={W - pad} y2={sy(t)} stroke="#f0f0ee" />
            <text x={sx(t)} y={H - pad + 16} fontSize="10" fill="#9a9a94" textAnchor="middle">{t}</text>
            <text x={pad - 8} y={sy(t) + 3} fontSize="10" fill="#9a9a94" textAnchor="end">{t}</text>
          </g>
        ))}
        {/* axes labels */}
        <text x={W / 2} y={H - 6} fontSize="11" fill="#6b6b66" textAnchor="middle">Buyer utility</text>
        <text x={14} y={H / 2} fontSize="11" fill="#6b6b66" textAnchor="middle" transform={`rotate(-90 14 ${H / 2})`}>Seller utility</text>

        {/* baseline trajectory */}
        <polyline
          fill="none"
          stroke="#c9c9c4"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          points={basePath.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")}
        />
        {basePath.map((p, i) => (
          <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={2.5} fill="#c9c9c4" />
        ))}

        {/* baseline deal */}
        {baseDeal && (
          <g>
            <circle cx={sx(baseDeal.x)} cy={sy(baseDeal.y)} r={6} fill="#6b6b66" />
            <text x={sx(baseDeal.x) + 9} y={sy(baseDeal.y) - 8} fontSize="10" fill="#6b6b66">baseline</text>
          </g>
        )}

        {/* improvement arrow + improved deal */}
        {baseDeal && impDeal && (
          <g>
            <defs>
              <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill="#1f7a63" />
              </marker>
            </defs>
            <line
              x1={sx(baseDeal.x)} y1={sy(baseDeal.y)}
              x2={sx(impDeal.x)} y2={sy(impDeal.y)}
              stroke="#1f7a63" strokeWidth={1.5} markerEnd="url(#arrow)"
            />
            <circle cx={sx(impDeal.x)} cy={sy(impDeal.y)} r={6} fill="#1f7a63" />
            <text x={sx(impDeal.x) + 9} y={sy(impDeal.y) - 8} fontSize="10" fill="#1f7a63">improved</text>
          </g>
        )}
      </svg>
      <div className="legend">
        <span><span className="sw" style={{ background: "#c9c9c4" }} />trajectory</span>
        <span><span className="sw" style={{ background: "#6b6b66" }} />baseline deal</span>
        {impDeal && <span><span className="sw" style={{ background: "#1f7a63" }} />after self-improvement</span>}
      </div>
    </div>
  );
}
