"""Attendance, punch, and regularization endpoints."""
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pymongo.errors import DuplicateKeyError

from app.core.time import (
    attendance_date_for_instant,
    compute_late_minutes,
    dt_from_epoch,
    ensure_utc,
    epoch_ms,
    recompute_derived_fields,
    truncate_seconds,
)
from app.db.mongo import db
from app.models.schemas import PunchInRequest, PunchOutRequest, RegularizeRequest
from app.services.attendance import fetch_employee_or_404, record_version_filter, validate_calendar_date
from app.services.serialization import serialize_attendance

router = APIRouter(tags=["attendance"])


@router.post("/attendance/punch-in", status_code=status.HTTP_201_CREATED)
def punch_in(payload: PunchInRequest):
    employee = fetch_employee_or_404(payload.emp_code)
    punched_dt = dt_from_epoch(payload.punched_at or int(datetime.now(timezone.utc).timestamp() * 1000))
    punched_dt = truncate_seconds(punched_dt)
    record_date = attendance_date_for_instant(employee, punched_dt)
    doc = {
        "emp_code": employee["emp_code"],
        "date": record_date,
        "status": payload.status,
        "punch_in": punched_dt,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(punched_dt, employee["shift_start"], employee["shift_end"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
        "version": 0,
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "attendance record already exists for this employee and date") from exc
    return serialize_attendance(doc)


@router.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    attendance_status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q: dict[str, Any] = {}
    if emp_code is not None:
        q["emp_code"] = emp_code
    if date_from is not None:
        validate_calendar_date(date_from, "date_from")
    if date_to is not None:
        validate_calendar_date(date_to, "date_to")
    if date_from or date_to:
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date_from cannot be after date_to")
        if date_from or date_to:
            q["date"] = {}
            if date_from:
                q["date"]["$gte"] = date_from
            if date_to:
                q["date"]["$lte"] = date_to
    if attendance_status is not None:
        q["status"] = attendance_status
    total = db.attendance_logs.count_documents(q)
    docs = list(db.attendance_logs.find(q).sort([("date", -1), ("emp_code", 1)]).skip((page - 1) * page_size).limit(page_size))
    return {"items": [serialize_attendance(doc) for doc in docs], "total": total, "page": page, "page_size": page_size}


@router.post("/attendance/punch-out")
def punch_out(payload: PunchOutRequest):
    employee = fetch_employee_or_404(payload.emp_code)
    punched_dt = ensure_utc(dt_from_epoch(payload.punched_at or int(datetime.now(timezone.utc).timestamp() * 1000)))
    punched_dt = truncate_seconds(punched_dt)
    record = db.attendance_logs.find_one(
        {"emp_code": employee["emp_code"], "punch_in": {"$lte": punched_dt}},
        sort=[("date", -1)],
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no punch-in found")
    if record.get("punch_out") is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "record already punched out")
    record_date = record["date"]
    record_punch_in = ensure_utc(record.get("punch_in"))
    if record_punch_in is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "record is not open for punch-out")
    if punched_dt <= record_punch_in:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "punch_out must be after punch_in")
    if punched_dt - record_punch_in > timedelta(hours=24):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "punch_out cannot be more than 24 hours after punch_in")
    current_version = int(record.get("version", 0))
    updated = dict(record)
    updated["punch_out"] = punched_dt
    updated = recompute_derived_fields(updated, employee)
    version_filter = record_version_filter(record, current_version)
    res = db.attendance_logs.update_one(
        {
            "emp_code": employee["emp_code"],
            "date": record_date,
            "punch_out": None,
            **version_filter,
        },
        {"$set": {"punch_in": updated.get("punch_in"), "punch_out": punched_dt, "work_hours": updated.get("work_hours"), "late_minutes": updated.get("late_minutes"), "overtime_minutes": updated.get("overtime_minutes"), "half_day": updated.get("half_day"), "version": current_version + 1}},
    )
    if res.matched_count == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "record already updated by another request")
    updated["version"] = current_version + 1
    return serialize_attendance(updated)


@router.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, payload: RegularizeRequest):
    validate_calendar_date(date, "date")
    employee = fetch_employee_or_404(emp_code)
    record = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "attendance record not found")
    current_version = int(record.get("version", 0))
    new_status = payload.status if payload.status is not None else record["status"]
    new_punch_in = ensure_utc(record.get("punch_in"))
    new_punch_out = ensure_utc(record.get("punch_out"))
    if payload.punch_in is not None:
        new_punch_in = truncate_seconds(dt_from_epoch(payload.punch_in))
    if payload.punch_out is not None:
        new_punch_out = truncate_seconds(dt_from_epoch(payload.punch_out))

    if new_status in {"ABSENT", "LEAVE"}:
        if payload.punch_in is not None or payload.punch_out is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ABSENT/LEAVE records cannot provide punch times")
        new_punch_in = None
        new_punch_out = None
    else:
        if payload.punch_in is not None and not (attendance_date_for_instant(employee, new_punch_in) == date):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "punch_in must remain on the attendance date")
        if new_punch_in is None and new_punch_out is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "presence status requires a punch_in")
        if new_punch_in is not None and new_punch_out is not None and new_punch_out <= new_punch_in:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "punch_out must be after punch_in")
        if new_punch_in is not None and new_punch_out is not None and new_punch_out - new_punch_in > timedelta(hours=24):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "punch_out cannot be more than 24 hours after punch_in")

    updated = dict(record)
    updated["status"] = new_status
    updated["punch_in"] = new_punch_in
    updated["punch_out"] = new_punch_out
    updated = recompute_derived_fields(updated, employee)

    changes: dict[str, dict[str, Any]] = {}
    for field in ["status", "punch_in", "punch_out", "work_hours", "late_minutes", "overtime_minutes", "half_day"]:
        old_value = record.get(field)
        new_value = updated.get(field)
        if field in {"punch_in", "punch_out"}:
            old_compare = epoch_ms(old_value)
            new_compare = epoch_ms(new_value)
        else:
            old_compare = old_value
            new_compare = new_value
        if old_compare != new_compare:
            changes[field] = {"from": old_value, "to": new_value}
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "request changes nothing")

    history_entry = {
        "at": datetime.now(timezone.utc),
        "by": payload.regularized_by,
        "reason": payload.reason,
        "changes": changes,
    }
    updated["history"] = list(record.get("history", [])) + [history_entry]
    res = db.attendance_logs.update_one(
        {
            "emp_code": emp_code,
            "date": date,
            **record_version_filter(record, current_version),
        },
        {
            "$set": {
                "status": updated["status"],
                "punch_in": updated["punch_in"],
                "punch_out": updated["punch_out"],
                "work_hours": updated["work_hours"],
                "late_minutes": updated["late_minutes"],
                "overtime_minutes": updated["overtime_minutes"],
                "half_day": updated["half_day"],
                "history": updated["history"],
                "version": current_version + 1,
            }
        },
    )
    if res.matched_count == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "optimistic concurrency conflict: record changed concurrently")
    updated["version"] = current_version + 1
    return serialize_attendance(updated)
