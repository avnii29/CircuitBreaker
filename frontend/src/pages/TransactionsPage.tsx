import { useEffect, useMemo, useState } from "react";
import { LiveFailureStream } from "../components/LiveFailureStream";
import { AuditDrawer } from "../components/AuditDrawer";
import { StatusPill } from "../components/StatusPill";
import type { CircuitBreakerState } from "../hooks/useCircuitBreaker";
import type { TransactionState } from "../types";
import { isActiveRecovery, STATE_SORT_ORDER } from "../types";
import { cx, formatINR } from "../lib/format";

const FILTERS: { id: "ALL" | TransactionState; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "AUTOMATED_LOOP", label: "In recovery" },
  { id: "RECOVERED", label: "Rescued" },
  { id: "ESCALATED", label: "Escalated" },
  { id: "FAILED", label: "Failed" },
];

export function TransactionsPage({
  state,
  onOpenRecovery,
}: {
  state: CircuitBreakerState;
  onOpenRecovery: () => void;
}) {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("ALL");
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = state.transactions.filter((txn) => {
      if (filter === "AUTOMATED_LOOP" && !isActiveRecovery(txn.state)) return false;
      if (filter !== "ALL" && filter !== "AUTOMATED_LOOP" && txn.state !== filter) return false;
      if (!q) return true;
      return (
        txn.transaction_id.toLowerCase().includes(q) ||
        txn.routing.bank.toLowerCase().includes(q) ||
        txn.customer.name.toLowerCase().includes(q) ||
        txn.routing.error_code.toLowerCase().includes(q)
      );
    });
    return [...filtered].sort((a, b) => STATE_SORT_ORDER[a.state] - STATE_SORT_ORDER[b.state]);
  }, [filter, query, state.transactions]);

  const selected = state.selected;

  useEffect(() => {
    if (state.selectedId) state.setAuditOpen(true);
  }, [state.selectedId, state.setAuditOpen]);

  return (
    <div className="space-y-6">
      <header>
        <p className="text-[13px] font-medium text-secondary">Ledger</p>
        <h1 className="mt-2 text-[32px] font-semibold tracking-tight text-navy">Transactions</h1>
        <p className="mt-2 text-[15px] text-secondary">
          History of intercepted failures. Open Recovery to act on a live payment.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-md border border-[rgba(15,40,50,0.10)] bg-white p-1">
          {FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setFilter(item.id)}
              className={cx(
                "rounded px-3 py-1.5 text-[13px]",
                filter === item.id ? "bg-[#EEF2FF] font-semibold text-blue" : "text-secondary",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search ID, bank, customer, error"
          className="focus-ring h-10 min-w-[220px] flex-1 rounded-md border border-[rgba(15,40,50,0.10)] bg-white px-3 text-[13px] text-ink outline-none"
        />
      </div>

      <LiveFailureStream
        transactions={rows}
        selectedId={state.selectedId}
        busy={state.busy}
        heading="All transactions"
        subheading="Select a row to see why the engine acted"
        onSelect={(id) => {
          state.setSelectedId(id);
          state.setAuditOpen(true);
        }}
      />

      {selected && (
        <section className="card p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="section-label">Selected payment</p>
              <p className="mt-2 font-mono text-[14px] font-semibold text-navy">{selected.transaction_id}</p>
              <p className="mt-1 text-[13px] text-secondary">
                {selected.customer.name} · {selected.routing.bank} · {formatINR(selected.order.amount)}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <StatusPill state={selected.state} />
              {isActiveRecovery(selected.state) && (
                <button
                  type="button"
                  onClick={onOpenRecovery}
                  className="focus-ring rounded-md bg-blue px-3 py-1.5 text-[12px] font-semibold text-white"
                >
                  Watch in Recovery
                </button>
              )}
            </div>
          </div>
          <p className="mt-4 text-[14px] leading-6 text-ink">
            {(selected.smart_routing?.reason || selected.routing.diagnosis || selected.routing.error_label).replace(
              /\s*\n\s*/g,
              " ",
            )}
          </p>
          {selected.state === "RECOVERED" && (
            <p className="mt-2 text-[14px] font-semibold text-success">
              Rescued {formatINR(selected.money_recovered || selected.order.amount)}
            </p>
          )}
        </section>
      )}

      {state.auditOpen && selected && (
        <AuditDrawer
          transaction={selected}
          events={state.auditEvents}
          loading={state.auditLoading}
          onClose={() => state.setAuditOpen(false)}
        />
      )}
    </div>
  );
}
