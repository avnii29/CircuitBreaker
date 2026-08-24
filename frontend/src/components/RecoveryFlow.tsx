import type { Transaction, TransactionState } from "../types";
import { cx } from "../lib/format";

const NODES: { id: string; label: string; match: TransactionState[] }[] = [
  { id: "INITIATED", label: "INITIATED", match: ["INITIATED"] },
  { id: "FAILED", label: "FAILED", match: ["FAILED"] },
  { id: "AUTOMATED_LOOP", label: "AUTOMATED LOOP", match: ["AUTOMATED_LOOP"] },
  { id: "PHASE", label: "RETRYING / REROUTING", match: ["RETRYING", "REROUTING"] },
  { id: "TERMINAL", label: "RECOVERED / ESCALATED", match: ["RECOVERED", "ESCALATED"] },
];

function tone(state: TransactionState | undefined, active: boolean): string {
  if (!active || !state) return "border-[#D0D5DD] bg-white text-muted";
  if (state === "FAILED" || state === "ESCALATED") return "border-danger bg-[#FDECEC] text-danger";
  if (state === "RECOVERED") return "border-success bg-[#E6F8F0] text-success";
  if (state === "RETRYING" || state === "REROUTING" || state === "AUTOMATED_LOOP") {
    return "border-warning bg-[#FFF6E5] text-warning";
  }
  return "border-blue bg-[#EEF2FF] text-blue";
}

function passed(state: TransactionState | undefined, nodeId: string): boolean {
  if (!state) return false;
  const order = ["INITIATED", "FAILED", "AUTOMATED_LOOP", "PHASE", "TERMINAL"];
  const current =
    state === "RETRYING" || state === "REROUTING"
      ? "PHASE"
      : state === "RECOVERED" || state === "ESCALATED"
        ? "TERMINAL"
        : state;
  return order.indexOf(current) > order.indexOf(nodeId);
}

export function RecoveryFlow({ transaction }: { transaction: Transaction | null }) {
  const state = transaction?.state;
  const phaseLabel =
    state === "RETRYING" ? "RETRYING" : state === "REROUTING" ? "REROUTING" : "RETRYING / REROUTING";
  const terminalLabel =
    state === "RECOVERED" ? "RECOVERED" : state === "ESCALATED" ? "ESCALATED" : "RECOVERED / ESCALATED";

  return (
    <section className="card overflow-hidden p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="section-label">Recovery state flow</p>
          <p className="mt-2 text-[15px] font-semibold text-navy">
            {transaction ? transaction.transaction_id : "Waiting for a transaction"}
          </p>
        </div>
        {transaction && (
          <p className="font-mono text-[12px] text-secondary">
            {transaction.routing.error_code} · {transaction.routing.recovery_strategy || "RETRY"}
          </p>
        )}
      </div>
      <div className="mt-6 flex flex-wrap items-center gap-2 md:gap-3">
        {NODES.map((node, index) => {
          const active = Boolean(state && node.match.includes(state));
          const done = passed(state, node.id);
          const label =
            node.id === "PHASE" ? phaseLabel : node.id === "TERMINAL" ? terminalLabel : node.label;
          return (
            <div key={node.id} className="flex items-center gap-2 md:gap-3">
              <div
                className={cx(
                  "min-w-[118px] rounded-card border px-3 py-2 text-center text-[11px] font-semibold tracking-wide transition-all duration-500",
                  done && !active && "border-success/40 bg-[#F3FBF7] text-success",
                  tone(state, active),
                  active && "shadow-card scale-[1.03]",
                )}
              >
                {label}
              </div>
              {index < NODES.length - 1 && (
                <span
                  className={cx(
                    "hidden h-px w-6 bg-[#D0D5DD] sm:block md:w-10",
                    (active || done) && "bg-navy/40",
                  )}
                />
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
