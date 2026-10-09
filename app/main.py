"""FastAPI application factory and stable Uvicorn entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers import admin, analytics, attendance, employees, system
from app.core.config import MONGO_DB, MONGO_URI
from app.core.time import (
    IST, PRESENCE_STATUSES, attendance_date_for_instant, compute_late_minutes,
    compute_work_hours, dt_from_epoch, ensure_utc, epoch_ms, is_overnight,
    iso_ist, minutes_of_day, parse_hhmm, parse_ymd, recompute_derived_fields,
    round_half_up, shift_end_dt_for_record, shift_start_dt_for_emp, truncate_seconds,
)
from app.db.mongo import client, db, ensure_indexes, set_database
from app.models.schemas import EmployeeCreate, PunchInRequest, PunchOutRequest, RegularizeRequest
from app.services.analytics import (
    department_summary_pipeline, department_trend_pipeline, explain_aggregation,
    late_leaderboard_pipeline, mongo_round_half_up,
)
from app.services.attendance import (
    employee_monthly_pipeline, fetch_employee_or_404, month_bounds,
    month_user_summary, record_version_filter, validate_calendar_date,
    working_days_in_month,
)
from app.services.serialization import serialize_attendance, serialize_employee, to_response_history


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_indexes()
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0", lifespan=lifespan)
    application.include_router(system.router)
    application.include_router(employees.router)
    application.include_router(attendance.router)
    application.include_router(analytics.router)
    application.include_router(admin.router)
    return application


app = create_app()
