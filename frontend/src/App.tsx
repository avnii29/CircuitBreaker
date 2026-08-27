import { useEffect, useState } from "react";
import { DemoBanner, TopNav } from "./components/TopNav";
import { OverviewPage } from "./pages/OverviewPage";
import { RecoveryPage } from "./pages/RecoveryPage";
import { TransactionsPage } from "./pages/TransactionsPage";
import { useCircuitBreaker } from "./hooks/useCircuitBreaker";
import type { PageId } from "./types";
import { setTenantHeader } from "./api/client";

export default function App() {
  const state = useCircuitBreaker();
  const [page, setPage] = useState<PageId>("overview");
  const [tenantId, setTenantId] = useState("");
  const tenants: string[] = [];

  useEffect(() => {
    setTenantHeader(tenantId);
    void state.refresh();
    // Tenant header is module state; refresh reloads scoped lists.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  const openRecovery = () => setPage("recovery");

  return (
    <div className="min-h-screen bg-page">
      <TopNav
        page={page}
        onPage={setPage}
        connection={state.connection}
        onRetry={() => void state.reconnect()}
        tenants={tenants}
        tenantId={tenantId}
        onTenant={setTenantId}
      />
      <DemoBanner
        demoMode={state.telemetry?.demo_mode ?? state.health?.demo_mode ?? true}
        windowSeconds={state.telemetry?.recovery_window_seconds ?? state.health?.recovery_window_seconds ?? 30}
      />
      <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
        {page === "overview" && (
          <OverviewPage
            state={state}
            onOpenRecovery={openRecovery}
            onOpenTransactions={() => setPage("transactions")}
          />
        )}
        {page === "recovery" && <RecoveryPage state={state} />}
        {page === "transactions" && (
          <TransactionsPage state={state} onOpenRecovery={openRecovery} />
        )}
      </main>
    </div>
  );
}
