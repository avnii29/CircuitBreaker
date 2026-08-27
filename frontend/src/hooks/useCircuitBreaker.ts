import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  cacheTelemetry,
  checkHealth,
  getConnectionState,
  loadCachedTelemetry,
  noteDataFailure,
  noteDataSuccess,
  retryConnection,
  subscribeConnection,
  type ConnectionState,
} from "../api/client";
import type {
  AuditEvent,
  BatchResult,
  ExecuteRecoveryResponse,
  ExecuteSelectedRouteResponse,
  HealthResponse,
  RoutingPerformanceResponse,
  SimulateCheckoutRequest,
  TelemetryDashboard,
  Transaction,
} from "../types";
import { isActiveRecovery } from "../types";

const RANDOM_BANKS = ["HDFC", "SBI", "ICICI", "AXIS"] as const;
const RANDOM_AMOUNTS = [499, 799, 999, 1499, 1999, 2499, 3999, 4999];
const RANDOM_CUSTOMERS: Record<(typeof RANDOM_BANKS)[number], { name: string; email: string }> = {
  HDFC: { name: "Rahul Sharma", email: "rahul@example.com" },
  SBI: { name: "Priya Mehta", email: "priya@example.com" },
  ICICI: { name: "Arjun Rao", email: "arjun@example.com" },
  AXIS: { name: "Ananya Iyer", email: "ananya@example.com" },
};

export function randomFailurePayload(): SimulateCheckoutRequest {
  const bank = RANDOM_BANKS[Math.floor(Math.random() * RANDOM_BANKS.length)] ?? "HDFC";
  const amount = RANDOM_AMOUNTS[Math.floor(Math.random() * RANDOM_AMOUNTS.length)] ?? 1499;
  const customer = RANDOM_CUSTOMERS[bank];
  return {
    bank,
    amount,
    customer_name: customer.name,
    customer_email: customer.email,
    customer_phone: "9876543210",
    merchant_id: "MERCHANT_001",
  };
}

