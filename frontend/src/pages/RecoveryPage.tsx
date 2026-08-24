import { useEffect, useState } from "react";
import { TransactionInspector } from "../components/TransactionInspector";
import { RecoveryFlow } from "../components/RecoveryFlow";
import { DecisionTimeline } from "../components/DecisionTimeline";
import { SimulationPanel } from "../components/SimulationPanel";
import { StatusPill } from "../components/StatusPill";
import type { CircuitBreakerState } from "../hooks/useCircuitBreaker";
import { formatINR } from "../lib/format";
import { useNow } from "../hooks/useAnimatedNumber";
import { isActiveRecovery } from "../types";
import { scenarioPayload, type DemoScenarioId } from "../lib/scenarios";

export function RecoveryPage({ state }: { state: CircuitBreakerState }) {
  const now = useNow(500);
  const [scenario, setScenario] = useState<DemoScenarioId>("GOLDEN_OUTAGE");
  const queue = state.transactions.filter(
    (txn) => isActiveRecovery(txn.state) || txn.transaction_id === state.selectedId,
  );
  const focused =
    state.selected ??
    state.heldCarts[0] ??
    state.transactions.find((txn) => isActiveRecovery(txn.state)) ??
    state.transactions[0] ??
    null;

  const focusedId = focused?.transaction_id;

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
      <header>
        <p className="text-[13px] font-medium text-secondary">Live recovery</p>
        <h1 className="mt-2 text-[32px] font-semibold tracking-tight text-navy">Recovery</h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-6 text-secondary">
          This is the demo: a payment fails, CircuitBreaker decides, and you see whether it was rescued.
        </p>
      </header>

      {state.error && (
        <div className="rounded-card border border-[rgba(229,72,77,0.3)] bg-white px-4 py-3 text-[13px] text-danger">
          {state.error}
        </div>
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

      <RecoveryFlow transaction={focused} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(280px,0.9fr)_minmax(0,1.4fr)]">
        <section className="card overflow-hidden">
          <header className="border-b border-[rgba(15,40,50,0.08)] px-5 py-4">
            <p className="section-label">In play</p>
            <p className="mt-2 tabular text-[28px] font-semibold text-navy">{state.heldCarts.length}</p>
          </header>
          {queue.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <p className="text-[15px] font-medium text-navy">Nothing to recover yet</p>
              <p className="mt-2 text-[13px] text-secondary">Simulate a failure above to start.</p>
            </div>
          ) : (
            <ul>
              {queue.slice(0, 8).map((txn) => {
                const left = Math.max(
                  0,
                  Math.ceil((new Date(txn.recovery.window_expires_at).getTime() - now) / 1000),
                );
                const selected = txn.transaction_id === focused?.transaction_id;
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
                        <p className="font-mono text-[12px] font-medium text-navy">{txn.transaction_id}</p>
                        <p className="mt-1 truncate text-[13px] text-secondary">
                          {txn.routing.bank} · {formatINR(txn.order.amount)}
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
