import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, createEmployee } from "../api";

interface Props {
  onCreated: () => void;
}

export function NewEmployeeForm({ onCreated }: Props) {
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [skills, setSkills] = useState("");
  const [dailyCapacity, setDailyCapacity] = useState(5);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createEmployee({
        name,
        location: location || undefined,
        skills: skills || undefined,
        daily_capacity: dailyCapacity,
      });
      setName("");
      setLocation("");
      setSkills("");
      setDailyCapacity(5);
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to add employee.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="panel-form" onSubmit={handleSubmit}>
      <div className="form-row">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          Location
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
      </div>
      <div className="form-row">
        <label>
          Skills <span className="label-hint">(comma-separated)</span>
          <input
            value={skills}
            onChange={(e) => setSkills(e.target.value)}
            placeholder="e.g. electrical,hvac"
          />
        </label>
        <label>
          Daily capacity
          <input
            type="number"
            min={1}
            value={dailyCapacity}
            onChange={(e) => setDailyCapacity(Number(e.target.value))}
          />
        </label>
      </div>
      {error && <p className="form-error">{error}</p>}
      <button type="submit" disabled={submitting}>
        {submitting ? "Adding..." : "Add employee"}
      </button>
    </form>
  );
}
