import type { Transaction } from "../types";
import { isActiveRecovery } from "../types";
import { StatusPill } from "./StatusPill";
import { formatAge, formatINR, cx } from "../lib/format";
import { useNow } from "../hooks/useAnimatedNumber";

export function LiveFailureStream({
  transactions,
  selectedId,
  busy,
  onSelect,
  onRecover,
  showRecover = false,
  heading = "Transactions",
  subheading = "Intercepted failures and outcomes",
}: {
  transactions: Transaction[];
  selectedId: string | null;
  busy: string | null;
  onSelect: (id: string) => void;
  onRecover?: (id: string) => void;
  showRecover?: boolean;
  heading?: string;
  subheading?: string;
}) {
  const now = useNow(1000);

  return (
    <section className="card flex min-h-[520px] flex-col overflow-hidden">
      <header className="flex items-start justify-between gap-3 border-b border-[rgba(15,40,50,0.08)] px-6 py-5">
        <div>
          <p className="section-label">{heading}</p>
          <p className="mt-1 text-[13px] text-secondary">{subheading}</p>
        </div>
        <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-success">
          LIVE
          <span className="h-1.5 w-1.5 rounded-full bg-success" />
        </span>
      </header>

      {transactions.length === 0 ? (
        <div className="flex flex-1 items-center justify-center px-8 py-16 text-center">
          <div>
            <p className="text-[15px] font-medium text-navy">No failures intercepted yet</p>
            <p className="mt-2 max-w-sm text-[13px] leading-5 text-secondary">
              Trigger a simulation to watch the recovery engine hold the cart and open an
              alternate payment route.
            </p>
          </div>
        </div>
      ) : (
        <div className="custom-scroll flex-1 overflow-auto">
          <div
            className={cx(
              "hidden min-w-[720px] gap-3 border-b border-[rgba(15,40,50,0.06)] px-6 py-2 text-[11px] font-semibold tracking-[0.08em] text-muted md:grid",
              showRecover
                ? "grid-cols-[1.15fr_1.1fr_1fr_0.8fr_0.7fr_0.9fr_0.5fr_0.9fr]"
                : "grid-cols-[1.15fr_1.1fr_1fr_0.8fr_0.7fr_0.9fr_0.5fr]",
            )}
          >
            <span>STATUS</span>
            <span>TRANSACTION</span>
            <span>CUSTOMER</span>
            <span>BANK</span>
            <span>AMOUNT</span>
            <span>ERROR</span>
            <span>AGE</span>
            {showRecover && <span>ACTION</span>}
          </div>
          <ul>
            {transactions.map((txn) => {
              const selected = txn.transaction_id === selectedId;
              const recovering = busy === `recover:${txn.transaction_id}`;
              return (
                <li key={txn.transaction_id}>
                  <div
                    className={cx(
                      "grid min-w-[720px] grid-cols-1 items-center gap-3 border-b border-[rgba(15,40,50,0.06)] px-6 py-3.5 transition-colors duration-150 hover:bg-[#F8FAFC]",
                      showRecover
                        ? "md:grid-cols-[1.15fr_1.1fr_1fr_0.8fr_0.7fr_0.9fr_0.5fr_0.9fr]"
                        : "md:grid-cols-[1.15fr_1.1fr_1fr_0.8fr_0.7fr_0.9fr_0.5fr]",
                      selected && "bg-[#F5F8FF]",
                    )}
        style={selected ? { boxShadow: "inset 2px 0 0 #2E5CFF" } : undefined}
                  >
                    <button
                      type="button"
                      onClick={() => onSelect(txn.transaction_id)}
                      className="contents text-left"
                    >
                      <span>
                        <StatusPill state={txn.state} />
                      </span>
                      <span className="font-mono text-[12px] font-medium tracking-wide text-navy">
                        {txn.transaction_id}
                      </span>
                      <span className="truncate text-[13px] text-secondary">{txn.customer.name}</span>
                      <span className="truncate text-[13px] text-secondary">{txn.bank || txn.routing.bank}</span>
                      <span className="tabular text-[13px] font-medium text-ink">
                        {formatINR(txn.order.amount)}
                      </span>
                      <span className="truncate font-mono text-[12px] text-secondary">
                        {txn.routing.error_code}
                      </span>
                      <span className="tabular text-[12px] text-muted">{formatAge(txn.created_at, now)}</span>
                    </button>
                    {showRecover && (
                      <span>
                        {isActiveRecovery(txn.state) && onRecover ? (
                          <button
                            type="button"
                            disabled={busy !== null}
                            onClick={() => onRecover(txn.transaction_id)}
                            className="focus-ring rounded-md bg-blue px-2.5 py-1 text-[12px] font-semibold text-white disabled:opacity-50"
                          >
                            {recovering ? "Recovering..." : "Recover"}
                          </button>
                        ) : txn.state === "RECOVERED" ? (
                          <span className="text-[12px] font-medium text-success">Rescued</span>
                        ) : (
                          <span className="text-[12px] text-muted">-</span>
                        )}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
