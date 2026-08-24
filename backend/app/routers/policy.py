from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.engine.jobs import PRIORITY_ANALYTICS, enqueue
from app.engine.policy import current_policy, list_snapshots, retrain, rollback_to, save_thresholds
from app.security.auth import require_ops, require_read, require_write
from app.tenancy import list_known_tenants, write_tenant_id

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/policy")
async def get_policy() -> dict:
    return await current_policy()


@router.get("/policy/snapshots")
async def get_snapshots() -> dict:
    return {"snapshots": await list_snapshots()}


@router.post("/policy/retrain", dependencies=[Depends(require_write)])
async def trigger_retrain() -> dict:
    snapshot = await retrain(write_tenant_id())
    return {"ok": True, "snapshot": snapshot}


@router.post("/policy/rollback/{version}", dependencies=[Depends(require_write)])
async def rollback_policy(version: int) -> dict:
    try:
        snapshot = await rollback_to(version)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy snapshot not found.")
    return {"ok": True, "snapshot": snapshot}


@router.post("/policy/thresholds", dependencies=[Depends(require_write)])
async def override_thresholds(body: dict) -> dict:
    tenant = write_tenant_id()
    current = await current_policy(tenant)
    values = dict(current["thresholds"])
    for key in ("max_retries", "amount_limit", "cooldown_seconds", "predict_fail_threshold"):
        if key in body:
            values[key] = body[key]
    rationale = str(body.get("rationale") or "Human override of adaptive thresholds.")
    snapshot = await save_thresholds(tenant, values, rationale)
    return {"ok": True, "snapshot": snapshot}


@router.post("/policy/enqueue-retrain", dependencies=[Depends(require_write)])
async def enqueue_retrain() -> dict:
    job = await enqueue("retrain", write_tenant_id(), {}, priority=PRIORITY_ANALYTICS)
    return {"ok": True, "job_id": job.id}


@router.get("/tenants", dependencies=[Depends(require_ops)])
async def tenants() -> dict:
    return {"tenants": list_known_tenants()}
