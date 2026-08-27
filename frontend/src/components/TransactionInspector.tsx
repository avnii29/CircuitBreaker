import { useState } from "react";
import type { ExecuteRecoveryResponse, RouteAttempt, RouteScore, Transaction } from "../types";
import { isActiveRecovery } from "../types";
import { ArrowIcon, StatusPill } from "./StatusPill";
import { StateMachine } from "./StateMachine";
import { AuditTimeline } from "./AuditTimeline";
import { formatCountdown, formatINR, formatPercent, cx } from "../lib/format";
import { useNow } from "../hooks/useAnimatedNumber";
import { actionLabel, economicsOf, eventLabel } from "../lib/economics";

function remaining(expiresAt: string, now: number): number {
  return Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 1000));
}

export function TransactionInspector({
  transaction,
  busy,
  notice,
  executeResult,
  onRecover,
  onSelectRoute,
  onExecuteRoute,
}: {
  transaction: Transaction | null;
  busy: string | null;
  notice: string | null;
  executeResult: ExecuteRecoveryResponse | null;
  onRecover: (id: string) => void;
  onSelectRoute?: (id: string) => void;
  onExecuteRoute?: (id: string) => void;
}) {
  const now = useNow(1000);
  const [copied, setCopied] = useState(false);
  const [whyOpen, setWhyOpen] = useState(false);
  const [evalPhase, setEvalPhase] = useState<"idle" | "evaluating" | "counted" | "selected">("idle");
  const [detailsOpen, setDetailsOpen] = useState(false);

  if (!transaction) {
    return (
      <section className="card flex min-h-[520px] items-center justify-center p-8">
        <div className="max-w-sm text-center">
          <p className="section-label">What CircuitBreaker is doing</p>
          <p className="mt-4 text-[16px] font-medium text-navy">
            Trigger a revenue event to watch the agent decide
          </p>
          <p className="mt-2 text-[13px] leading-5 text-secondary">
            The diagnosis, chosen action, and outcome appear here as the engine runs.
          </p>
        </div>
      </section>
    );
  }

  const left = remaining(transaction.recovery.window_expires_at, now);
  const total = transaction.recovery.window_seconds;
  const progress = Math.min(100, ((total - left) / total) * 100);
  const looping = isActiveRecovery(transaction.state);
  const recovered = transaction.state === "RECOVERED";
  const escalated = transaction.state === "ESCALATED";
  const guardrail = transaction.recovery.guardrail;
  const recovering = busy === `recover:${transaction.transaction_id}`;
  const selecting = busy === `select:${transaction.transaction_id}`;
  const executing = busy === `execute-route:${transaction.transaction_id}`;
  const smart = transaction.smart_routing;
  const policyBlocked = Boolean(smart?.policy_blocked);
  const justRecovered =
    executeResult?.executed &&
    executeResult.transaction.transaction_id === transaction.transaction_id &&
    recovered;
  const blocked =
    Boolean(executeResult?.blocked && executeResult.transaction.transaction_id === transaction.transaction_id) ||
    Boolean(guardrail && !guardrail.passed);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(transaction.recovery.payment_link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section className="card fade-in flex min-h-[520px] flex-col overflow-hidden">
      <header className="border-b border-[rgba(15,40,50,0.08)] px-6 py-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="section-label">Revenue event</p>
            <p className="mt-2 font-mono text-[15px] font-semibold tracking-wide text-navy">
              {transaction.transaction_id}
            </p>
          </div>
          <StatusPill state={transaction.state} />
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-[13px] sm:grid-cols-3">
          <Meta label="Status" value={transaction.state} />
          <Meta label="Customer" value={transaction.customer.name} />
          <Meta label="Bank" value={transaction.routing.bank} />
          <Meta label="Amount" value={formatINR(transaction.order.amount)} />
          <Meta label="Error" value={transaction.routing.error_code} mono />
          <Meta label="Merchant" value={transaction.order.merchant_id} />
        </dl>
      </header>

      <div className="custom-scroll flex-1 space-y-6 overflow-y-auto px-6 py-6">
        <EconomicsPanel transaction={transaction} recovered={recovered} escalated={escalated} />

        {recovered && (
          <div className="success-in rounded-card border border-[rgba(0,179,104,0.25)] bg-[#F3FBF7] px-4 py-3">
            <p className="text-[13px] font-semibold text-success">Payment recovered</p>
            <p className="mt-1 text-[13px] text-secondary">
              {formatINR(transaction.money_recovered || transaction.order.amount)} recovered. Cart released.
            </p>
          </div>
        )}

        {escalated && (
          <div className="rounded-card border border-[rgba(102,112,133,0.25)] bg-[#F7F8FA] px-4 py-3">
            <p className="text-[13px] font-semibold text-secondary">
              {economicsOf(transaction)?.selected_action === "DO_NOTHING"
                ? "Recovery intentionally skipped"
                : policyBlocked
                  ? "AUTOMATED RECOVERY BLOCKED"
                  : "Recovery stopped"}
            </p>
            <p className="mt-1 text-[13px] text-secondary">
              {economicsOf(transaction)?.selected_action === "DO_NOTHING"
                ? economicsOf(transaction)?.rationale
                : policyBlocked
                ? smart?.policy_reason || "Transaction exceeds automated recovery policy limit."
                : "Automated recovery stopped safely. Cart released. Human review required."}
            </p>
          </div>
        )}

        {blocked && looping && (
          <div className="rounded-card border border-[rgba(229,72,77,0.25)] bg-[#FDF6F6] px-4 py-3">
            <p className="text-[13px] font-semibold text-danger">FALLBACK EXECUTED</p>
            <p className="mt-1 text-[13px] text-secondary">
              {notice || guardrail?.blocked_reason || "AI output did not pass money-safety checks."}
            </p>
          </div>
        )}

        {looping && (
          <button
            type="button"
            disabled={selecting || executing || recovering}
            onClick={() => (onExecuteRoute ?? onRecover)(transaction.transaction_id)}
            className="focus-ring inline-flex w-full items-center justify-center gap-2 rounded-md bg-blue px-4 py-3 text-[14px] font-semibold text-white hover:bg-[#2448d6] disabled:opacity-50"
          >
            {executing || recovering ? "Executing..." : "Execute recovery"}
            {!(executing || recovering) && <ArrowIcon />}
          </button>
        )}

        <button
          type="button"
          onClick={() => setDetailsOpen((value) => !value)}
          className="text-[12px] font-semibold text-blue"
        >
          {detailsOpen ? "Hide decision details" : "View decision details"}
        </button>

        {detailsOpen && (
          <>
        <div className="grid gap-6 lg:grid-cols-[160px_1fr]">
          <div>
            <p className="section-label mb-4">Lifecycle</p>
            <StateMachine state={transaction.state} />
          </div>
          <div>
            <p className="section-label">Recovery window</p>
            <p className="mt-3 tabular text-[28px] font-semibold tracking-tight text-navy">
              {looping ? `${formatCountdown(left)} remaining` : recovered ? "Recovered" : escalated ? "Expired" : formatCountdown(left)}
            </p>
            <p className="mt-1 text-[12px] text-secondary">
              DEMO MODE · {transaction.recovery.window_seconds}s window
            </p>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#EEF2F6]">
              <div
                className={cx(
                  "h-full rounded-full transition-[width] duration-200",
                  recovered ? "bg-success" : escalated ? "bg-secondary" : "bg-warning",
                )}
                style={{ width: recovered ? "100%" : `${progress}%` }}
              />
            </div>
          </div>
        </div>

        <Separator title="Recovery state" />
        <div className="grid grid-cols-2 gap-4 text-[13px]">
          <Meta label="Attempts" value={`${transaction.recovery.retry_count ?? transaction.recovery.attempt_count} / ${transaction.recovery.max_attempts}`} />
          <Meta label="Cart status" value={transaction.cart_status} />
          <Meta label="Recovery route" value={transaction.recovery.recovery_route || "UPI FALLBACK"} />
          <Meta label="Money recovered" value={formatINR(transaction.money_recovered)} />
        </div>

        <RouteAttemptChain attempts={transaction.routing.route_attempts ?? []} />

        <Separator title="Failure analysis" />
        <div className="grid grid-cols-2 gap-4 text-[13px]">
          <Meta label="Bank" value={transaction.routing.bank} />
          <Meta label="Raw code" value={transaction.routing.error_code} mono />
          <div className="col-span-2 flex flex-wrap items-baseline gap-x-2">
            <p className="text-[12px] text-secondary">Human explanation:</p>
            <p className="text-ink">{transaction.routing.error_label || transaction.failure_reason}</p>
          </div>
          <Meta label="Classification" value={transaction.routing.recovery_eligible ? "RECOVERABLE" : "NOT RECOVERABLE"} />
          <Meta
            label="Confidence"
            value={transaction.recovery.confidence ? `${Math.round(transaction.recovery.confidence)}%` : "-"}
          />
        </div>

        <SmartRoutingSection
          transaction={transaction}
          looping={looping}
          selecting={selecting}
          executing={executing}
          recovering={recovering}
          evalPhase={selecting ? "evaluating" : smart?.selected_route ? "selected" : evalPhase}
          whyOpen={whyOpen}
          onToggleWhy={() => setWhyOpen((value) => !value)}
          onEvaluate={() => {
            setEvalPhase("evaluating");
            onSelectRoute?.(transaction.transaction_id);
          }}
          onExecute={() => (onExecuteRoute ?? onRecover)(transaction.transaction_id)}
        />

        <Separator title="AI output validation" />
        <p className={cx("text-[13px] font-semibold", guardrail?.passed ? "text-success" : "text-secondary")}>
          {!guardrail ? "PENDING" : guardrail.passed ? "PASSED" : "FALLBACK EXECUTED"}
        </p>

        <Separator title="AI recovery message" />
        <p className="rounded-card bg-[#F5F8FB] px-4 py-3 text-[14px] leading-6 text-ink">
          {transaction.recovery.customer_message || "Message will appear when recovery starts."}
        </p>

        <div>
          <p className="text-[12px] text-secondary">Demo recovery link</p>
          <p className="mt-1 break-all font-mono text-[12px] text-blue">
            {transaction.recovery.payment_link}
          </p>
          <button
            type="button"
            onClick={() => void copyLink()}
            className="focus-ring mt-3 rounded-md border border-[rgba(15,40,50,0.12)] bg-white px-3 py-1.5 text-[12px] font-semibold text-navy"
          >
            {copied ? "Recovery link copied" : "Copy Recovery Link"}
          </button>
          <p className="mt-2 text-[11px] tracking-wide text-muted">
            DEMO RECOVERY LINK · not a live Razorpay URL
          </p>
        </div>

        {justRecovered && (
          <p className="text-center text-[13px] font-semibold text-success">Recovered ✓</p>
        )}

        <Separator title="Recovery timeline" />
        <AuditTimeline events={transaction.audit_trail} />
          </>
        )}
      </div>
    </section>
  );
}

