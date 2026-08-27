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

if (import.meta.env.PROD && /localhost|127\.0\.0\.1|0\.0\.0\.0/.test(API_BASE)) {
  throw new Error("VITE_API_BASE_URL must not point at localhost in a production build.");
}

export type ConnectionState = "CONNECTED" | "CONNECTING" | "RECONNECTING" | "DEGRADED" | "UNAVAILABLE";

const TELEMETRY_CACHE_KEY = "cb.lastTelemetry";
const DEFAULT_TIMEOUT_MS = 20000;
const HEALTH_TIMEOUT_MS = 15000;
const MAX_RETRIES = 2;

let tenantHeader = "";
let connectionState: ConnectionState = "CONNECTING";
let healthFailures = 0;
const connectionListeners = new Set<(state: ConnectionState) => void>();

export function setTenantHeader(tenantId: string) {
  tenantHeader = tenantId;
}

export class ApiError extends Error {
  status: number;
  retryable: boolean;

  constructor(status: number, message: string, retryable = status === 0 || status >= 500) {
    super(message);
    this.status = status;
    this.retryable = retryable;
  }
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in (detail as { message?: unknown })) {
    const nested = (detail as { message?: unknown }).message;
    if (typeof nested === "string") return nested;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: string }).msg);
        }
        return "Request failed.";
      })
      .join("; ");
  }
  return fallback;
}

function setConnectionState(next: ConnectionState) {
  if (next === connectionState) return;
  connectionState = next;
  connectionListeners.forEach((listener) => listener(next));
}

export function getConnectionState(): ConnectionState {
  return connectionState;
}

export function subscribeConnection(listener: (state: ConnectionState) => void): () => void {
  connectionListeners.add(listener);
  listener(connectionState);
  return () => connectionListeners.delete(listener);
}

export function cacheTelemetry(data: TelemetryDashboard) {
  try {
    sessionStorage.setItem(TELEMETRY_CACHE_KEY, JSON.stringify(data));
  } catch {
    /* ignore quota */
  }
}

export function loadCachedTelemetry(): TelemetryDashboard | null {
  try {
    const raw = sessionStorage.getItem(TELEMETRY_CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as TelemetryDashboard;
  } catch {
    return null;
  }
}

function noteHealthSuccess() {
  healthFailures = 0;
  if (connectionState !== "CONNECTED") setConnectionState("CONNECTED");
}

function noteHealthFailure() {
  healthFailures += 1;
  if (healthFailures <= 1) setConnectionState("RECONNECTING");
  else if (healthFailures < 4) setConnectionState("DEGRADED");
  else setConnectionState("UNAVAILABLE");
}

export function noteDataFailure() {
  if (connectionState === "CONNECTED" || connectionState === "CONNECTING") {
    setConnectionState("RECONNECTING");
  }
}

export function noteDataSuccess() {
  if (healthFailures === 0) setConnectionState("CONNECTED");
}

async function sleep(ms: number) {
  await new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function fetchOnce<T>(path: string, init: RequestInit | undefined, timeoutMs: number): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
        ...(tenantHeader ? { "X-Tenant-Id": tenantHeader } : {}),
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        detail?: unknown;
        error?: { message?: string; retryable?: boolean };
      };
      const message =
        body.error?.message || detailMessage(body.detail, "Recovery service is temporarily unavailable.");
      throw new ApiError(response.status, message, Boolean(body.error?.retryable) || response.status >= 500);
    }
    return (await response.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(0, "Request timed out.", true);
    }
    throw new ApiError(0, "Recovery service is temporarily unavailable.", true);
  } finally {
    window.clearTimeout(timer);
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  let lastError: ApiError | null = null;
  const attempts = init?.method && init.method !== "GET" ? 1 : MAX_RETRIES;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await fetchOnce<T>(path, init, timeoutMs);
    } catch (err) {
      lastError = err instanceof ApiError ? err : new ApiError(0, "Recovery service is temporarily unavailable.", true);
      if (!lastError.retryable || attempt === attempts - 1) break;
      await sleep(400 * 2 ** attempt);
    }
  }
  throw lastError ?? new ApiError(0, "Recovery service is temporarily unavailable.", true);
}

export async function checkHealth(): Promise<boolean> {
  try {
    await request<HealthResponse>("/api/v1/health", undefined, HEALTH_TIMEOUT_MS);
    noteHealthSuccess();
    return true;
  } catch {
    noteHealthFailure();
    return false;
  }
}

export async function retryConnection(): Promise<boolean> {
  healthFailures = 0;
  setConnectionState("RECONNECTING");
  return checkHealth();
}

export const api = {
  baseUrl: API_BASE,
  health: () => request<HealthResponse>("/api/v1/health", undefined, HEALTH_TIMEOUT_MS),
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
    request<BatchSimulateResponse>(
      "/api/v1/payments/simulate-batch",
      {
        method: "POST",
        body: JSON.stringify(body ?? { count: 20, recover: true }),
      },
      60000,
    ),
  runRecoverySimulation: () =>
    request<RunRecoverySimulationResponse>(
      "/api/v1/payments/run-recovery-simulation",
      {
        method: "POST",
      },
      60000,
    ),
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
