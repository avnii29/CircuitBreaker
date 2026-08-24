import type {
  BatchSimulateResponse,
  ExecuteRecoveryResponse,
  ExecuteSelectedRouteResponse,
  HealthResponse,
  RoutingDecision,
  RoutingPerformanceResponse,
  RunRecoverySimulationResponse,
  SimulateBatchRequest,
  SimulateCheckoutRequest,
  TelemetryDashboard,
  Transaction,
  AuditEvent,
  PolicySnapshot,
  PolicyView,
} from "../types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

if (import.meta.env.PROD && /localhost|127\.0\.0\.1/.test(API_BASE)) {
  throw new Error("VITE_API_BASE_URL must not point at localhost in a production build.");
}

let tenantHeader = "";

export function setTenantHeader(tenantId: string) {
  tenantHeader = tenantId;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: string }).msg);
        }
        return JSON.stringify(item);
      })
      .join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      ...(tenantHeader ? { "X-Tenant-Id": tenantHeader } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new ApiError(response.status, detailMessage(body.detail, response.statusText));
  }
  return (await response.json()) as T;
}

export const api = {
  baseUrl: API_BASE,
  health: () => request<HealthResponse>("/api/v1/health"),
  telemetry: () => request<TelemetryDashboard>("/api/v1/payments/telemetry-dashboard"),
  listTransactions: () => request<Transaction[]>("/api/v1/payments/transactions"),
  getTransaction: (id: string) => request<Transaction>(`/api/v1/payments/transactions/${id}`),
  simulateCheckout: (body?: SimulateCheckoutRequest) =>
    request<Transaction>("/api/v1/payments/simulate-checkout", {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  executeRecovery: (id: string, body?: { idempotency_key?: string }) =>
    request<ExecuteRecoveryResponse>(`/api/v1/payments/execute-recovery-action/${id}`, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  selectRecoveryRoute: (id: string) =>
    request<RoutingDecision>(`/api/v1/payments/select-recovery-route/${id}`, {
      method: "POST",
    }),
  executeSelectedRoute: (id: string) =>
    request<ExecuteSelectedRouteResponse>(`/api/v1/payments/execute-selected-route/${id}`, {
      method: "POST",
    }),
  routingPerformance: () => request<RoutingPerformanceResponse>("/api/v1/routing/performance"),
  simulateBatch: (body?: SimulateBatchRequest) =>
    request<BatchSimulateResponse>("/api/v1/payments/simulate-batch", {
      method: "POST",
      body: JSON.stringify(body ?? { count: 50 }),
    }),
  runRecoverySimulation: () =>
    request<RunRecoverySimulationResponse>("/api/v1/payments/run-recovery-simulation", {
      method: "POST",
    }),
  resetDemo: () => request<{ ok: boolean; message: string }>("/api/v1/payments/reset-demo", {
    method: "POST",
  }),
  auditLog: (id: string) =>
    request<AuditEvent[]>(`/api/v1/payments/transactions/${id}/audit-log`),
  policy: () => request<PolicyView>("/api/v2/policy"),
  policySnapshots: () => request<{ snapshots: PolicySnapshot[] }>("/api/v2/policy/snapshots"),
  rollbackPolicy: (version: number) =>
    request<{ ok: boolean; snapshot: PolicySnapshot }>(`/api/v2/policy/rollback/${version}`, { method: "POST" }),
  retrainPolicy: () => request<{ ok: boolean; snapshot: PolicySnapshot }>("/api/v2/policy/retrain", { method: "POST" }),
  tenants: () => request<{ tenants: string[] }>("/api/v2/tenants"),
  manualReview: (tenantId?: string) =>
    request<Transaction[]>(
      `/api/v1/payments/manual-review-queue${tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ""}`,
    ),
};
