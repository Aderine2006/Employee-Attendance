"""Readiness and system endpoints."""
from fastapi import APIRouter, HTTPException, status

from app.db.mongo import db

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    try:
        db.command("ping")
    except Exception as exc:  # pragma: no cover - runtime safeguard
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MongoDB unavailable") from exc
    return {"status": "ok"}
