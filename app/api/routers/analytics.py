"""Employee and department analytics endpoints."""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.time import parse_ymd, round_half_up
from app.db.mongo import db
from app.services.analytics import (
    department_summary_pipeline,
    department_trend_pipeline,
    late_leaderboard_pipeline,
)
from app.services.attendance import fetch_employee_or_404, month_bounds, month_user_summary

router = APIRouter(tags=["analytics"])


@router.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    employee = fetch_employee_or_404(emp_code)
    return month_user_summary(employee, month)


@router.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = Query(default=None),
):
    start_str, end_str = month_bounds(month)
    rows = list(db.employees.aggregate(department_summary_pipeline(start_str, end_str, department)))
    for row in rows:
        row["present_days"] = round_half_up(float(row["present_days"]), 2)
        if row["avg_work_hours"] is not None:
            row["avg_work_hours"] = round_half_up(float(row["avg_work_hours"]), 2)
    return {"month": month, "items": rows}


@router.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(default=10, ge=1, le=50),
    department: Optional[str] = Query(default=None),
):
    start_str, end_str = month_bounds(month)
    pipeline = late_leaderboard_pipeline(start_str, end_str, limit, department)
    return {"month": month, "items": list(db.attendance_logs.aggregate(pipeline))}


@router.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    try:
        from_dt = parse_ymd(from_date)
        to_dt = parse_ymd(to_date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "from/to must be YYYY-MM-DD") from exc
    if to_dt < from_dt:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "to must be on or after from")
    if (to_dt - from_dt).days + 1 > 92:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "range exceeds 92 days")
    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "department not found")
    pipeline = department_trend_pipeline(department, from_date, to_date)
    items = list(db.aggregate(pipeline))
    for item in items:
        item["present_count"] = float(item["present_count"])
        if item["attendance_rate"] is not None:
            item["attendance_rate"] = float(item["attendance_rate"])
        if item["moving_avg_7d"] is not None:
            item["moving_avg_7d"] = float(item["moving_avg_7d"])
    return {"department": department, "items": items}
