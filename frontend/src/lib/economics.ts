import type { RecoveryEconomics, Transaction } from "../types";

export function economicsOf(transaction: Transaction | null | undefined): RecoveryEconomics | null {
  const payload = transaction?.smart_routing?.economics;
  if (!payload || typeof payload !== "object") return null;
  return payload;
}

export function eventLabel(eventType: string | undefined): string {
  switch (eventType) {
    case "CHECKOUT_ABANDONMENT":
      return "Checkout abandoned";
    case "SUBSCRIPTION_FAILURE":
      return "Subscription failure";
    case "OVERDUE_RECEIVABLE":
      return "Overdue receivable";
    case "PAYMENT_FAILURE":
      return "Payment failure";
    default:
      return eventType?.replace(/_/g, " ") || "Revenue event";
  }
}

export function actionLabel(action: string | undefined): string {
  if (action === "DO_NOTHING") return "DO NOTHING";
  if (action === "ESCALATE") return "ESCALATE";
  if (action === "ACT") return "ACT";
  return action || "-";
}

export function outcomeLabel(transaction: Transaction): string {
  const action = economicsOf(transaction)?.selected_action;
  if (action === "DO_NOTHING") return "SKIPPED";
  if (transaction.state === "RECOVERED") return "RECOVERED";
  if (transaction.state === "ESCALATED") return "ESCALATED";
  return transaction.state.replace(/_/g, " ");
}

export function priorityScore(transaction: Transaction): number {
  return economicsOf(transaction)?.priority_score ?? transaction.order.amount;
}
