import type { CircuitBreakerStatus, HealthResponse, TelemetryDashboard } from "../types";

function pill(ok: boolean, label: string, detail: string) {
  return (
    <article className="card p-4">
      <p className="section-label">{label}</p>
      <div className="mt-3 flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${ok ? "bg-success" : "bg-danger"}`} />
        <p className="text-[18px] font-semibold tracking-tight text-navy">{detail}</p>
      </div>
    </article>
  );
}

export function SystemHealth({
  health,
  telemetry,
  offline,
}: {
  health: HealthResponse | null;
  telemetry: TelemetryDashboard | null;
  offline: boolean;
}) {
  const engineOk = !offline && (health?.engine === "online" || telemetry?.engine_online !== false);
  const dbOk = health?.db_connected !== false && !offline;
  const railsOk = health?.rails_reachable !== false && !offline;
  const circuits = telemetry?.circuit_breakers ?? [];
  const open = circuits.filter((row: CircuitBreakerStatus) => row.state === "OPEN");
  const queue = telemetry?.recovery_queue_depth ?? health?.recovery_queue_depth ?? telemetry?.active_held_carts ?? 0;

  return (
    <section>
      <p className="section-label">System health</p>
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-5">
        {pill(engineOk, "Engine", engineOk ? "ONLINE" : "OFFLINE")}
        {pill(dbOk, "Database", dbOk ? "CONNECTED" : "UNAVAILABLE")}
        {pill(railsOk, "Rails", railsOk ? "REACHABLE" : "DEGRADED")}
        {pill(open.length === 0, "Circuits", open.length === 0 ? "CLOSED" : `${open.length} OPEN`)}
        {pill(true, "Recovery queue", String(queue))}
      </div>
    </section>
  );
}
