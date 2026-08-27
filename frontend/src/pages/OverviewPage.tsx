import { BrandName } from "../components/StatusPill";
import type { CircuitBreakerState } from "../hooks/useCircuitBreaker";
import { actionLabel, economicsOf, eventLabel, outcomeLabel } from "../lib/economics";
import { formatINR, formatLakhs } from "../lib/format";
import { isActiveRecovery } from "../types";

function toneForAction(action: string | undefined): string {
  if (action === "DO_NOTHING") return "text-secondary";
  if (action === "ESCALATE") return "text-warning";
  return "text-success";
}

export function OverviewPage({
  state,
  onOpenRecovery,
  onOpenTransactions,
}: {
  state: CircuitBreakerState;
  onOpenRecovery: () => void;
  onOpenTransactions: () => void;
}) {
  const tel = state.telemetry;
  const atRisk = tel?.revenue_leakage_total || tel?.revenue_at_risk || 0;
  const recovered = tel?.total_revenue_recovered || 0;
  const net = tel?.net_revenue_protected ?? Math.max(recovered - (tel?.intervention_cost_total || 0), 0);
  const rate = tel?.recovery_rate ?? 0;
  const activity = state.transactions.slice(0, 6);
  const leakage = tel?.leakage ?? [];
  const reconnecting = state.connection === "RECONNECTING" || state.connection === "DEGRADED";

  const startDemo = () => {
    onOpenRecovery();
    void state.startLiveDemo();
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
            Find revenue slipping away. Understand why. Choose the highest-value safe intervention. Measure what was actually recovered.
          </p>
        </div>
        <button
          type="button"
          disabled={state.connection === "UNAVAILABLE" || state.busy !== null}
          onClick={startDemo}
          className="focus-ring rounded-md bg-blue px-5 py-3 text-[15px] font-semibold text-white hover:bg-[#2448d6] disabled:opacity-50"
        >
          {state.busy === "live-demo" ? "Running live demo..." : "Start live demo"}
        </button>
      </header>

      {reconnecting && (
        <div className="flex items-center justify-between rounded-card border border-[rgba(15,40,50,0.08)] bg-white px-4 py-2.5 text-[13px] text-secondary">
          <span>Engine reconnecting. Showing last known totals.</span>
          <button type="button" onClick={() => void state.reconnect()} className="font-semibold text-navy">
            Retry
          </button>
        </div>
      )}
      {state.connection === "UNAVAILABLE" && (
        <div className="flex items-center justify-between rounded-card border border-[rgba(15,40,50,0.12)] bg-white px-4 py-2.5 text-[13px] text-secondary">
          <span>Engine unavailable. Navigation stays usable. Retry when ready.</span>
          <button type="button" onClick={() => void state.reconnect()} className="font-semibold text-navy">
            Retry
          </button>
        </div>
      )}
      {state.error && (
        <div className="rounded-card border border-[rgba(229,72,77,0.3)] bg-white px-4 py-3 text-[13px] text-danger">
          {state.error}
        </div>
      )}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Revenue at risk" value={formatLakhs(atRisk)} hint="From live revenue events" />
        <Metric label="Revenue recovered" value={formatLakhs(recovered)} hint="Actual simulated recoveries" />
        <Metric
          label="Net revenue protected"
          value={formatLakhs(net)}
          hint="Recovered minus simulated intervention cost"
          featured
        />
        <Metric label="Recovery rate" value={`${rate.toFixed(1)}%`} hint={`${tel?.intentionally_skipped ?? 0} intentionally skipped`} />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <article className="card p-5">
          <p className="section-label">Recovery agent activity</p>
          {activity.length === 0 ? (
            <p className="mt-4 text-[14px] leading-6 text-secondary">
              Start the live demo to analyze a batch of revenue events.
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {activity.map((txn) => {
                const econ = economicsOf(txn);
                return (
                  <li key={txn.transaction_id}>
                    <button
                      type="button"
                      onClick={() => {
                        state.setSelectedId(txn.transaction_id);
                        if (isActiveRecovery(txn.state) || txn.state === "RECOVERED") onOpenRecovery();
                        else onOpenTransactions();
                      }}
                      className="flex w-full items-start justify-between gap-3 rounded-md border border-[rgba(15,40,50,0.08)] px-3 py-3 text-left hover:bg-[#F8FAFC]"
                    >
                      <div className="min-w-0">
                        <p className="tabular text-[16px] font-semibold text-navy">{formatINR(txn.order.amount)}</p>
                        <p className="mt-1 truncate text-[13px] text-secondary">
                          {eventLabel(econ?.event_type)} · {econ?.selected_intervention?.replace(/_/g, " ") || txn.routing.error_label}
                        </p>
                      </div>
                      <p className={`shrink-0 text-[12px] font-semibold ${toneForAction(econ?.selected_action)}`}>
                        {actionLabel(econ?.selected_action)} → {outcomeLabel(txn)}
                      </p>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </article>

        <div className="space-y-4">
          <article className="card p-5">
            <p className="section-label">Agent decisions</p>
            <div className="mt-4 grid grid-cols-3 gap-3 text-center">
              <Count label="ACT" value={tel?.agent_act ?? 0} />
              <Count label="DO NOTHING" value={tel?.agent_do_nothing ?? 0} />
              <Count label="ESCALATE" value={tel?.agent_escalate ?? 0} />
            </div>
          </article>
          <article className="card p-5">
            <p className="section-label">Revenue leakage</p>
            <ul className="mt-3 space-y-2 text-[13px]">
              {(leakage.length ? leakage : [
                { event_type: "PAYMENT_FAILURE", count: 0, amount: 0, recovered: 0 },
                { event_type: "CHECKOUT_ABANDONMENT", count: 0, amount: 0, recovered: 0 },
                { event_type: "SUBSCRIPTION_FAILURE", count: 0, amount: 0, recovered: 0 },
                { event_type: "OVERDUE_RECEIVABLE", count: 0, amount: 0, recovered: 0 },
              ]).map((row) => (
                <li key={row.event_type} className="flex items-center justify-between gap-3">
                  <span className="text-secondary">{eventLabel(row.event_type)}</span>
                  <span className="tabular font-medium text-navy">{formatINR(row.amount)}</span>
                </li>
              ))}
            </ul>
          </article>
        </div>
      </section>

      {tel?.last_batch && (
        <section className="card p-5">
          <p className="section-label">Simulated baseline</p>
          <p className="mt-1 text-[12px] text-secondary">SIMULATED BASELINE vs SIMULATED INTERVENTION. Not a real-world causal measurement.</p>
          <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
            <Metric label="Without CircuitBreaker" value={formatLakhs(tel.last_batch.baseline_recovered || tel.baseline_recovered || 0)} hint={`Natural recovery ${(18).toFixed(0)}% assumed`} />
            <Metric label="With CircuitBreaker" value={formatLakhs(tel.last_batch.revenue_recovered)} hint="Actual recovered in this batch" />
            <Metric label="Incremental value" value={formatLakhs(tel.last_batch.incremental_value_protected || tel.incremental_value_protected || 0)} hint="Simulated value protected" />
            <Metric label="Intervention cost" value={formatINR(tel.last_batch.intervention_cost || tel.intervention_cost_total || 0)} hint="Simulated costs only" />
          </div>
        </section>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  featured,
}: {
  label: string;
  value: string;
  hint: string;
  featured?: boolean;
}) {
  return (
    <article className={`card p-5 ${featured ? "border-blue/20 bg-[#F5F8FF]" : ""}`}>
      <p className="section-label">{label}</p>
      <p className="mt-3 tabular text-[28px] font-semibold leading-none tracking-tight text-navy">{value}</p>
      <p className="mt-3 text-[13px] leading-5 text-secondary">{hint}</p>
    </article>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="tabular text-[24px] font-semibold text-navy">{value}</p>
      <p className="mt-1 text-[11px] font-semibold tracking-wide text-secondary">{label}</p>
    </div>
  );
}