function EconomicsPanel({
  transaction,
  recovered,
  escalated,
}: {
  transaction: Transaction;
  recovered: boolean;
  escalated: boolean;
}) {
  const econ = economicsOf(transaction);
  if (!econ) {
    return (
      <div className="rounded-card border border-[rgba(15,40,50,0.08)] bg-[#F8FAFC] px-4 py-3">
        <p className="text-[13px] text-secondary">Intervention economics will appear once the agent evaluates this event.</p>
      </div>
    );
  }
  const selected = econ.candidates.find((row) => row.id === econ.selected_intervention);
  return (
    <div className="space-y-4">
      <div>
        <p className="section-label">Revenue at risk</p>
        <p className="mt-2 tabular text-[32px] font-semibold tracking-tight text-navy">{formatINR(econ.revenue_at_risk)}</p>
        <p className="mt-1 text-[13px] text-secondary">
          {eventLabel(econ.event_type)} · Predicted loss {formatPercent(econ.predicted_loss_probability)}
        </p>
      </div>
      <div>
        <p className="section-label">Root cause</p>
        <p className="mt-2 text-[14px] leading-6 text-ink">{econ.root_cause}</p>
      </div>
      <div>
        <p className="section-label">Options considered</p>
        <p className="mt-1 text-[11px] text-secondary">SIMULATED probabilities and intervention costs</p>
        <ul className="mt-3 space-y-2">
          {econ.candidates.slice(0, 4).map((row) => (
            <li
              key={row.id}
              className={cx(
                "flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-[13px]",
                row.id === econ.selected_intervention ? "border-blue/30 bg-[#F5F8FF]" : "border-[rgba(15,40,50,0.08)]",
              )}
            >
              <span className="font-medium text-navy">{row.label}</span>
              <span className="tabular text-secondary">
                {formatPercent(row.predicted_success_probability)} · {formatINR(row.expected_recovery_value)} EV
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-card border border-[rgba(15,40,50,0.08)] px-4 py-3">
        <p className="section-label">Agent decision</p>
        <p className="mt-2 text-[18px] font-semibold text-navy">
          {actionLabel(econ.selected_action)}
          {selected ? ` · ${selected.label}` : ""}
        </p>
        <p className="mt-2 text-[13px] leading-6 text-secondary">{econ.rationale}</p>
        <p className="mt-2 text-[12px] text-secondary">
          Expected ₹{econ.expected_recovery_value.toLocaleString("en-IN")} · Simulated cost ₹{econ.intervention_cost}
          {econ.selected_action === "DO_NOTHING" && econ.cost_avoided
            ? ` · Unnecessary cost avoided ₹${econ.cost_avoided}`
            : ""}
        </p>
      </div>
      {recovered && (
        <div className="rounded-card border border-[rgba(0,179,104,0.25)] bg-[#F3FBF7] px-4 py-3">
          <p className="text-[13px] font-semibold text-success">
            Result · {formatINR(econ.actual_recovered || transaction.money_recovered || transaction.order.amount)} recovered
          </p>
          <p className="mt-1 text-[12px] text-secondary">
            Counterfactual (simulated): without intervention estimated ₹{econ.counterfactual.without_expected.toLocaleString("en-IN")} recovered naturally.
          </p>
        </div>
      )}
      {escalated && econ.selected_action === "DO_NOTHING" && (
        <p className="text-[12px] text-secondary">
          Estimated unnecessary intervention cost avoided: {formatINR(econ.cost_avoided || econ.intervention_cost || 0)}
        </p>
      )}
    </div>
  );
}

function RouteAttemptChain({ attempts }: { attempts: RouteAttempt[] }) {
  if (attempts.length === 0) return null;
  return (
    <div className="rounded-card border border-[rgba(15,40,50,0.08)] bg-[#F8FAFC] px-4 py-3">
      <p className="section-label">Route attempts</p>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-ink">
        {attempts.map((attempt, index) => (
          <span key={`${attempt.route}-${attempt.sequence}`} className="inline-flex items-center gap-2">
            <span>
              Tried {attempt.route.replace(/_/g, " ")} →{" "}
              <span className={attempt.outcome === "SUCCEEDED" ? "font-semibold text-success" : "font-semibold text-danger"}>
                {attempt.outcome.toLowerCase()}
              </span>
            </span>
            {index < attempts.length - 1 && <span className="text-muted">→</span>}
          </span>
        ))}
      </p>
    </div>
  );
}

function Meta({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <dt className="text-[12px] text-secondary">{label}:</dt>
      <dd className={cx("text-ink", mono && "font-mono text-[12px]")}>{value}</dd>
    </div>
  );
}

function Separator({ title }: { title: string }) {
  return (
    <div className="border-t border-[rgba(15,40,50,0.08)] pt-5">
      <p className="section-label">{title}</p>
    </div>
  );
}

function barColor(route: RouteScore, selected: string | null): string {
  if (route.route === selected) return "bg-blue";
  if (!route.eligible) return "bg-[#D0D5DD]";
  if (route.score >= 75) return "bg-success";
  if (route.score >= 60) return "bg-warning";
  return "bg-[#D0D5DD]";
}

function SmartRoutingSection({
  transaction,
  looping,
  selecting,
  executing,
  recovering,
  evalPhase,
  whyOpen,
  onToggleWhy,
  onEvaluate,
  onExecute,
}: {
  transaction: Transaction;
  looping: boolean;
  selecting: boolean;
  executing: boolean;
  recovering: boolean;
  evalPhase: "idle" | "evaluating" | "counted" | "selected";
  whyOpen: boolean;
  onToggleWhy: () => void;
  onEvaluate: () => void;
  onExecute: () => void;
}) {
  const smart = transaction.smart_routing;
  const classification = smart?.failure_classification;
  const selected = smart?.selected_route;
  const score = smart?.route_score;
  const confidence = smart?.confidence;
  const scored = smart?.scored_routes ?? [];
  const alternatives = [...(smart?.alternatives ?? [])].sort((a, b) => b.score - a.score);

  return (
    <div className="space-y-4">
      <Separator title="Smart Routing" />
      <p className="text-[11px] font-semibold tracking-[0.12em] text-muted">SIMULATED · DEMO DATA</p>

      {evalPhase === "evaluating" && (
        <p className="text-[13px] text-secondary">Evaluating recovery routes...</p>
      )}
      {evalPhase !== "evaluating" && scored.length > 0 && (
        <p className="text-[13px] text-secondary">{scored.length} routes evaluated</p>
      )}
      {selected && evalPhase !== "evaluating" && (
        <p className="text-[13px] font-semibold text-blue">{smart?.display_name || selected} selected</p>
      )}

      <div className="grid grid-cols-2 gap-4 text-[13px]">
        <Meta label="Failure classification" value={classification?.category?.replace(/_/g, " ") || "Pending evaluation"} />
        <Meta label="Recoverable" value={classification ? (classification.recoverable ? "YES" : "NO") : "-"} />
        <Meta label="Selected route" value={smart?.display_name || selected || "Not evaluated"} />
        <Meta label="Score" value={score != null ? `${score} / 100` : "-"} />
        <Meta
          label="Confidence"
          value={confidence != null ? `${Math.round(confidence * 100)}%` : "-"}
        />
        <Meta
          label="Decision"
          value={smart?.policy_blocked ? "BLOCKED" : selected ? "AUTOMATED" : "PENDING"}
        />
      </div>

      {scored.length > 0 && (
        <div className="space-y-3">
          {scored
            .slice()
            .sort((a, b) => b.score - a.score)
            .map((route) => (
              <div key={route.route}>
                <div className="flex items-center justify-between text-[12px]">
                  <span className={cx("font-medium", route.route === selected ? "text-blue" : "text-secondary")}>
                    {route.display_name}
                  </span>
                  <span className="tabular text-navy">{route.score}</span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#EEF2F6]">
                  <div
                    className={cx("h-full rounded-full transition-[width] duration-300", barColor(route, selected ?? null))}
                    style={{ width: `${route.score}%` }}
                  />
                </div>
              </div>
            ))}
        </div>
      )}

      {smart?.reason && (
        <div className="flex flex-wrap items-baseline gap-x-2 text-[13px] leading-5">
          <p className="text-[12px] text-secondary">Reason:</p>
          <p className="min-w-0 text-ink">{smart.reason.replace(/\s*\n\s*/g, " ")}</p>
        </div>
      )}

      {alternatives.length > 0 && (
        <div>
          <p className="text-[12px] font-semibold tracking-[0.08em] text-secondary">ALTERNATIVE ROUTES</p>
          <ul className="mt-2 space-y-1 text-[13px]">
            {alternatives.map((row) => (
              <li key={row.route} className="flex justify-between text-secondary">
                <span>{row.display_name || row.route.replace(/_/g, " ")}</span>
                <span className="tabular text-navy">{row.score}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {whyOpen && (smart?.why.length ?? 0) > 0 && (
        <div className="rounded-card border border-[rgba(47,91,255,0.16)] bg-[#F5F8FF] px-4 py-3">
          <p className="text-[12px] font-semibold tracking-[0.08em] text-blue">
            WHY {smart?.display_name?.toUpperCase() || "THIS ROUTE"}?
          </p>
          <ol className="mt-2 list-decimal space-y-1 pl-4 text-[13px] leading-5 text-ink">
            {smart?.why.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </div>
      )}

      {looping && (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold tracking-[0.12em] text-muted">SIMULATED ROUTE EXECUTION</p>
          {!selected && (
            <button
              type="button"
              disabled={selecting || executing || recovering}
              onClick={onEvaluate}
              className="focus-ring inline-flex w-full items-center justify-center gap-2 rounded-md bg-blue px-4 py-3 text-[14px] font-semibold text-white transition-colors duration-150 hover:bg-[#2448d6] disabled:opacity-50"
            >
              {selecting ? "Evaluating recovery routes..." : "Evaluate Recovery Route"}
            </button>
          )}
          {selected && (
            <>
              <button
                type="button"
                onClick={onToggleWhy}
                className="focus-ring w-full rounded-md border border-[rgba(15,40,50,0.12)] bg-white px-4 py-2.5 text-[13px] font-semibold text-navy"
              >
                {whyOpen ? "Hide explanation" : "Why this route?"}
              </button>
              <button
                type="button"
                disabled={selecting || executing || recovering}
                onClick={onExecute}
                className="focus-ring inline-flex w-full items-center justify-center gap-2 rounded-md bg-blue px-4 py-3 text-[14px] font-semibold text-white transition-colors duration-150 hover:bg-[#2448d6] disabled:opacity-50"
              >
                {executing ? "Executing simulated route..." : "Execute Recovery"}
                {!executing && <ArrowIcon />}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
