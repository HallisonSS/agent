import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import audit, fetch_one, jsonb
from app.redis_client import get_redis
from app.security.auth import require_key
from app.tools import executor

router = APIRouter(tags=["events"], dependencies=[Depends(require_key)])


class Alert(BaseModel):
    status: str | None = None
    labels: dict = Field(default_factory=dict)
    annotations: dict = Field(default_factory=dict)
    startsAt: str | None = None
    endsAt: str | None = None
    fingerprint: str | None = None


class AlertmanagerWebhook(BaseModel):
    version: str | None = None
    groupKey: str | None = None
    status: str | None = None
    receiver: str | None = None
    groupLabels: dict = Field(default_factory=dict)
    commonLabels: dict = Field(default_factory=dict)
    commonAnnotations: dict = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[Alert] = Field(default_factory=list)


class ActionRequest(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)
    requested_by: str | None = "api"
    reason: str | None = None


@router.post("/alerts")
async def alerts(payload: AlertmanagerWebhook):
    s = get_settings()
    r = get_redis()
    for a in payload.alerts:
        await r.xadd(
            s.alerts_stream,
            {
                "status": a.status or payload.status or "",
                "labels": json.dumps(a.labels, ensure_ascii=False),
                "annotations": json.dumps(a.annotations, ensure_ascii=False),
                "startsAt": a.startsAt or "",
                "fingerprint": a.fingerprint or "",
            },
            maxlen=s.stream_maxlen,
            approximate=True,
        )
    return {"ok": True, "queued": len(payload.alerts)}


@router.post("/actions")
async def actions(req: ActionRequest):
    s = get_settings()
    try:
        spec = executor.validate(req.action, req.params)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    who = req.requested_by or "api"
    if spec.requires_approval:
        row = await fetch_one(
            "INSERT INTO approvals (requested_by, action, params, reason) VALUES (%s, %s, %s, %s) RETURNING id",
            (who, req.action, jsonb(req.params), req.reason),
        )
        await audit(who, "approval_requested", str(row["id"]), {"action": req.action, "params": req.params})  # type: ignore[index]
        return {"queued": False, "approval_id": row["id"], "status": "pending"}  # type: ignore[index]
    await get_redis().xadd(
        s.actions_stream,
        {"action": req.action, "params": json.dumps(req.params, ensure_ascii=False), "requested_by": who},
        maxlen=s.stream_maxlen,
        approximate=True,
    )
    await audit(who, "action_queued", req.action, {"params": req.params})
    return {"queued": True}
