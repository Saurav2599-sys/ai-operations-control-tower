import { useState } from "react";
import { OrdersView } from "./components/OrdersView";
import { EmployeesView } from "./components/EmployeesView";
import { AssignmentsView } from "./components/AssignmentsView";

type Tab = "orders" | "employees" | "assignments";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "orders", label: "Orders" },
  { id: "employees", label: "Employees" },
  { id: "assignments", label: "Assignments" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("orders");
  // Bumped whenever an assignment run completes; OrdersView refetches
  // whenever this changes even while a different tab is showing, so
  // switching back to Orders always reflects the latest run without a
  // manual refresh click. No routing library, no global state manager --
  // one counter passed down is all three views need to stay in sync.
  const [refreshSignal, setRefreshSignal] = useState(0);

  return (
    <div className="app">
      <header className="app-header">
        <h1>AI Operations Control Tower</h1>
        <p className="app-subtitle">
          Order ingestion, OR-Tools scheduling, and LLM classification -- against the real API.
        </p>
      </header>

      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={t.id === tab ? "tab tab-active" : "tab"}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="app-main">
        {tab === "orders" && <OrdersView refreshSignal={refreshSignal} />}
        {tab === "employees" && <EmployeesView />}
        {tab === "assignments" && (
          <AssignmentsView onRunComplete={() => setRefreshSignal((n) => n + 1)} />
        )}
      </main>
    </div>
  );
}
