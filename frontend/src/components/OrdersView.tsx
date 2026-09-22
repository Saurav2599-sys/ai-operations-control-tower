import { useCallback, useEffect, useState } from "react";
import { ApiError, listOrders, reclassifyOrder } from "../api";
import type { Order, OrderStatus } from "../types";
import { StatusBadge } from "./StatusBadge";
import { PriorityBadge } from "./PriorityBadge";
import { AiSuggestionCell } from "./AiSuggestionCell";
import { NewOrderForm } from "./NewOrderForm";

const STATUS_FILTERS: Array<OrderStatus | "all"> = [
  "all",
  "validated",
  "assigned",
  "duplicate",
  "rejected",
];

interface Props {
  // Bumped by App whenever an assignment run completes, so this view
  // refetches and shows the newly-assigned orders without the user
  // having to manually switch tabs and back.
  refreshSignal: number;
}

export function OrdersView({ refreshSignal }: Props) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [statusFilter, setStatusFilter] = useState<OrderStatus | "all">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reclassifyingId, setReclassifyingId] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listOrders(statusFilter === "all" ? undefined : statusFilter);
      setOrders(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load orders.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders, refreshSignal]);

  async function handleReclassify(orderId: number) {
    setReclassifyingId(orderId);
    try {
      const updated = await reclassifyOrder(orderId);
      setOrders((prev) => prev.map((o) => (o.id === updated.id ? updated : o)));
    } catch {
      // A reclassify failure (e.g. OpenAI down) is expected sometimes --
      // app/api.py surfaces it as a 502. Nothing to do here beyond not
      // crashing the row; the order's ai_* fields simply stay as they
      // were before this click.
    } finally {
      setReclassifyingId(null);
    }
  }

  return (
    <section>
      <div className="view-toolbar">
        <div className="filter-group">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              className={s === statusFilter ? "filter-btn filter-btn-active" : "filter-btn"}
              onClick={() => setStatusFilter(s)}
            >
              {s === "all" ? "All" : s[0].toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
        <div className="toolbar-actions">
          <button className="secondary" onClick={() => fetchOrders()}>
            Refresh
          </button>
          <button onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "New order"}
          </button>
        </div>
      </div>

      {showForm && (
        <NewOrderForm
          onCreated={() => {
            setShowForm(false);
            fetchOrders();
          }}
        />
      )}

      {error && <p className="form-error">{error}</p>}
      {loading ? (
        <p className="empty-state">Loading...</p>
      ) : orders.length === 0 ? (
        <p className="empty-state">No orders match this filter.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Customer</th>
                <th>Description</th>
                <th>Priority</th>
                <th>Required skills</th>
                <th>Status</th>
                <th>Assigned to</th>
                <th>AI suggestion</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.id}>
                  <td>{order.id}</td>
                  <td>{order.customer_name}</td>
                  <td className="description-cell" title={order.description}>
                    {order.description}
                  </td>
                  <td>
                    <PriorityBadge priority={order.priority} />
                  </td>
                  <td>{order.required_skills ?? <em>none</em>}</td>
                  <td>
                    <StatusBadge status={order.status} />
                    {order.validation_errors.length > 0 && (
                      <div
                        className="validation-errors"
                        title={order.validation_errors.join("; ")}
                      >
                        {order.validation_errors.length} issue
                        {order.validation_errors.length > 1 ? "s" : ""}
                      </div>
                    )}
                  </td>
                  <td>{order.assigned_employee_id ?? <em>--</em>}</td>
                  <td>
                    <AiSuggestionCell order={order} />
                  </td>
                  <td>
                    <button
                      className="secondary small"
                      disabled={reclassifyingId === order.id}
                      onClick={() => handleReclassify(order.id)}
                    >
                      {reclassifyingId === order.id ? "..." : "Reclassify"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
