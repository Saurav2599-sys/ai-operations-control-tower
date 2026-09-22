import type { Order } from "../types";

// Renders what Phase 3 actually produced for this order, distinctly from
// the authoritative required_skills/priority columns elsewhere in the
// row -- the whole point of "suggestion, never override" (see the
// README) is that these stay visibly separate, including in the UI,
// rather than silently merged into one column.
export function AiSuggestionCell({ order }: { order: Order }) {
  if (!order.ai_classified_at) {
    return <span className="ai-cell ai-cell-none">--</span>;
  }

  const confidencePct = order.ai_confidence !== null ? Math.round(order.ai_confidence * 100) : null;
  const wasApplied =
    order.required_skills !== null && order.required_skills === order.ai_suggested_skills;

  return (
    <div className="ai-cell" title={order.ai_reasoning ?? undefined}>
      <div className="ai-cell-skills">
        {order.ai_suggested_skills || <em>no skills suggested</em>}
      </div>
      <div className="ai-cell-meta">
        {order.ai_suggested_priority && (
          <span className="ai-cell-priority">
            priority: {order.ai_suggested_priority}
            <span className="ai-cell-priority-note"> (never auto-applied)</span>
          </span>
        )}
        {confidencePct !== null && (
          <span className={confidencePct === 0 ? "ai-cell-conf-zero" : "ai-cell-conf"}>
            conf {confidencePct}%
          </span>
        )}
        {/* Named "skills applied", not bare "applied" -- this only ever
            reflects required_skills being copied over. Priority is never
            auto-applied at any confidence (see the README's Phase 3
            design notes), so the "(never auto-applied)" note next to it
            above is unconditional, not just shown when it wasn't this
            time -- otherwise a viewer could misread the single checkmark
            here as covering both fields. */}
        {wasApplied && <span className="ai-cell-applied">skills applied ✓</span>}
      </div>
    </div>
  );
}
