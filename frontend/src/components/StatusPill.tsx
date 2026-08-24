import type { TransactionState } from "../types";
import { isActiveRecovery } from "../types";
import { cx } from "../lib/format";

const STYLES: Record<TransactionState, string> = {
  INITIATED: "bg-[#EEF2FF] text-blue",
  FAILED: "bg-[#FDECEC] text-danger",
  AUTOMATED_LOOP: "bg-[#FFF6E5] text-warning",
  RETRYING: "bg-[#FFF6E5] text-warning",
  REROUTING: "bg-[#FFF6E5] text-warning",
  RECOVERED: "bg-[#E6F8F0] text-success",
  ESCALATED: "bg-[#FDECEC] text-danger",
};

const LABELS: Record<TransactionState, string> = {
  INITIATED: "INITIATED",
  FAILED: "FAILED",
  AUTOMATED_LOOP: "AUTOMATED LOOP",
  RETRYING: "RETRYING",
  REROUTING: "REROUTING",
  RECOVERED: "RECOVERED",
  ESCALATED: "ESCALATED",
};

export function StatusPill({ state }: { state: TransactionState }) {
  const looping = isActiveRecovery(state);
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-semibold tracking-wide",
        STYLES[state],
      )}
    >
      {looping && (
        <span className="pulse-amber inline-block h-1.5 w-1.5 rounded-full bg-warning" />
      )}
      {state === "RECOVERED" && <span aria-hidden="true">✓</span>}
      {LABELS[state]}
    </span>
  );
}

export function CircuitMark({ className }: { className?: string }) {
  return (
    <img
      src="/logo.png"
      alt="CircuitBreaker"
      className={className}
    />
  );
}

export function BrandName({ className }: { className?: string }) {
  return (
    <span className={className}>
      Circuit<span className="text-[#2E5CFF]">Breaker</span>
    </span>
  );
}

export function PlayIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d="M3.2 2.1v7.8L10 6 3.2 2.1Z" fill="currentColor" />
    </svg>
  );
}

export function ArrowIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path
        d="M3 7h8M7.5 3.5 11 7l-3.5 3.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
