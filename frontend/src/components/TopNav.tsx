import type { PageId } from "../types";
import { BrandName, CircuitMark } from "./StatusPill";
import { cx } from "../lib/format";

const LINKS: { id: PageId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "recovery", label: "Recovery" },
  { id: "transactions", label: "Transactions" },
];

export function DemoBanner({
  demoMode,
  windowSeconds,
}: {
  demoMode: boolean;
  windowSeconds: number;
}) {
  return (
    <div className="border-b border-[rgba(15,40,50,0.08)] bg-[#EEF2F6]">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-2 px-6 py-2 text-[12px] text-secondary lg:px-10">
        <p>
          <span className="font-semibold tracking-[0.12em] text-navy">DEMO ENVIRONMENT</span>
          <span className="mx-2 text-muted">·</span>
          Simulated bank failures · No real payments processed
        </p>
        {demoMode && (
          <p className="font-medium text-navy">
            DEMO MODE · Recovery window compressed to {windowSeconds}s
          </p>
        )}
      </div>
    </div>
  );
}

export function TopNav({
  page,
  onPage,
  offline,
  tenants,
  tenantId,
  onTenant,
}: {
  page: PageId;
  onPage: (page: PageId) => void;
  offline: boolean;
  tenants: string[];
  tenantId: string;
  onTenant: (tenantId: string) => void;
}) {
  return (
    <header className="sticky top-0 z-30 h-16 border-b border-[rgba(15,40,50,0.08)] bg-white">
      <div className="mx-auto flex h-full max-w-[1440px] items-center justify-between gap-6 px-6 lg:px-10">
        <div className="flex min-w-0 items-center gap-3">
          <CircuitMark className="h-10 w-10 shrink-0 object-contain" />
          <BrandName className="text-[15px] font-semibold tracking-tight text-navy" />
        </div>

        <nav className="hidden items-center gap-1 md:flex">
          {LINKS.map((link) => (
            <button
              key={link.id}
              type="button"
              onClick={() => onPage(link.id)}
              className={cx(
                "focus-ring rounded-md px-3 py-1.5 text-[14px] transition-colors duration-150",
                page === link.id
                  ? "font-semibold text-navy"
                  : "text-secondary hover:text-ink",
              )}
            >
              {link.label}
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-3 text-[12px]">
          {tenants.length > 0 && (
            <label className="hidden items-center gap-2 text-secondary lg:flex">
              Tenant
              <select
                className="rounded-md border border-[rgba(15,40,50,0.12)] bg-white px-2 py-1 text-[12px] text-navy"
                value={tenantId}
                onChange={(event) => onTenant(event.target.value)}
              >
                <option value="">All tenants</option>
                {tenants.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
          )}
          {offline ? (
            <span className="inline-flex items-center gap-1.5 font-medium text-danger">
              <span className="h-1.5 w-1.5 rounded-full bg-danger" />
              BACKEND OFFLINE
            </span>
          ) : null}
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#EEF2F6] text-[11px] font-semibold text-navy">
            CB
          </span>
        </div>
      </div>
      <div className="flex gap-1 overflow-x-auto border-t border-[rgba(15,40,50,0.06)] px-4 py-2 md:hidden">
        {LINKS.map((link) => (
          <button
            key={link.id}
            type="button"
            onClick={() => onPage(link.id)}
            className={cx(
              "whitespace-nowrap rounded-md px-3 py-1 text-[13px]",
              page === link.id ? "bg-[#EEF2FF] font-semibold text-blue" : "text-secondary",
            )}
          >
            {link.label}
          </button>
        ))}
      </div>
    </header>
  );
}
