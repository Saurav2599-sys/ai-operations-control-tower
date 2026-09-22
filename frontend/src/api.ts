// Thin fetch wrapper over app/api.py -- one function per endpoint, no
// client library (axios, react-query, etc.). The API surface is small
// enough that a dependency here would be overhead without a real
// benefit, same reasoning as the backend choosing plain OpenAI SDK over
// a framework for Phase 3.

import type {
  AssignmentRunResult,
  AssignmentStrategy,
  Employee,
  EmployeeCreatePayload,
  Order,
  OrderCreatePayload,
  OrderStatus,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    // A network-level failure (API not running, CORS blocked, DNS) --
    // distinguished from an HTTP error status below so the UI can show
    // "can't reach the API" rather than a confusing generic message.
    throw new ApiError(0, `Could not reach the API at ${BASE_URL}. Is uvicorn running?`);
  }

  if (!response.ok) {
    // FastAPI's HTTPException responses are {"detail": "..."} -- surface
    // that message when present rather than just the status code.
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Response wasn't JSON -- fall back to statusText above.
    }
    throw new ApiError(response.status, detail);
  }

  // 204 No Content, or any other truly empty response.
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listOrders(status?: OrderStatus): Promise<Order[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<Order[]>(`/orders${query}`);
}

export function createOrder(payload: OrderCreatePayload): Promise<Order> {
  return request<Order>("/orders", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function reclassifyOrder(orderId: number): Promise<Order> {
  return request<Order>(`/orders/${orderId}/classify`, { method: "POST" });
}

export function listEmployees(): Promise<Employee[]> {
  return request<Employee[]>("/employees");
}

export function createEmployee(payload: EmployeeCreatePayload): Promise<Employee> {
  return request<Employee>("/employees", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function runAssignment(strategy: AssignmentStrategy): Promise<AssignmentRunResult> {
  return request<AssignmentRunResult>(`/assignments/run?strategy=${strategy}`, {
    method: "POST",
  });
}
