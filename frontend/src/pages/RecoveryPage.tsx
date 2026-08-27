import { useEffect, useMemo, useState } from "react";
import { TransactionInspector } from "../components/TransactionInspector";
import { DecisionTimeline } from "../components/DecisionTimeline";
import { SimulationPanel } from "../components/SimulationPanel";
import { StatusPill } from "../components/StatusPill";
import type { CircuitBreakerState } from "../hooks/useCircuitBreaker";
import { actionLabel, economicsOf, eventLabel, priorityScore } from "../lib/economics";
import { formatINR, formatLakhs } from "../lib/format";
import { useNow } from "../hooks/useAnimatedNumber";
import { isActiveRecovery } from "../types";
import { scenarioPayload, type DemoScenarioId } from "../lib/scenarios";

export function RecoveryPage({ state }: { state: CircuitBreakerState }) {
  const now = useNow(500);
  const [scenario, setScenario] = useState<DemoScenarioId>("GOLDEN_OUTAGE");
  const queue = useMemo(() => {
    const rows = state.transactions.filter(
      (txn) =>
        isActiveRecovery(txn.state) ||
        txn.transaction_id === state.selectedId ||
        txn.state === "RECOVERED" ||
        txn.state === "ESCALATED",
    );
    const ranked = rows.length > 0 ? rows : state.transactions;
    return [...ranked].sort((a, b) => priorityScore(b) - priorityScore(a)).slice(0, 10);
  }, [state.transactions, state.selectedId]);
  const focused =
    state.selected ??
    state.heldCarts[0] ??
    state.transactions.find((txn) => isActiveRecovery(txn.state)) ??
    state.transactions[0] ??
    null;

  const focusedId = focused?.transaction_id;
  const batch = state.lastBatch;

  useEffect(() => {
    if (!state.selectedId && focusedId) {
      state.setSelectedId(focusedId);
    }
  }, [focusedId, state.selectedId, state.setSelectedId]);

  const runScenario = () => {
    const payload = scenarioPayload(scenario);
    if (payload === "batch") {
      void state.simulateBatch();
      return;
    }
    void state.simulate(payload, "scenario");
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[13px] font-medium text-secondary">Live recovery</p>
          <h1 className="mt-2 text-[32px] font-semibold tracking-tight text-navy">Decision theater</h1>
          <p className="mt-2 max-w-2xl text-[15px] leading-6 text-secondary">
            Money at risk, options considered, why the agent acted or skipped, and what was recovered.
          </p>
        </div>
        <button
          type="button"
          disabled={state.connection === "UNAVAILABLE" || state.busy !== null}
          onClick={() => void state.startLiveDemo()}
          className="focus-ring rounded-md bg-blue px-4 py-2.5 text-[14px] font-semibold text-white hover:bg-[#2448d6] disabled:opacity-50"
        >
          {state.busy === "live-demo" ? "Running live demo..." : "Start live demo"}
        </button>
      </header>

      {state.error && (
        <div className="rounded-card border border-[rgba(229,72,77,0.3)] bg-white px-4 py-3 text-[13px] text-danger">
          {state.error}
        </div>
      )}

      {batch && (
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <Mini label="At risk" value={formatLakhs(batch.revenue_leakage_total || batch.revenue_at_risk)} />
          <Mini label="Recovered" value={formatLakhs(batch.revenue_recovered)} />
          <Mini label="Net protected" value={formatLakhs(batch.net_revenue_protected || 0)} />
          <Mini label="ACT" value={String(batch.agent_act ?? 0)} />
          <Mini label="DO NOTHING" value={String(batch.agent_do_nothing ?? batch.intentionally_skipped ?? 0)} />
          <Mini label="ESCALATE" value={String(batch.agent_escalate ?? batch.escalated)} />
        </section>
      )}

      <SimulationPanel
        busy={state.busy}
        confirmReset={state.confirmReset}
        scenario={scenario}
        onScenario={setScenario}
        onRunScenario={runScenario}
        onBatch={() => void state.simulateBatch()}
        onDemoRecovery={() => void state.runRecoverySimulation()}
        onAskReset={() => state.setConfirmReset(true)}
        onCancelReset={() => state.setConfirmReset(false)}
        onConfirmReset={() => void state.resetDemo()}
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(280px,0.9fr)_minmax(0,1.4fr)]">
        <section className="card overflow-hidden">
          <header className="border-b border-[rgba(15,40,50,0.08)] px-5 py-4">
            <p className="section-label">Priority queue</p>
            <p className="mt-2 text-[13px] text-secondary">Highest economic urgency first</p>
          </header>
          {queue.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <p className="text-[15px] font-medium text-navy">Nothing to recover yet</p>
              <p className="mt-2 text-[13px] text-secondary">Start the live demo or run a single event.</p>
            </div>
          ) : (
            <ul>
              {queue.map((txn) => {
                const left = Math.max(
                  0,
                  Math.ceil((new Date(txn.recovery.window_expires_at).getTime() - now) / 1000),
                );
                const selected = txn.transaction_id === focused?.transaction_id;
                const econ = economicsOf(txn);
                return (
                  <li key={txn.transaction_id}>
                    <button
                      type="button"
                      onClick={() => state.setSelectedId(txn.transaction_id)}
                      className={`flex w-full items-center justify-between gap-3 border-b border-[rgba(15,40,50,0.06)] px-5 py-3.5 text-left hover:bg-[#F8FAFC] ${
                        selected ? "bg-[#F5F8FF]" : ""
                      }`}
                    >
                      <div className="min-w-0">
                        <p className="tabular text-[15px] font-semibold text-navy">{formatINR(txn.order.amount)}</p>
                        <p className="mt-1 truncate text-[12px] text-secondary">
                          {eventLabel(econ?.event_type)} · {actionLabel(econ?.selected_action)}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        {isActiveRecovery(txn.state) && (
                          <span className="tabular text-[13px] font-medium text-warning">{left}s</span>
                        )}
                        <StatusPill state={txn.state} />
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <div className="space-y-4">
          <TransactionInspector
            transaction={focused}
            busy={state.busy}
            notice={state.notice}
            executeResult={state.executeResult}
            onRecover={(id) => void state.executeRecovery(id)}
            onSelectRoute={(id) => void state.selectRoute(id)}
            onExecuteRoute={(id) => void state.executeSelectedRoute(id)}
          />
          {focused && <DecisionTimeline transaction={focused} events={state.auditEvents} />}
        </div>
      </div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <article className="card px-4 py-3">
      <p className="section-label">{label}</p>
      <p className="mt-2 tabular text-[18px] font-semibold text-navy">{value}</p>
    </article>
  );
}
