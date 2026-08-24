import type { AuditEvent } from "../types";
import { formatTime } from "../lib/format";

function description(event: AuditEvent): string {
  if (event.reason && event.reason !== event.action) return event.reason;
  const meta = event.metadata;
  switch (event.action) {
    case "PAYMENT_INITIATED":
      return `${meta.display ?? `₹${Number(meta.amount ?? 0).toLocaleString("en-IN")}`} payment request created.`;
    case "BANK_FAILURE_DETECTED":
      return String(meta.error_code ?? "Bank-side technical failure");
    case "FAILURE_INTERCEPTED":
      return "Failure intercepted. Transaction is eligible for recovery.";
    case "CART_HELD":
      return "Inventory reservation created. Cart status: HELD.";
    case "AUTOMATED_RECOVERY_STARTED":
      return "Transaction entered automated recovery loop.";
    case "RECOVERY_ENGINE_STARTED":
      return "Transaction entered automated recovery loop.";
    case "RECOVERY_MESSAGE_GENERATED":
      return "Hinglish recovery message prepared.";
    case "AI_MESSAGE_GENERATED":
      return "Hinglish recovery message prepared.";
    case "GUARDRAIL_VALIDATED":
      return `AI output validation ${String(meta.guardrail_status ?? "PASSED")}.`;
    case "GUARDRAIL_BLOCKED":
      return String(meta.reason ?? meta.blocked_reason ?? "Guardrail blocked automated recovery.");
    case "RECOVERY_LINK_GENERATED":
      return "Alternate UPI fallback route created.";
    case "RECOVERY_ATTEMPT_STARTED":
      return "Recovery attempt started after guardrail validation.";
    case "RECOVERY_ATTEMPTED":
      return "Waiting for payment confirmation.";
    case "PAYMENT_RECOVERED":
      return `${String(meta.display ?? `₹${Number(meta.amount ?? 0).toLocaleString("en-IN")}`)} successfully recovered.`;
    case "RECOVERY_WINDOW_EXPIRED":
      return "Recovery window expired.";
    case "STOPPING_RULE_TRIGGERED":
      return "Recovery window expired.";
    case "ESCALATION_TRIGGERED":
      return "Stopping rule triggered. Human review required.";
    case "FAILURE_CLASSIFIED":
      return String(meta.category ?? "Failure classified.");
    case "ROUTES_EVALUATED":
      return `${String(meta.count ?? "")} recovery routes scored.`.trim();
    case "ROUTE_SELECTED":
      return `${String(meta.route ?? "Route")} selected.`;
    case "RECOVERY_ROUTE_EXECUTED":
      return `Simulated ${String(meta.route ?? "route")} execution started.`;
    case "RECOVERY_ROUTE_SUCCEEDED":
      return `${String(meta.route ?? "Route")} succeeded.`;
    case "RECOVERY_ROUTE_FAILED":
      return `${String(meta.route ?? "Route")} failed. Fallback evaluation started.`;
    case "ROUTING_ATTEMPTS_EXHAUSTED":
      return "Maximum recovery attempts reached.";
    case "RECOVERY_DECISION":
      return String(event.reason ?? meta.reason ?? "Canonical recovery decision recorded.");
    case "PREDICTIVE_REROUTE":
      return String(meta.reason ?? "Predicted primary-rail failure; alternate selected.");
    case "POLICY_BLOCKED":
      return String(meta.reason ?? "Automated recovery policy blocked this transaction.");
    case "CART_RELEASED":
      return "Held cart released.";
    case "HELD_CART_RELEASED":
      return "Held cart released.";
    default:
      return event.actor;
  }
}

export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  const chronological = [...events].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );

  return (
    <ol className="space-y-4">
      {chronological.map((event, index) => (
        <li key={`${event.action}-${event.timestamp}-${index}`} className="grid grid-cols-[72px_1fr] gap-4">
          <p className="tabular pt-0.5 text-[12px] text-muted">{formatTime(event.timestamp)}</p>
          <div>
            <p className="font-mono text-[12px] font-medium tracking-wide text-navy">
              {event.action}
            </p>
            {(event.previous_state || event.new_state) && (
              <p className="mt-0.5 text-[11px] font-semibold tracking-wide text-secondary">
                {event.previous_state ?? "-"} → {event.new_state ?? "-"}
              </p>
            )}
            <p className="mt-1 text-[13px] leading-5 text-secondary">{description(event)}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
