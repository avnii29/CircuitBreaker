import { BrandName } from "../components/StatusPill";
import { BatchPanel, RoutingPerformancePanel, RoutingSummaryPanel } from "../components/SimulationPanel";
import type { CircuitBreakerState } from "../hooks/useCircuitBreaker";
import { formatDuration, formatINR, formatTime } from "../lib/format";

export function TelemetryPage({ state }: { state: CircuitBreakerState }) {
  const t = state.telemetry;
  const snapshot = {
    engine: state.offline ? "offline" : "online",
    demo_mode: t?.demo_mode ?? true,
    recovery_window_seconds: t?.recovery_window_seconds ?? 30,
    total_failures_intercepted: t?.total_failures_intercepted ?? 0,
    total_transactions_rescued: t?.total_transactions_rescued ?? 0,
    total_escalated: t?.total_escalated ?? 0,
    recovery_rate: t?.recovery_rate ?? 0,
    revenue_recovered: t?.revenue_recovered ?? 0,
    revenue_at_risk: t?.revenue_at_risk ?? 0,
    active_held_carts: t?.active_held_carts ?? 0,
    average_recovery_time_seconds: t?.average_recovery_time_seconds,
    llm: "AI SIMULATION",
    routing: t?.routing ?? {
      total_route_decisions: 0,
      successful_route_executions: 0,
      failed_route_executions: 0,
      average_route_score: 0,
      most_selected_route: null,
    },
    intelligence: t?.intelligence ?? null,
  };

  const stats = [
    ["Failures intercepted", String(snapshot.total_failures_intercepted)],
    ["Rescued", String(snapshot.total_transactions_rescued)],
    ["Escalated", String(snapshot.total_escalated)],
    ["Held carts", String(snapshot.active_held_carts)],
    ["Recovery rate", `${snapshot.recovery_rate.toFixed(1)}%`],
    ["Avg recovery time", formatDuration(snapshot.average_recovery_time_seconds ?? null)],
    ["Revenue recovered", formatINR(snapshot.revenue_recovered)],
    ["Revenue at risk", formatINR(snapshot.revenue_at_risk)],
  ];

  return (
    <div className="space-y-8">
      <section className="overflow-hidden rounded-card bg-surface px-6 py-10 text-white md:px-10 md:py-12">
        <p className="text-[13px] text-[#98A2B3]">Infrastructure telemetry</p>
        <h1 className="mt-4 max-w-3xl text-[36px] font-semibold leading-tight tracking-tight md:text-[44px]">
          <BrandName className="text-white" /> records{" "}
          <span className="text-success">&lt;every recovery decision&gt;</span>
        </h1>
        <p className="mt-4 max-w-xl text-[15px] leading-6 text-[#98A2B3]">
          The AI drafts language. Deterministic guardrails decide whether money can move.
          Stopping rules close the window without operator guesswork.
        </p>
        <div className="mt-10 grid gap-8 md:grid-cols-3">
          <Feature title="Guardrails" body="Amount, transaction ID, link, window, and attempt limits are checked before execution." />
          <Feature title="Audit trail" body="Every state change is appended with actor, previous state, and metadata." />
          <Feature title="Stopping rule" body="If the window expires, automation stops and the held cart is released." />
        </div>
      </section>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {stats.map(([label, value]) => (
          <article key={label} className="card p-5">
            <p className="text-[12px] text-secondary">{label}</p>
            <p className="mt-2 tabular text-[22px] font-semibold text-navy">{value}</p>
          </article>
        ))}
      </section>

      {state.routing && <RoutingPerformancePanel routes={state.routing.routes} />}
      {state.routing?.last_summary && (
        <section className="card p-6">
          <RoutingSummaryPanel summary={state.routing.last_summary} />
        </section>
      )}

      {state.lastBatch && <BatchPanel batch={state.lastBatch} />}

      <section className="overflow-hidden rounded-card bg-navy">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <p className="text-[12px] font-medium text-white">telemetry.json</p>
          <p className="text-[12px] text-[#98A2B3]">
            {state.health ? formatTime(state.health.heartbeat) : "awaiting heartbeat"}
          </p>
        </div>
        <pre className="overflow-x-auto px-5 py-4 font-mono text-[12px] leading-6 text-[#D0D5DD]">
          {JSON.stringify(snapshot, null, 2)}
        </pre>
      </section>
    </div>
  );
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <p className="text-[15px] font-semibold text-white">{title}</p>
      <p className="mt-2 text-[13px] leading-6 text-[#98A2B3]">{body}</p>
      <p className="mt-3 text-[13px] text-white">View model →</p>
    </div>
  );
}
