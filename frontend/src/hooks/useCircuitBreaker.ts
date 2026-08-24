import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
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
  const [telemetry, setTelemetry] = useState<TelemetryDashboard | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
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
      setTransactions(
        [...txns].sort(
          (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
        ),
      );
      setTelemetry(tel);
      setHealth(h);
      setOffline(false);
      try {
        setRouting(await api.routingPerformance());
      } catch {
        /* telemetry polling remains the source of truth if routing feed lags */
      }
    } catch {
      setOffline(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => {
      void refresh();
    }, 2500);
    return () => window.clearInterval(id);
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
      } catch {
        setError("Recovery engine unavailable. Unable to start simulation.");
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
      const result = await api.simulateBatch({ count: 50 });
      mergeTransactions(result.transactions);
      if (result.transactions[0]) {
        setSelectedId(result.transactions[0].transaction_id);
        setAuditOpen(true);
      }
      await refresh();
    } catch {
      setError("Recovery engine unavailable. Unable to start simulation.");
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
    } catch {
      setError("Recovery engine unavailable. Unable to start simulation.");
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
    offline,
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
    executeRecovery,
    selectRoute,
    executeSelectedRoute,
    runRecoverySimulation,
    resetDemo,
    refresh,
  };
}

export type CircuitBreakerState = ReturnType<typeof useCircuitBreaker>;
