// Mirrors app/schemas.py's OrderOut / EmployeeOut / AssignmentRunResult
// field-for-field -- kept as plain types (not generated) since the API
// is small and stable enough that hand-syncing is simpler than adding a
// codegen step. If the two ever drift, a TypeScript error at the fetch
// call site is the signal to update this file.

export type Priority = "low" | "normal" | "high" | "urgent";

// received -> validated -> (duplicate | rejected | assigned) -- see
// app/models.py's Order.status docstring for the full state machine.
export type OrderStatus =
  | "received"
  | "validated"
  | "rejected"
  | "duplicate"
  | "assigned";

export interface Order {
  id: number;
  customer_name: string;
  description: string;
  location: string | null;
  priority: Priority;
  required_skills: string | null; // comma-separated
  status: OrderStatus;
  validation_errors: string[];
  duplicate_of_id: number | null;
  assigned_employee_id: number | null;
  assigned_at: string | null; // ISO datetime
  // Phase 3: always populated if classification ran, regardless of
  // whether it was confident enough to fill required_skills above.
  ai_suggested_skills: string | null;
  ai_suggested_priority: Priority | null;
  ai_confidence: number | null;
  ai_reasoning: string | null;
  ai_classified_at: string | null;
  created_at: string;
}

export interface Employee {
  id: number;
  name: string;
  location: string | null;
  skills: string | null; // comma-separated
  daily_capacity: number;
  created_at: string;
}

export type AssignmentStrategy = "fcfs" | "optimized";

export interface AssignmentRunResult {
  strategy: AssignmentStrategy;
  considered: number;
  assigned: number;
  unassigned: number;
  assigned_order_ids: number[];
}

export interface OrderCreatePayload {
  customer_name: string;
  description: string;
  location?: string;
  priority?: Priority;
  required_skills?: string;
}

export interface EmployeeCreatePayload {
  name: string;
  location?: string;
  skills?: string;
  daily_capacity?: number;
}
