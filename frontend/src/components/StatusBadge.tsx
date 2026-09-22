import type { OrderStatus } from "../types";

const STATUS_LABEL: Record<OrderStatus, string> = {
  received: "Received",
  validated: "Validated",
  assigned: "Assigned",
  duplicate: "Duplicate",
  rejected: "Rejected",
};

export function StatusBadge({ status }: { status: OrderStatus }) {
  return <span className={`badge badge-status-${status}`}>{STATUS_LABEL[status]}</span>;
}
