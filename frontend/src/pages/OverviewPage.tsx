import { MetricCards } from "../components/MetricCards";
import { BrandName, StatusPill } from "../components/StatusPill";
import type { CircuitBreakerState } from "../hooks/useCircuitBreaker";
import { formatINR } from "../lib/format";
import { isActiveRecovery } from "../types";
import { scenarioPayload } from "../lib/scenarios";

export function OverviewPage({
  state,
  onOpenRecovery,
  onOpenTransactions,
}: {
  state: CircuitBreakerState;
  onOpenRecovery: () => void;
  onOpenTransactions: () => void;
}) {
  const active = state.transactions.filter((txn) => isActiveRecovery(txn.state));
  const recent = state.transactions.slice(0, 5);
  const latestOutcome = state.transactions.find(
    (txn) => txn.state === "RECOVERED" || txn.state === "ESCALATED",
  );

  const startDemo = () => {
    onOpenRecovery();
    const payload = scenarioPayload("GOLDEN_OUTAGE");
    if (payload !== "batch") void state.simulate(payload, "scenario");
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <p className="text-[13px] font-medium text-secondary">AI Revenue Recovery</p>
          <h1 className="mt-2 text-[36px] font-semibold leading-[1.1] tracking-tight text-navy md:text-[44px]">
            <BrandName />
          </h1>
          <p className="mt-3 max-w-xl text-[16px] leading-7 text-secondary">
            Trigger a payment failure and watch the system save it.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={state.offline || state.busy !== null}
            onClick={startDemo}
            className="focus-ring rounded-md bg-blue px-4 py-2.5 text-[14px] font-semibold text-white hover:bg-[#2448d6] disabled:opacity-50"
          >
            {state.busy === "scenario" ? "Starting..." : "Simulate a failure"}
          </button>
          <button
            type="button"
            onClick={onOpenRecovery}
            className="focus-ring rounded-md border border-[rgba(15,40,50,0.12)] bg-white px-4 py-2.5 text-[14px] font-semibold text-navy"
          >
            Open recovery
          </button>
        </div>
      </header>

      {state.offline && (
        <div className="rounded-card border border-[rgba(229,72,77,0.3)] bg-white px-4 py-3 text-[13px] text-danger">
          Recovery engine unavailable. Unable to start simulation.
        </div>
      )}
      {state.error && (
        <div className="rounded-card border border-[rgba(229,72,77,0.3)] bg-white px-4 py-3 text-[13px] text-danger">
          {state.error}
        </div>
      )}

      <MetricCards telemetry={state.telemetry} loading={state.loading} />

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <article className="card p-5">
          <p className="section-label">Happening now</p>
          {active.length === 0 ? (
            <div className="mt-4">
              <p className="text-[16px] font-semibold text-navy">No payments in recovery</p>
              <p className="mt-2 text-[14px] leading-6 text-secondary">
                Simulate a bank-side failure to see CircuitBreaker retry, reroute, or escalate.
              </p>
            </div>
          ) : (
            <ul className="mt-4 space-y-3">
              {active.slice(0, 3).map((txn) => (
                <li key={txn.transaction_id}>
                  <button
                    type="button"
                    onClick={() => {
                      state.setSelectedId(txn.transaction_id);
                      onOpenRecovery();
                    }}
                    className="flex w-full items-center justify-between gap-3 rounded-md border border-[rgba(15,40,50,0.08)] px-3 py-3 text-left hover:bg-[#F8FAFC]"
                  >
                    <div className="min-w-0">
                      <p className="font-mono text-[12px] font-semibold text-navy">{txn.transaction_id}</p>
                      <p className="mt-1 truncate text-[13px] text-secondary">
                        {txn.routing.error_label || txn.routing.error_code} · {formatINR(txn.order.amount)}
                      </p>
                    </div>
                    <StatusPill state={txn.state} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </article>

        <article className="card p-5">
          <p className="section-label">Last outcome</p>
          {!latestOutcome ? (
            <p className="mt-4 text-[14px] leading-6 text-secondary">
              Rescue or escalation will appear here after the first recovery run.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <p className="font-mono text-[13px] font-semibold text-navy">{latestOutcome.transaction_id}</p>
                <StatusPill state={latestOutcome.state} />
              </div>
              <p className="text-[20px] font-semibold tracking-tight text-navy">
                {latestOutcome.state === "RECOVERED"
                  ? `${formatINR(latestOutcome.money_recovered || latestOutcome.order.amount)} recovered`
                  : "Sent to manual review"}
              </p>
              <p className="text-[13px] leading-5 text-secondary">
                {(latestOutcome.smart_routing?.reason ||
                  latestOutcome.routing.diagnosis ||
                  latestOutcome.routing.error_label).replace(/\s*\n\s*/g, " ")}
              </p>
            </div>
          )}
        </article>
      </section>

      {recent.length > 0 && (
        <section className="card overflow-hidden">
          <header className="flex items-center justify-between border-b border-[rgba(15,40,50,0.08)] px-5 py-4">
            <p className="section-label">Recent payments</p>
            <button
              type="button"
              onClick={onOpenRecovery}
              className="text-[12px] font-semibold text-blue"
            >
              Watch live recovery
            </button>
          </header>
          <ul>
            {recent.map((txn) => (
              <li key={txn.transaction_id}>
                <button
                  type="button"
                  onClick={() => {
                    state.setSelectedId(txn.transaction_id);
                    if (isActiveRecovery(txn.state)) onOpenRecovery();
                    else onOpenTransactions();
                  }}
                  className="flex w-full items-center justify-between gap-3 border-b border-[rgba(15,40,50,0.06)] px-5 py-3 text-left hover:bg-[#F8FAFC]"
                >
                  <span className="font-mono text-[12px] text-navy">{txn.transaction_id}</span>
                  <span className="hidden text-[13px] text-secondary sm:inline">
                    {txn.routing.bank} · {formatINR(txn.order.amount)}
                  </span>
                  <StatusPill state={txn.state} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
