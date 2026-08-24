import type { TransactionState } from "../types";
import { cx } from "../lib/format";

const STEPS: { key: TransactionState; label: string }[] = [
  { key: "INITIATED", label: "INITIATED" },
  { key: "FAILED", label: "FAILED" },
  { key: "AUTOMATED_LOOP", label: "AUTOMATED LOOP" },
  { key: "RETRYING", label: "RETRYING" },
  { key: "REROUTING", label: "REROUTING" },
  { key: "RECOVERED", label: "RECOVERED" },
  { key: "ESCALATED", label: "ESCALATED" },
];

function rank(state: TransactionState): number {
  if (state === "INITIATED") return 0;
  if (state === "FAILED") return 1;
  if (state === "AUTOMATED_LOOP") return 2;
  if (state === "RETRYING" || state === "REROUTING") return 3;
  return 4;
}

export function StateMachine({ state }: { state: TransactionState }) {
  const current = rank(state);

  return (
    <ol className="flex flex-col gap-0">
      {STEPS.map((step, index) => {
        const active = step.key === state;
        const skipped =
          (step.key === "RECOVERED" && state === "ESCALATED") ||
          (step.key === "ESCALATED" && state === "RECOVERED") ||
          (step.key === "RETRYING" && state === "REROUTING") ||
          (step.key === "REROUTING" && state === "RETRYING");
        const done =
          !skipped &&
          ((step.key === "RECOVERED" && state === "RECOVERED") ||
            (step.key === "ESCALATED" && state === "ESCALATED") ||
            (!["RECOVERED", "ESCALATED", "RETRYING", "REROUTING"].includes(step.key) &&
              current > rank(step.key)) ||
            ((step.key === "RETRYING" || step.key === "REROUTING") && current >= 4 && !skipped));
        const running =
          active &&
          (state === "AUTOMATED_LOOP" || state === "RETRYING" || state === "REROUTING");

        return (
          <li key={step.key} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className={cx(
                  "flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold transition-colors duration-300",
                  done && !active && "bg-success text-white",
                  active && (state === "FAILED" || state === "ESCALATED") && "bg-danger text-white",
                  active && state === "RECOVERED" && "bg-success text-white",
                  active && state === "INITIATED" && "bg-blue text-white",
                  running && "bg-warning text-white",
                  skipped && "bg-[#E4E7EC] text-muted",
                  !done && !active && !skipped && "border border-[#D0D5DD] bg-white text-muted",
                )}
              >
                {done && !active ? "✓" : active ? "●" : "○"}
              </span>
              {index < STEPS.length - 1 && (
                <span className="my-1 w-px flex-1 bg-[rgba(15,40,50,0.12)]" />
              )}
            </div>
            <div className={cx("pb-4", index === STEPS.length - 1 && "pb-0")}>
              <p
                className={cx(
                  "text-[12px] font-semibold tracking-wide transition-colors duration-300",
                  (active || (done && !skipped)) && "text-navy",
                  skipped && "text-muted",
                  !done && !active && "text-muted",
                )}
              >
                {step.label}
                {running && (
                  <span className="ml-2 text-[11px] font-medium text-warning pulse-amber">
                    running
                  </span>
                )}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
