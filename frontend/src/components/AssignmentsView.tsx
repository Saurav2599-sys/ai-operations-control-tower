import { useState } from "react";
import { ApiError, runAssignment } from "../api";
import type { AssignmentRunResult, AssignmentStrategy } from "../types";

interface Props {
  // Called after a successful run so App can bump OrdersView's
  // refreshSignal -- this view doesn't own the orders list itself.
  onRunComplete: () => void;
}

const STRATEGIES: Array<{ value: AssignmentStrategy; label: string; blurb: string }> = [
  {
    value: "optimized",
    label: "Optimized (OR-Tools CP-SAT)",
    blurb:
      "Maximizes priority-weighted, capacity-constrained matches across all eligible orders at once. See the README's Phase 2 benchmark for real numbers against the baseline below.",
  },
  {
    value: "fcfs",
    label: "FCFS (naive baseline)",
    blurb: "Greedy, submission-order assignment -- the baseline the optimizer is measured against.",
  },
];

export function AssignmentsView({ onRunComplete }: Props) {
  const [strategy, setStrategy] = useState<AssignmentStrategy>("optimized");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AssignmentRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRun() {
    setRunning(true);
    setError(null);
    try {
      const r = await runAssignment(strategy);
      setResult(r);
      onRunComplete();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Assignment run failed.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <section>
      <p className="view-subtitle">
        Assigns every currently-unassigned, validated order to an employee. Orders that can't be
        matched (no employee covers the required skills, or everyone capable is already at
        capacity for this run) are left as "validated" -- eligible for the next run, not lost.
      </p>

      <div className="strategy-picker">
        {STRATEGIES.map((s) => (
          <label
            key={s.value}
            className={s.value === strategy ? "strategy-option strategy-option-active" : "strategy-option"}
          >
            <input
              type="radio"
              name="strategy"
              value={s.value}
              checked={strategy === s.value}
              onChange={() => setStrategy(s.value)}
            />
            <div>
              <div className="strategy-label">{s.label}</div>
              <div className="strategy-blurb">{s.blurb}</div>
            </div>
          </label>
        ))}
      </div>

      <button onClick={handleRun} disabled={running}>
        {running ? "Running..." : `Run assignment (${strategy})`}
      </button>

      {error && <p className="form-error">{error}</p>}

      {result && (
        <div className="run-result">
          <h3>Result</h3>
          <dl>
            <dt>Strategy</dt>
            <dd>{result.strategy}</dd>
            <dt>Considered</dt>
            <dd>{result.considered}</dd>
            <dt>Assigned</dt>
            <dd>{result.assigned}</dd>
            <dt>Unassigned</dt>
            <dd>{result.unassigned}</dd>
          </dl>
          {result.assigned_order_ids.length > 0 && (
            <p className="run-result-ids">
              Assigned order IDs: {result.assigned_order_ids.join(", ")} -- see the Orders tab.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
