"""Translate MongoDB records into stable API response shapes."""
from typing import Any

from app.core.time import epoch_ms

def to_response_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in history or []:
        changes = {}
        for field, payload in item.get("changes", {}).items():
            if field in {"punch_in", "punch_out"}:
                changes[field] = {
                    "from": epoch_ms(payload.get("from")) if payload.get("from") is not None else None,
                    "to": epoch_ms(payload.get("to")) if payload.get("to") is not None else None,
                }
            else:
                changes[field] = {"from": payload.get("from"), "to": payload.get("to")}
        out.append({
            "at": epoch_ms(item.get("at")),
            "by": item.get("by"),
            "reason": item.get("reason"),
            "changes": changes,
        })
    return out


def serialize_attendance(record: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "emp_code": record.get("emp_code"),
        "date": record.get("date"),
        "status": record.get("status"),
        "punch_in": epoch_ms(record.get("punch_in")),
        "punch_out": epoch_ms(record.get("punch_out")),
        "work_hours": record.get("work_hours"),
        "late_minutes": record.get("late_minutes", 0),
        "overtime_minutes": record.get("overtime_minutes", 0),
        "half_day": bool(record.get("half_day", False)),
        "history": to_response_history(record.get("history", [])),
    }
    return payload


def serialize_employee(employee: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "emp_code": employee.get("emp_code"),
        "name": employee.get("name"),
        "email": employee.get("email"),
        "department": employee.get("department"),
        "shift_start": employee.get("shift_start"),
        "shift_end": employee.get("shift_end"),
        "joined_on": employee.get("joined_on"),
        "created_at": epoch_ms(employee.get("created_at")),
    }
    return payload
