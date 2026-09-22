import { useCallback, useEffect, useState } from "react";
import { ApiError, listEmployees } from "../api";
import type { Employee } from "../types";
import { NewEmployeeForm } from "./NewEmployeeForm";

export function EmployeesView() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const fetchEmployees = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEmployees(await listEmployees());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load employees.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEmployees();
  }, [fetchEmployees]);

  return (
    <section>
      <div className="view-toolbar">
        <p className="view-subtitle">
          {employees.length} employee{employees.length === 1 ? "" : "s"}
        </p>
        <div className="toolbar-actions">
          <button className="secondary" onClick={() => fetchEmployees()}>
            Refresh
          </button>
          <button onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "Add employee"}
          </button>
        </div>
      </div>

      {showForm && (
        <NewEmployeeForm
          onCreated={() => {
            setShowForm(false);
            fetchEmployees();
          }}
        />
      )}

      {error && <p className="form-error">{error}</p>}
      {loading ? (
        <p className="empty-state">Loading...</p>
      ) : employees.length === 0 ? (
        <p className="empty-state">
          No employees yet -- add one before running an assignment, or nothing will match.
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Location</th>
                <th>Skills</th>
                <th>Daily capacity</th>
              </tr>
            </thead>
            <tbody>
              {employees.map((e) => (
                <tr key={e.id}>
                  <td>{e.id}</td>
                  <td>{e.name}</td>
                  <td>{e.location ?? <em>--</em>}</td>
                  <td>{e.skills ?? <em>none</em>}</td>
                  <td>{e.daily_capacity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
