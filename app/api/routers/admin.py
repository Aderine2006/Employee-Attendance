"""Administrative query explain endpoint."""
from datetime import timedelta
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.time import parse_ymd
from app.db.mongo import db
from app.services.analytics import department_summary_pipeline, department_trend_pipeline, explain_aggregation, late_leaderboard_pipeline
from app.services.attendance import employee_monthly_pipeline, month_bounds, validate_calendar_date

router = APIRouter(tags=["admin"])

@router.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = Query(default=None),
    month: Optional[str] = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1, le=50),
    date_from: Optional[str] = Query(default=None, alias="date_from"),
    date_to: Optional[str] = Query(default=None, alias="date_to"),
    attendance_status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = Query(default=None, alias="status"),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    allowed = {"attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"}
    if endpoint not in allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown endpoint")
    collection = "attendance_logs"
    if endpoint == "attendance_list":
        query = {}
        if emp_code is not None:
            query["emp_code"] = emp_code
        if date_from is not None:
            validate_calendar_date(date_from, "date_from")
        if date_to is not None:
            validate_calendar_date(date_to, "date_to")
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date_from cannot be after date_to")
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to
        if attendance_status is not None:
            query["status"] = attendance_status
        explain_doc = db.attendance_logs.find(query).sort([("date", -1), ("emp_code", 1)]).skip((page - 1) * page_size).limit(page_size).explain("executionStats")
    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "emp_code and month are required")
        start_str, end_str = month_bounds(month)
        pipeline = employee_monthly_pipeline(emp_code, start_str, end_str)
        explain_doc = explain_aggregation("attendance_logs", pipeline)
    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month is required")
        start_str, end_str = month_bounds(month)
        pipeline = department_summary_pipeline(start_str, end_str, department)
        explain_doc = explain_aggregation("employees", pipeline)
        collection = "employees"
    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month is required")
        start_str, end_str = month_bounds(month)
        pipeline = late_leaderboard_pipeline(start_str, end_str, limit or 10, department)
        explain_doc = explain_aggregation("attendance_logs", pipeline)
    elif endpoint == "department_trend":
        if not department or not from_date or not to_date:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "department, from and to are required")
        validate_calendar_date(from_date, "from")
        validate_calendar_date(to_date, "to")
        from_dt, to_dt = parse_ymd(from_date), parse_ymd(to_date)
        if to_dt < from_dt or (to_dt - from_dt).days + 1 > 92:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid department trend range")
        pipeline = department_trend_pipeline(department, from_date, to_date)
        explain_doc = explain_aggregation(1, pipeline)
        collection = "database"
    return {"endpoint": endpoint, "collection": collection, "explain": explain_doc}
