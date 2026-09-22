import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, createOrder } from "../api";
import type { Priority } from "../types";

interface Props {
  onCreated: () => void;
}

const PRIORITIES: Priority[] = ["low", "normal", "high", "urgent"];

// Deliberately leaves required_skills blank by default -- submitting
// with it empty is what exercises Phase 3's classification path (see
// app/api.py's submit_order()), which is usually the more interesting
// thing to demo from this form than typing skills in by hand.
export function NewOrderForm({ onCreated }: Props) {
  const [customerName, setCustomerName] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [priority, setPriority] = useState<Priority>("normal");
  const [requiredSkills, setRequiredSkills] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createOrder({
        customer_name: customerName,
        description,
        location: location || undefined,
        priority,
        required_skills: requiredSkills || undefined,
      });
      setCustomerName("");
      setDescription("");
      setLocation("");
      setPriority("normal");
      setRequiredSkills("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit order.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="panel-form" onSubmit={handleSubmit}>
      <div className="form-row">
        <label>
          Customer name
          <input
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
            required
          />
        </label>
        <label>
          Location
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
      </div>
      <label>
        Description
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          required
        />
      </label>
      <div className="form-row">
        <label>
          Priority
          <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label>
          Required skills{" "}
          <span className="label-hint">(comma-separated, leave blank to let AI suggest)</span>
          <input
            value={requiredSkills}
            onChange={(e) => setRequiredSkills(e.target.value)}
            placeholder="e.g. plumbing,hvac"
          />
        </label>
      </div>
      {error && <p className="form-error">{error}</p>}
      <button type="submit" disabled={submitting}>
        {submitting ? "Submitting..." : "Submit order"}
      </button>
    </form>
  );
}