export function useCircuitBreaker() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [telemetry, setTelemetry] = useState<TelemetryDashboard | null>(() => loadCachedTelemetry());
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState>(() => getConnectionState());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [executeResult, setExecuteResult] = useState<ExecuteRecoveryResponse | null>(null);
  const [routeResult, setRouteResult] = useState<ExecuteSelectedRouteResponse | null>(null);
  const [routing, setRouting] = useState<RoutingPerformanceResponse | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);

  const selected = useMemo(
    () => transactions.find((txn) => txn.transaction_id === selectedId) ?? null,
    [transactions, selectedId],
  );

  const mergeTransactions = useCallback((incoming: Transaction[]) => {
    setTransactions((prev) => {
      const map = new Map(prev.map((txn) => [txn.transaction_id, txn]));
      incoming.forEach((txn) => map.set(txn.transaction_id, txn));
      return Array.from(map.values()).sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [txns, tel, h] = await Promise.all([
        api.listTransactions(),
        api.telemetry(),
        api.health(),
      ]);
      setTransactions((prev) => {
        if (txns.length === 0 && prev.length > 0) return prev;
        return [...txns].sort(
          (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
        );
      });
      setTelemetry(tel);
      cacheTelemetry(tel);
      setHealth(h);
      noteDataSuccess();
      try {
        setRouting(await api.routingPerformance());
      } catch {
        /* optional analytics must not break recovery */
      }
    } catch {
      noteDataFailure();
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => subscribeConnection(setConnection), []);

  useEffect(() => {
    void refresh();
    const dataId = window.setInterval(() => {
      if (getConnectionState() !== "UNAVAILABLE") void refresh();
    }, 5000);
    const healthId = window.setInterval(() => {
      void checkHealth();
    }, 8000);
    return () => {
      window.clearInterval(dataId);
      window.clearInterval(healthId);
    };
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) {
      setAuditEvents([]);
      return;
    }
    let cancelled = false;
    setAuditLoading(true);
    void api
      .auditLog(selectedId)
      .then((events) => {
        if (!cancelled) setAuditEvents(events);
      })
      .catch(() => {
        if (!cancelled) setAuditEvents([]);
      })
      .finally(() => {
        if (!cancelled) setAuditLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, selected?.updated_at, selected?.state]);

  const simulate = useCallback(
    async (body?: SimulateCheckoutRequest, label = "simulate") => {
      setBusy(label);
      setError(null);
      setNotice(null);
      setExecuteResult(null);
      setRouteResult(null);
      try {
        const txn = await api.simulateCheckout(body);
        mergeTransactions([txn]);
        setSelectedId(txn.transaction_id);
        setAuditOpen(true);
        await refresh();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Unable to start this revenue event.");
      } finally {
        setBusy(null);
      }
    },
    [mergeTransactions, refresh],
  );

  const simulateBatch = useCallback(async () => {
    setBusy("batch");
    setError(null);
    setNotice(null);
    try {
      const result = await api.simulateBatch({ count: 20, recover: true });
      mergeTransactions(result.transactions);
      if (result.transactions[0]) {
        setSelectedId(result.transactions[0].transaction_id);
        setAuditOpen(true);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to start the batch simulation.");
    } finally {
      setBusy(null);
    }
  }, [mergeTransactions, refresh]);

  const selectRoute = useCallback(async (transactionId: string) => {
    setBusy(`select:${transactionId}`);
    setError(null);
    setNotice(null);
    try {
      const result = await api.selectRecoveryRoute(transactionId);
      mergeTransactions([result.transaction]);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Route evaluation could not be completed.");
    } finally {
      setBusy(null);
    }
  }, [mergeTransactions, refresh]);

  const executeSelectedRoute = useCallback(async (transactionId: string) => {
    setBusy(`execute-route:${transactionId}`);
    setError(null);
    setNotice(null);
    try {
      const result = await api.executeSelectedRoute(transactionId);
      setRouteResult(result);
      mergeTransactions([result.transaction]);
      if (result.blocked || result.outcome === "FAILED" || result.outcome === "ESCALATED") {
        setNotice(result.reason ?? "Simulated route execution completed.");
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulated route execution could not be completed.");
    } finally {
      setBusy(null);
    }
  }, [mergeTransactions, refresh]);

  const executeRecovery = useCallback(async (transactionId: string) => {
    setBusy(`recover:${transactionId}`);
    setError(null);
    setNotice(null);
    try {
      const result = await api.executeRecovery(transactionId);
      setExecuteResult(result);
      mergeTransactions([result.transaction]);
      if (result.blocked) {
        setNotice(result.reason ?? "Recovery action could not be completed.");
      }
      await refresh();
    } catch {
      setError("Recovery action could not be completed.");
    } finally {
      setBusy(null);
    }
  }, [mergeTransactions, refresh]);

  const runRecoverySimulation = useCallback(async () => {
    setBusy("demo-recovery");
    setError(null);
    setNotice(null);
    try {
      await api.runRecoverySimulation();
      await refresh();
      window.setTimeout(() => void refresh(), 1200);
      window.setTimeout(() => void refresh(), 2800);
      window.setTimeout(() => void refresh(), 5000);
      window.setTimeout(() => void refresh(), 8000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Recovery action could not be completed.");
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  const startLiveDemo = useCallback(async () => {
    setBusy("live-demo");
    setError(null);
    setNotice(null);
    try {
      await api.resetDemo();
      setTransactions([]);
      setSelectedId(null);
      const result = await api.simulateBatch({ count: 20, recover: true });
      mergeTransactions(result.transactions);
      if (result.transactions[0]) {
        setSelectedId(result.transactions[0].transaction_id);
        setAuditOpen(true);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to start the live demo.");
    } finally {
      setBusy(null);
    }
  }, [mergeTransactions, refresh]);

  const reconnect = useCallback(async () => {
    setBusy("reconnect");
    const ok = await retryConnection();
    if (ok) await refresh();
    setBusy(null);
  }, [refresh]);

  const resetDemo = useCallback(async () => {
    setBusy("reset");
    setError(null);
    try {
      await api.resetDemo();
      setTransactions([]);
      setSelectedId(null);
      setExecuteResult(null);
      setRouteResult(null);
      setNotice(null);
      setAuditEvents([]);
      setAuditOpen(false);
      setConfirmReset(false);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to reset the demo.");
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  const heldCarts = useMemo(
    () => transactions.filter((txn) => isActiveRecovery(txn.state) && txn.cart_status === "HELD"),
    [transactions],
  );

  const lastBatch: BatchResult | null = telemetry?.last_batch ?? null;

  return {
    transactions,
    telemetry,
    health,
    selected,
    selectedId,
    setSelectedId,
    connection,
    offline: connection === "UNAVAILABLE",
    loading,
    busy,
    error,
    notice,
    executeResult,
    routeResult,
    routing,
    heldCarts,
    lastBatch,
    confirmReset,
    setConfirmReset,
    auditEvents,
    auditLoading,
    auditOpen,
    setAuditOpen,
    simulate,
    simulateBatch,
    startLiveDemo,
    reconnect,
    executeRecovery,
    selectRoute,
    executeSelectedRoute,
    runRecoverySimulation,
    resetDemo,
    refresh,
  };
}

export type CircuitBreakerState = ReturnType<typeof useCircuitBreaker>;
