"""Attendance persistence helpers and employee-month calculations."""
import re
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import HTTPException, status

from app.core.time import parse_ymd, round_half_up
from app.db.mongo import db

def fetch_employee_or_404(emp_code: str) -> dict[str, Any]:
    employee = db.employees.find_one({"emp_code": emp_code})
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "employee not found")
    return employee


def record_version_filter(record: dict[str, Any], version: int) -> dict[str, Any]:
    if "version" in record:
        return {"version": version}
    return {"version": {"$exists": False}}


def validate_calendar_date(value: str, field_name: str) -> str:
    try:
        parse_ymd(value)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{field_name} must be YYYY-MM-DD",
        ) from exc
    return value


def month_bounds(month: str) -> tuple[str, str]:
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month must be YYYY-MM")
    try:
        year, month_num = map(int, month.split("-"))
        month_date = date(year, month_num, 1)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month must be YYYY-MM") from exc
    next_month = (month_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    return month_date.isoformat(), next_month.isoformat()


def working_days_in_month(joined_on: str, month: str) -> int:
    start_str, end_str = month_bounds(month)
    month_start = parse_ymd(start_str)
    month_end = parse_ymd(end_str) - timedelta(days=1)
    join_date = parse_ymd(joined_on)
    count = 0
    current = max(month_start, join_date)
    while current <= month_end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def employee_monthly_pipeline(emp_code: str, start_str: str, end_str: str) -> list[dict[str, Any]]:
    present_status = {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]}
    weekday = {"$lte": [{"$isoDayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, 5]}
    return [
        {"$match": {"emp_code": emp_code, "date": {"$gte": start_str, "$lt": end_str}}},
        {"$group": {
            "_id": None,
            "present_days": {"$sum": {"$cond": [{"$and": [present_status, weekday]}, {"$cond": ["$half_day", 0.5, 1.0]}, 0]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}},
        }},
    ]


def month_user_summary(employee: dict[str, Any], month: str) -> dict[str, Any]:
    emp_code = employee["emp_code"]
    start_str, end_str = month_bounds(month)
    working_days = working_days_in_month(employee["joined_on"], month)
    aggregate = list(db.attendance_logs.aggregate(employee_monthly_pipeline(emp_code, start_str, end_str)))
    totals = aggregate[0] if aggregate else {}
    present_days = float(totals.get("present_days", 0.0))
    attendance_pct = None if working_days == 0 else round_half_up((present_days / working_days) * 100, 2)
    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": totals.get("leave_days", 0),
        "late_count": totals.get("late_count", 0),
        "total_late_minutes": totals.get("total_late_minutes", 0),
        "total_overtime_minutes": totals.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct,
    }
