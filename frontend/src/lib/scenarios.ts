import type { SimulateCheckoutRequest } from "../types";

export const DEMO_SCENARIOS = [
  { id: "GOLDEN_OUTAGE", label: "Golden outage recovery" },
  { id: "TRANSIENT_FAILURE", label: "Transient failure" },
  { id: "BANK_OUTAGE", label: "Bank outage" },
  { id: "HARD_DECLINE", label: "Hard decline" },
  { id: "RISK_BLOCK", label: "Risk block" },
  { id: "HDFC_TECHNICAL", label: "HDFC technical failure" },
  { id: "SBI_TIMEOUT", label: "SBI timeout" },
  { id: "INSUFFICIENT_FUNDS", label: "Insufficient funds" },
  { id: "BANK_DOWN", label: "Bank rail outage" },
  { id: "MIXED_BANK", label: "Mixed bank failures" },
  { id: "REPEATED_ROUTE_FAILURE", label: "Repeated route failure" },
  { id: "HIGH_VALUE", label: "High-value transaction" },
  { id: "EXPIRED_WINDOW", label: "Expired recovery window" },
] as const;

export type DemoScenarioId = (typeof DEMO_SCENARIOS)[number]["id"];

export function scenarioPayload(id: DemoScenarioId): SimulateCheckoutRequest | "batch" {
  if (id === "MIXED_BANK") return "batch";
  if (id === "TRANSIENT_FAILURE") {
    return {
      bank: "HDFC",
      scenario: "TRANSIENT_FAILURE",
      customer_name: "Rahul Sharma",
      customer_phone: "9876543210",
      customer_email: "rahul@example.com",
      merchant_id: "MERCHANT_001",
      amount: 1499,
      demo_scenario: id,
    };
  }
  if (id === "SBI_TIMEOUT") {
    return {
      bank: "SBI",
      customer_name: "Priya Mehta",
      customer_phone: "9876543210",
      customer_email: "priya@example.com",
      merchant_id: "MERCHANT_001",
      amount: 2499,
      demo_scenario: id,
    };
  }
  if (id === "REPEATED_ROUTE_FAILURE") {
    return {
      bank: "HDFC",
      customer_name: "Rahul Sharma",
      customer_phone: "9876543210",
      customer_email: "rahul@example.com",
      merchant_id: "MERCHANT_001",
      amount: 1999,
      force_route_failure: true,
      demo_scenario: id,
    };
  }
  if (id === "HARD_DECLINE") {
    return {
      bank: "HDFC",
      scenario: "HARD_DECLINE",
      customer_name: "Rahul Sharma",
      customer_phone: "9876543210",
      customer_email: "rahul@example.com",
      merchant_id: "MERCHANT_001",
      amount: 1499,
      demo_scenario: id,
    };
  }
  if (id === "INSUFFICIENT_FUNDS") {
    return {
      bank: "HDFC",
      scenario: "FUNDS",
      customer_name: "Rahul Sharma",
      customer_phone: "9876543210",
      customer_email: "rahul@example.com",
      merchant_id: "MERCHANT_001",
      amount: 1499,
      demo_scenario: id,
    };
  }
  if (id === "RISK_BLOCK") {
    return {
      bank: "HDFC",
      scenario: "RISK",
      customer_name: "Rahul Sharma",
      customer_phone: "9876543210",
      customer_email: "rahul@example.com",
      merchant_id: "MERCHANT_001",
      amount: 1999,
      demo_scenario: id,
    };
  }
  if (id === "BANK_OUTAGE") {
    return {
      bank: "SBI",
      scenario: "BANK_OUTAGE",
      customer_name: "Priya Mehta",
      customer_phone: "9876543210",
      customer_email: "priya@example.com",
      merchant_id: "MERCHANT_001",
      amount: 1799,
      demo_scenario: id,
    };
  }
  if (id === "GOLDEN_OUTAGE") {
    return {
      bank: "SBI",
      scenario: "BANK_DOWN",
      customer_name: "Priya Mehta",
      customer_phone: "9876543210",
      customer_email: "priya@example.com",
      merchant_id: "MERCHANT_001",
      amount: 4850,
      demo_scenario: id,
    };
  }
  if (id === "BANK_DOWN") {
    return {
      bank: "SBI",
      scenario: "BANK_DOWN",
      customer_name: "Priya Mehta",
      customer_phone: "9876543210",
      customer_email: "priya@example.com",
      merchant_id: "MERCHANT_001",
      amount: 1799,
      demo_scenario: id,
    };
  }
  if (id === "HIGH_VALUE") {
    return {
      bank: "HDFC",
      customer_name: "Rahul Sharma",
      customer_phone: "9876543210",
      customer_email: "rahul@example.com",
      merchant_id: "MERCHANT_001",
      amount: 15000,
      demo_scenario: id,
    };
  }
  if (id === "EXPIRED_WINDOW") {
    return {
      bank: "HDFC",
      customer_name: "Rahul Sharma",
      customer_phone: "9876543210",
      customer_email: "rahul@example.com",
      merchant_id: "MERCHANT_001",
      amount: 1499,
      expire_window: true,
      demo_scenario: id,
    };
  }
  return {
    bank: "HDFC",
    customer_name: "Rahul Sharma",
    customer_phone: "9876543210",
    customer_email: "rahul@example.com",
    merchant_id: "MERCHANT_001",
    amount: 1499,
    demo_scenario: "HDFC_TECHNICAL",
  };
}
