import { useEffect, useState } from "react";
import { TopNav } from "./components/TopNav";
import { OverviewPage } from "./pages/OverviewPage";
import { RecoveryPage } from "./pages/RecoveryPage";
import { TransactionsPage } from "./pages/TransactionsPage";
import { useCircuitBreaker } from "./hooks/useCircuitBreaker";
import type { PageId } from "./types";
import { api, setTenantHeader } from "./api/client";

export default function App() {
  const state = useCircuitBreaker();
  const [page, setPage] = useState<PageId>("overview");
  const [tenants, setTenants] = useState<string[]>([]);
  const [tenantId, setTenantId] = useState("");

  useEffect(() => {
    void api
      .tenants()
      .then((payload) => setTenants(payload.tenants))
      .catch(() => setTenants([]));
  }, []);

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
        offline={state.offline}
        tenants={tenants}
        tenantId={tenantId}
        onTenant={setTenantId}
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
