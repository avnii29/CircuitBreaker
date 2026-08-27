import { PlayIcon } from "./StatusPill";
import { cx, formatTime } from "../lib/format";
import { DEMO_SCENARIOS, type DemoScenarioId } from "../lib/scenarios";
import type { RoutePerformance, RoutingEvent, RoutingSummary } from "../types";

export type { DemoScenarioId };

export function SimulationPanel({
  busy,
  confirmReset,
  scenario,
  onScenario,
  onRunScenario,
  onBatch,
  onDemoRecovery,
  onAskReset,
  onCancelReset,
  onConfirmReset,
}: {
  busy: string | null;
  confirmReset: boolean;
  scenario: DemoScenarioId;
  onScenario: (id: DemoScenarioId) => void;
  onRunScenario: () => void;
  onBatch: () => void;
  onDemoRecovery: () => void;
  onAskReset: () => void;
  onCancelReset: () => void;
  onConfirmReset: () => void;
}) {
  const disabled = busy !== null;
  const running =
    busy === "scenario" || busy === "hdfc" || busy === "sbi" || busy === "random" || busy === "simulate";

  return (
    <section className="overflow-hidden rounded-card bg-surface p-5 text-white md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <p className="section-label !text-[#98A2B3]">Live demo</p>
          <span className="inline-flex items-center gap-1.5 rounded-md bg-white/10 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-success">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            SIMULATED
          </span>
          </div>
          <h2 className="mt-2 text-[22px] font-semibold tracking-tight">
            Run a revenue event. Watch the agent decide.
          </h2>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-end gap-3">
        <label className="text-[12px] text-[#98A2B3]">
          Revenue event
          <select
            value={scenario}
            onChange={(event) => onScenario(event.target.value as DemoScenarioId)}
            className="mt-1 block h-10 min-w-[240px] rounded-md border border-white/20 bg-[#0E3A4A] px-3 text-[13px] text-white"
          >
            {DEMO_SCENARIOS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={disabled}
          onClick={onRunScenario}
          className="focus-ring inline-flex h-10 items-center gap-2 rounded-md bg-blue px-4 text-[14px] font-semibold text-white hover:bg-[#2448d6] disabled:opacity-50"
        >
          <PlayIcon />
          {running ? "Simulating..." : "Run event"}
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onDemoRecovery}
          className="focus-ring h-10 rounded-md border border-success/40 bg-success/10 px-4 text-[13px] font-semibold text-success hover:bg-success/15 disabled:opacity-50"
        >
          {busy === "demo-recovery" ? "Running recovery..." : "Auto-recover"}
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onBatch}
          className="focus-ring h-10 rounded-md border border-white/25 bg-transparent px-4 text-[13px] font-semibold text-white hover:bg-white/5 disabled:opacity-50"
        >
          {busy === "batch" || busy === "live-demo" ? "Simulating..." : "Run batch"}
        </button>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[12px] text-[#98A2B3]">Simulated interventions only. No real money movement.</p>
        {!confirmReset ? (
          <button
            type="button"
            disabled={disabled}
            onClick={onAskReset}
            className="text-[12px] font-medium text-[#98A2B3] underline-offset-2 hover:text-white hover:underline disabled:opacity-50"
          >
            Reset demo
          </button>
        ) : (
          <div className="flex items-center gap-2 text-[12px]">
            <span className="text-white">Reset all demo transactions?</span>
            <button type="button" onClick={onCancelReset} className="rounded-md px-2 py-1 text-[#98A2B3]">
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirmReset}
              className="rounded-md bg-white px-2 py-1 font-semibold text-navy"
            >
              Reset demo
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

export function BatchPanel({
  batch,
}: {
  batch: {
    batch_id: string;
    batch_size: number;
    failures_intercepted: number;
    recovery_attempts: number;
    recovered: number;
    escalated: number;
    in_progress: number;
    recovery_rate: number;
    revenue_recovered: number;
    revenue_at_risk: number;
    complete: boolean;
    routing_summary?: RoutingSummary | null;
  };
}) {
  const cells = [
    ["Batch size", String(batch.batch_size)],
    ["Failures intercepted", String(batch.failures_intercepted)],
    ["Recovery attempts", String(batch.recovery_attempts)],
    ["Recovered", String(batch.recovered)],
    ["Escalated", String(batch.escalated)],
    ["In progress", String(batch.in_progress)],
    ["Recovery rate", `${batch.recovery_rate.toFixed(1)}%`],
    ["Revenue recovered", `₹${batch.revenue_recovered.toLocaleString("en-IN")}`],
    ["Revenue at risk", `₹${batch.revenue_at_risk.toLocaleString("en-IN")}`],
  ];

  return (
    <section className="card fade-in p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="section-label">Batch run</p>
          <p className="mt-2 font-mono text-[13px] text-navy">{batch.batch_id}</p>
        </div>
        <span
          className={cx(
            "rounded-md px-2 py-1 text-[11px] font-semibold tracking-wide",
            batch.complete ? "bg-[#E6F8F0] text-success" : "bg-[#FFF6E5] text-warning",
          )}
        >
          {batch.complete ? "COMPLETE" : "RUNNING"}
        </span>
      </div>
      <div className="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-3">
        {cells.map(([label, value]) => (
          <div key={label}>
            <p className="text-[12px] text-secondary">{label}</p>
            <p className="mt-1 tabular text-[18px] font-semibold text-navy">{value}</p>
          </div>
        ))}
      </div>
      {batch.routing_summary && <RoutingSummaryPanel summary={batch.routing_summary} />}
    </section>
  );
}

export function RoutingSummaryPanel({ summary }: { summary: RoutingSummary }) {
  const cells = [
    ["Transactions evaluated", String(summary.transactions_evaluated)],
    ["Routes evaluated", String(summary.routes_evaluated)],
    ["Recovered", String(summary.recovered)],
    ["Escalated", String(summary.escalated)],
    ["First-route recovery", String(summary.first_route_recovery)],
    ["Fallback recovery", String(summary.fallback_recovery)],
    ["Average attempts", summary.average_attempts.toFixed(1)],
    ["Revenue recovered", `₹${summary.revenue_recovered.toLocaleString("en-IN")}`],
    ["Revenue at risk", `₹${summary.revenue_at_risk.toLocaleString("en-IN")}`],
    ["Most effective route", summary.most_effective_route?.replace(/_/g, " ") || "-"],
  ];
  return (
    <div className="mt-6 border-t border-[rgba(15,40,50,0.08)] pt-5">
      <p className="section-label">Smart Routing Summary</p>
      <p className="mt-1 text-[11px] font-semibold tracking-[0.12em] text-muted">CALCULATED · SIMULATED</p>
      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-5">
        {cells.map(([label, value]) => (
          <div key={label}>
            <p className="text-[12px] text-secondary">{label}</p>
            <p className="mt-1 tabular text-[16px] font-semibold text-navy">{value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RoutingPerformancePanel({ routes }: { routes: RoutePerformance[] }) {
  return (
    <section className="card p-6">
      <p className="section-label">Smart Routing Performance</p>
      <p className="mt-2 text-[13px] text-secondary">Simulated recovery route outcomes</p>
      <p className="mt-1 text-[11px] font-semibold tracking-[0.12em] text-muted">SIMULATED ROUTE PERFORMANCE</p>
      <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {routes.map((route) => (
          <article key={route.route_id} className="rounded-card border border-[rgba(15,40,50,0.08)] px-4 py-3">
            <p className="text-[13px] font-semibold text-navy">{route.display_name}</p>
            <dl className="mt-3 grid grid-cols-3 gap-2 text-[12px]">
              <div>
                <dt className="text-secondary">Attempts</dt>
                <dd className="mt-1 tabular font-semibold text-navy">{route.attempts}</dd>
              </div>
              <div>
                <dt className="text-secondary">Successes</dt>
                <dd className="mt-1 tabular font-semibold text-navy">{route.successful}</dd>
              </div>
              <div>
                <dt className="text-secondary">Success rate</dt>
                <dd className="mt-1 tabular font-semibold text-navy">{route.success_rate.toFixed(1)}%</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

export function RoutingEventsFeed({ events }: { events: RoutingEvent[] }) {
  return (
    <section className="card overflow-hidden">
      <header className="border-b border-[rgba(15,40,50,0.08)] px-6 py-5">
        <p className="section-label">Smart Routing Events</p>
        <p className="mt-1 text-[12px] text-secondary">Live decisions from the recovery engine</p>
      </header>
      {events.length === 0 ? (
        <p className="px-6 py-8 text-[13px] text-secondary">No routing events yet.</p>
      ) : (
        <ul className="divide-y divide-[rgba(15,40,50,0.06)]">
          {events.slice(0, 8).map((event, index) => (
            <li key={`${event.timestamp}-${event.transaction_id}-${index}`} className="grid grid-cols-[72px_1fr] gap-4 px-6 py-3">
              <p className="tabular text-[12px] text-muted">{formatTime(event.timestamp)}</p>
              <div>
                <p className="font-mono text-[12px] font-medium text-navy">{event.transaction_id}</p>
                <p className="mt-0.5 text-[13px] text-secondary">{event.message}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
