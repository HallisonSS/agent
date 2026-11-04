import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.db import audit, fetch_all, fetch_one
from app.redis_client import get_redis
from app.security.auth import require_key

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_key)])


class Decision(BaseModel):
    approval_id: int
    approve: bool
    decided_by: str


@router.get("/approvals")
async def list_approvals(status: str = "pending", limit: int = 50):
    return await fetch_all(
        """SELECT id, requested_by, action, params, reason, status, decided_by, decided_at, created_at
           FROM approvals WHERE status = %s ORDER BY id DESC LIMIT %s""",
        (status, min(limit, 200)),
    )


@router.post("/approvals/decide")
async def decide(d: Decision):
    s = get_settings()
    new_status = "approved" if d.approve else "rejected"
    row = await fetch_one(
        """UPDATE approvals SET status = %s, decided_by = %s, decided_at = now()
           WHERE id = %s AND status = 'pending' RETURNING action, params""",
        (new_status, d.decided_by, d.approval_id),
    )
    if not row:
        exists = await fetch_one("SELECT status FROM approvals WHERE id = %s", (d.approval_id,))
        if not exists:
            raise HTTPException(404, "not found")
        raise HTTPException(409, f"já decidida: {exists['status']}")
    if d.approve:
        await get_redis().xadd(
            s.actions_stream,
            {
                "action": row["action"],
                "params": json.dumps(row["params"], ensure_ascii=False),
                "requested_by": d.decided_by,
                "approval_id": str(d.approval_id),
            },
            maxlen=s.stream_maxlen,
            approximate=True,
        )
    await audit(d.decided_by, f"approval_{new_status}", str(d.approval_id), {"action": row["action"]})
    return {"updated": True, "status": new_status}
