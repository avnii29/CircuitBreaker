import type { AuditEvent, Transaction } from "../types";
import { AuditTimeline } from "./AuditTimeline";

export function AuditDrawer({
  transaction,
  events,
  loading,
  onClose,
}: {
  transaction: Transaction | null;
  events: AuditEvent[];
  loading: boolean;
  onClose: () => void;
}) {
  if (!transaction) {
    return (
      <section className="card p-6">
        <p className="section-label">Audit log</p>
        <p className="mt-3 text-[13px] text-secondary">
          Select a transaction to load its engine audit trail.
        </p>
      </section>
    );
  }

  return (
    <section className="card overflow-hidden">
      <header className="flex items-start justify-between gap-3 border-b border-[rgba(15,40,50,0.08)] px-6 py-5">
        <div>
          <p className="section-label">What the engine did</p>
          <p className="mt-2 font-mono text-[13px] font-semibold text-navy">{transaction.transaction_id}</p>
          <p className="mt-1 text-[12px] text-secondary">Chronological recovery decisions for this payment</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-2 py-1 text-[12px] text-secondary hover:text-navy"
        >
          Close
        </button>
      </header>
      <div className="custom-scroll max-h-[360px] overflow-y-auto px-6 py-5">
        {loading ? (
          <p className="text-[13px] text-secondary">Loading audit trail...</p>
        ) : events.length === 0 ? (
          <p className="text-[13px] text-secondary">No audit events yet.</p>
        ) : (
          <AuditTimeline events={events} />
        )}
      </div>
    </section>
  );
}
