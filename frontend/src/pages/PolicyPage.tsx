import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PolicySnapshot, PolicyView } from "../types";

export function PolicyPage() {
  const [policy, setPolicy] = useState<PolicyView | null>(null);
  const [snapshots, setSnapshots] = useState<PolicySnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      const [current, listed] = await Promise.all([api.policy(), api.policySnapshots()]);
      setPolicy(current);
      setSnapshots(listed.snapshots);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Unable to load policy.");
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const rollback = async (version: number) => {
    setBusy(true);
    try {
      await api.rollbackPolicy(version);
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Rollback failed.");
    } finally {
      setBusy(false);
    }
  };

  const retrain = async () => {
    setBusy(true);
    try {
      await api.retrainPolicy();
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Retrain failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <section className="card p-6">
        <p className="section-label">Adaptive policy</p>
        <h1 className="mt-2 text-[28px] font-semibold tracking-tight text-navy">Explainable routing scores</h1>
        <p className="mt-2 max-w-2xl text-[14px] leading-6 text-secondary">
          Scores are rolling success rates from the durable audit trail. Threshold changes are bounded, versioned, and
          reversible.
        </p>
        <div className="mt-4 flex gap-2">
          <button type="button" className="focus-ring rounded-md bg-blue px-3 py-1.5 text-[13px] font-medium text-white" onClick={() => void retrain()} disabled={busy}>
            Retrain now
          </button>
        </div>
        {error && <p className="mt-3 text-[13px] text-danger">{error}</p>}
      </section>

      {policy && (
        <section className="grid gap-4 md:grid-cols-4">
          <article className="card p-5">
            <p className="text-[12px] text-secondary">Max retries</p>
            <p className="mt-2 tabular text-[22px] font-semibold text-navy">{policy.thresholds.max_retries}</p>
          </article>
          <article className="card p-5">
            <p className="text-[12px] text-secondary">Amount limit</p>
            <p className="mt-2 tabular text-[22px] font-semibold text-navy">{policy.thresholds.amount_limit}</p>
          </article>
          <article className="card p-5">
            <p className="text-[12px] text-secondary">Cooldown (s)</p>
            <p className="mt-2 tabular text-[22px] font-semibold text-navy">{policy.thresholds.cooldown_seconds}</p>
          </article>
          <article className="card p-5">
            <p className="text-[12px] text-secondary">Predict-fail threshold</p>
            <p className="mt-2 tabular text-[22px] font-semibold text-navy">{Math.round(policy.thresholds.predict_fail_threshold * 100)}%</p>
          </article>
        </section>
      )}

      {policy && (
        <section className="card p-6">
          <p className="text-[12px] font-medium text-secondary">Last adjustment</p>
          <p className="mt-2 text-[14px] leading-6 text-ink">{policy.last_adjustment || policy.thresholds.rationale}</p>
        </section>
      )}

      <section className="card overflow-hidden">
        <div className="border-b border-[rgba(15,40,50,0.08)] px-5 py-3">
          <p className="text-[13px] font-semibold text-navy">Per-rail success rates</p>
        </div>
        <table className="w-full text-left text-[13px]">
          <thead className="bg-[#F5F8FB] text-secondary">
            <tr>
              <th className="px-5 py-2 font-medium">Error code</th>
              <th className="px-5 py-2 font-medium">Rail</th>
              <th className="px-5 py-2 font-medium">Success rate</th>
              <th className="px-5 py-2 font-medium">Samples</th>
              <th className="px-5 py-2 font-medium">Rationale</th>
            </tr>
          </thead>
          <tbody>
            {(policy?.route_scores || []).map((row) => (
              <tr key={`${row.error_code}-${row.rail}`} className="border-t border-[rgba(15,40,50,0.06)]">
                <td className="px-5 py-2 tabular">{row.error_code}</td>
                <td className="px-5 py-2">{row.rail}</td>
                <td className="px-5 py-2 tabular">{Math.round(row.success_rate * 100)}%</td>
                <td className="px-5 py-2 tabular">{row.samples}</td>
                <td className="px-5 py-2 text-secondary">{row.rationale}</td>
              </tr>
            ))}
            {policy && policy.route_scores.length === 0 && (
              <tr>
                <td className="px-5 py-6 text-secondary" colSpan={5}>
                  No learned scores yet. Retrain after recovery attempts have been recorded.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="card p-6">
        <p className="text-[13px] font-semibold text-navy">Policy snapshots</p>
        <ul className="mt-3 space-y-3">
          {snapshots.map((snap) => (
            <li key={snap.version} className="flex items-start justify-between gap-4 rounded-md border border-[rgba(15,40,50,0.08)] px-4 py-3">
              <div>
                <p className="text-[13px] font-semibold text-navy">
                  v{snap.version} {snap.active ? "· active" : ""}
                </p>
                <p className="mt-1 text-[12px] leading-5 text-secondary">{snap.rationale}</p>
              </div>
              {!snap.active && (
                <button
                  type="button"
                  className="focus-ring shrink-0 rounded-md border border-[rgba(15,40,50,0.12)] px-3 py-1 text-[12px] font-medium text-navy"
                  disabled={busy}
                  onClick={() => void rollback(snap.version)}
                >
                  Rollback
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
