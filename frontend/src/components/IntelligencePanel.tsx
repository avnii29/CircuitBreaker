import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PolicyView, TelemetryDashboard } from "../types";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <article className="card p-4">
      <p className="section-label">{label}</p>
      <p className="mt-2 tabular text-[22px] font-semibold text-navy">{value}</p>
    </article>
  );
}

export function IntelligencePanel({ telemetry }: { telemetry: TelemetryDashboard | null }) {
  const [policy, setPolicy] = useState<PolicyView | null>(null);

  useEffect(() => {
    void api
      .policy()
      .then(setPolicy)
      .catch(() => setPolicy(null));
  }, [telemetry?.intelligence?.active_policy_version, telemetry?.last_heartbeat]);

  const intel = telemetry?.intelligence;
  const scores = [...(policy?.route_scores ?? [])].sort((a, b) => b.success_rate - a.success_rate);
  const best = intel?.best_route || scores[0]?.rail || "-";
  const version = intel?.active_policy_version || (policy ? `policy-v${policy.thresholds.version}` : "-");
  const predicted =
    intel?.predicted_failure_probability != null
      ? `${Math.round(intel.predicted_failure_probability * 100)}%`
      : "-";

  return (
    <section className="space-y-4">
      <div>
        <p className="section-label">Intelligence performance</p>
        <p className="mt-1 text-[13px] text-secondary">
          Evidence that routing scores, predictive reroutes, and policy thresholds actually move.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Active policy" value={String(version)} />
        <Stat label="Best route" value={best} />
        <Stat label="Predicted failure" value={predicted} />
        <Stat label="Adaptive adjustments" value={String(intel?.policy_adjustments ?? 0)} />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Primary success" value={`${(intel?.primary_success_rate ?? 0).toFixed(1)}%`} />
        <Stat label="Reroute success" value={`${(intel?.reroute_success_rate ?? 0).toFixed(1)}%`} />
        <Stat label="Predictive routing" value={`${(intel?.predictive_routing_rate ?? 0).toFixed(1)}%`} />
        <Stat label="Fail-then-reroute" value={`${(intel?.fail_then_reroute_rate ?? 0).toFixed(1)}%`} />
      </div>
      {scores.length > 0 && (
        <section className="card overflow-hidden">
          <header className="border-b border-[rgba(15,40,50,0.08)] px-5 py-4">
            <p className="section-label">Rail success scores</p>
          </header>
          <ul>
            {scores.slice(0, 8).map((row) => (
              <li
                key={`${row.error_code}:${row.rail}`}
                className="flex items-center justify-between border-b border-[rgba(15,40,50,0.06)] px-5 py-3 last:border-b-0"
              >
                <p className="text-[13px] text-navy">
                  {row.rail} <span className="text-muted">· {row.error_code}</span>
                </p>
                <p className="tabular text-[13px] font-semibold text-navy">
                  {Math.round(row.success_rate * 100)}%
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}
