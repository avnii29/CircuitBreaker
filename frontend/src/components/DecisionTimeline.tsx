import type { AuditEvent, Transaction } from "../types";
import { formatINR } from "../lib/format";

function compactReasonLines(reason: string): string[] {
  const raw = reason
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const lines: string[] = [];
  for (let index = 0; index < raw.length; index += 1) {
    const line = raw[index];
    const next = raw[index + 1];
    if (line.endsWith(":") && next && !next.includes(":")) {
      lines.push(`${line} ${next}`);
      index += 1;
    } else {
      lines.push(line);
    }
  }
  return lines;
}

function splitField(line: string): { label: string; value: string } {
  const index = line.indexOf(":");
  if (index === -1) return { label: "", value: line };
  return { label: line.slice(0, index).trim(), value: line.slice(index + 1).trim() };
}

function stepsFrom(transaction: Transaction, events: AuditEvent[]): string[] {
  const decision = transaction.smart_routing?.last_decision;
  const reason = typeof decision?.reason === "string" ? decision.reason : "";
  if (reason.includes("Decision:")) {
    return compactReasonLines(reason);
  }
  const ordered = [...events].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );
  const lines: string[] = [
    `Payment: ${transaction.transaction_id}`,
    `Amount: ${formatINR(transaction.order.amount)}`,
    `State: ${transaction.state} · ${transaction.routing.error_code}`,
  ];
  for (const event of ordered) {
    if (event.action === "GUARDRAIL_VALIDATED") lines.push("Guardrails: PASSED");
    if (event.action === "GUARDRAIL_BLOCKED") {
      lines.push(`Guardrails: BLOCKED · ${String(event.metadata.reason ?? event.reason ?? "")}`.trim());
    }
    if (event.action === "RECOVERY_DECISION") {
      lines.push(
        `Decision: ${String(event.metadata.decision ?? "")} · ${String(event.metadata.policy_version ?? "")}`.trim(),
      );
    }
    if (event.action === "ROUTE_SELECTED") {
      lines.push(`Alternate rail: ${String(event.metadata.route ?? "")}`);
    }
    if (event.action === "PREDICTIVE_REROUTE") {
      lines.push(
        `Primary rail failure probability: ${Math.round(Number(event.metadata.predicted_failure_probability ?? 0) * 100)}%`,
      );
    }
    if (event.action === "RECOVERY_ROUTE_SUCCEEDED" || event.action === "PAYMENT_RECOVERED") {
      lines.push(`Outcome: RECOVERED · ${formatINR(transaction.money_recovered || transaction.order.amount)}`);
    }
  }
  return lines;
}

export function DecisionTimeline({
  transaction,
  events,
}: {
  transaction: Transaction;
  events: AuditEvent[];
}) {
  const lines = stepsFrom(transaction, events);
  return (
    <section className="card p-5">
      <p className="section-label">Why this happened</p>
      <p className="mt-1 text-[12px] text-secondary">The action CircuitBreaker chose, and why</p>
      <ul className="mt-4 space-y-2">
        {lines.map((line, index) => {
          const field = splitField(line);
          return (
            <li key={`${line}-${index}`} className="flex items-baseline gap-2 text-[13px] leading-5">
              {index < lines.length - 1 ? (
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-blue" />
              ) : (
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-success" />
              )}
              {field.label ? (
                <p className="min-w-0">
                  <span className="text-secondary">{field.label}: </span>
                  <span className="text-navy">{field.value || "-"}</span>
                </p>
              ) : (
                <span className="text-navy">{field.value}</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
