import type { TelemetryDashboard } from "../types";
import { formatINR } from "../lib/format";
import { useAnimatedNumber } from "../hooks/useAnimatedNumber";

function MetricCard({
  label,
  value,
  hint,
  display,
  accent,
}: {
  label: string;
  value: number;
  hint: string;
  display: string;
  accent?: string;
}) {
  const animated = useAnimatedNumber(value);
  const shown = display.includes("₹")
    ? formatINR(animated)
    : display.includes("%")
      ? `${animated.toFixed(1)}%`
      : String(animated);

  return (
    <article className="card fade-in p-5">
      <p className="section-label">{label}</p>
      <div className="mt-3 flex items-end justify-between gap-3">
        <p className="tabular text-[28px] font-semibold leading-none tracking-tight text-navy">
          {shown}
        </p>
        {accent && <p className="text-[13px] font-medium text-success">{accent}</p>}
      </div>
      <p className="mt-3 text-[13px] leading-5 text-secondary">{hint}</p>
    </article>
  );
}

export function MetricCards({
  telemetry,
  loading,
}: {
  telemetry: TelemetryDashboard | null;
  loading: boolean;
}) {
  if (loading && !telemetry) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="card h-[132px] p-6">
            <div className="skeleton h-3 w-32 rounded" />
            <div className="skeleton mt-4 h-8 w-20 rounded" />
            <div className="skeleton mt-4 h-3 w-40 rounded" />
          </div>
        ))}
      </div>
    );
  }

  const data = telemetry;
  const recovered = data?.total_transactions_rescued ?? 0;
  const rate = data?.recovery_rate ?? 0;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        label="Payments rescued"
        value={recovered}
        hint="Failed checkouts CircuitBreaker saved"
        display="0"
      />
      <MetricCard
        label="Revenue recovered"
        value={data?.total_revenue_recovered ?? 0}
        hint="Money kept after a bank-side failure"
        display="₹0"
      />
      <MetricCard
        label="Still at risk"
        value={data?.revenue_at_risk ?? 0}
        hint="Orders in an open recovery window"
        display="₹0"
      />
      <MetricCard
        label="Rescue rate"
        value={rate}
        hint={`${data?.total_escalated ?? 0} sent to review`}
        display="0.0%"
      />
    </div>
  );
}
