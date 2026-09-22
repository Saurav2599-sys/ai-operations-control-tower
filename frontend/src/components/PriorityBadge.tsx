import type { Priority } from "../types";

export function PriorityBadge({ priority }: { priority: Priority }) {
  return (
    <span className={`badge badge-priority-${priority}`}>
      {priority[0].toUpperCase() + priority.slice(1)}
    </span>
  );
}
