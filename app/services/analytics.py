"""MongoDB aggregation builders and explain support."""
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

from app.core.time import parse_ymd
from app.db.mongo import db


def department_summary_pipeline(start_str: str, end_str: str, department: Optional[str] = None) -> list[dict[str, Any]]:
    employee_match: dict[str, Any] = {"joined_on": {"$lt": end_str}}
    if department is not None:
        employee_match["department"] = department
    presence_status = {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]}
    weekday = {"$lte": [{"$isoDayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, 5]}
    has_work_hours = {"$ne": [{"$ifNull": ["$work_hours", None]}, None]}
    empty_metrics = {
        "present_days": 0,
        "late_count": 0,
        "total_late_minutes": 0,
        "leave_count": 0,
        "on_duty_count": 0,
        "work_hours_total": 0,
        "work_hours_count": 0,
    }
    return [
        {"$match": employee_match},
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"employee_code": "$emp_code"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$emp_code", "$$employee_code"]},
                    {"$gte": ["$date", start_str]},
                    {"$lt": ["$date", end_str]},
                ]}}},
                {"$group": {
                    "_id": None,
                    "present_days": {"$sum": {"$cond": [{"$and": [presence_status, weekday]}, {"$cond": ["$half_day", 0.5, 1.0]}, 0]}},
                    "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
                    "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
                    "leave_count": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
                    "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]}},
                    "work_hours_total": {"$sum": {"$cond": [{"$and": [presence_status, has_work_hours]}, "$work_hours", 0]}},
                    "work_hours_count": {"$sum": {"$cond": [{"$and": [presence_status, has_work_hours]}, 1, 0]}},
                }},
            ],
            "as": "log_metrics",
        }},
        {"$set": {"metrics": {"$ifNull": [{"$arrayElemAt": ["$log_metrics", 0]}, empty_metrics]}}},
        {"$group": {
            "_id": "$department",
            "headcount": {"$sum": 1},
            "present_days": {"$sum": "$metrics.present_days"},
            "late_count": {"$sum": "$metrics.late_count"},
            "total_late_minutes": {"$sum": "$metrics.total_late_minutes"},
            "leave_count": {"$sum": "$metrics.leave_count"},
            "on_duty_count": {"$sum": "$metrics.on_duty_count"},
            "work_hours_total": {"$sum": "$metrics.work_hours_total"},
            "work_hours_count": {"$sum": "$metrics.work_hours_count"},
        }},
        {"$project": {
            "_id": 0,
            "department": "$_id",
            "headcount": 1,
            "present_days": 1,
            "late_count": 1,
            "total_late_minutes": 1,
            "leave_count": 1,
            "on_duty_count": 1,
            "avg_work_hours": {"$cond": [
                {"$gt": ["$work_hours_count", 0]},
                {"$divide": ["$work_hours_total", "$work_hours_count"]},
                None,
            ]},
        }},
        {"$sort": {"department": 1}},
    ]


def late_leaderboard_pipeline(
    start_str: str,
    end_str: str,
    limit: int,
    department: Optional[str] = None,
) -> list[dict[str, Any]]:
    return [
        {"$match": {"date": {"$gte": start_str, "$lt": end_str}}},
        {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"},
        {"$match": {"employee.department": department} if department else {}},
        {"$group": {"_id": "$emp_code", "name": {"$first": "$employee.name"}, "department": {"$first": "$employee.department"}, "total_late_minutes": {"$sum": "$late_minutes"}, "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}}}},
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$project": {"_id": 0, "rank": 1, "emp_code": "$_id", "name": 1, "department": 1, "total_late_minutes": 1, "late_count": 1}},
        {"$sort": {"total_late_minutes": -1, "emp_code": 1}},
    ]


def mongo_round_half_up(value: Any, places: int) -> dict[str, Any]:
    scale = 10 ** places
    decimal_scale = {"$toDecimal": str(scale)}
    return {
        "$divide": [
            {
                "$floor": {
                    "$add": [
                        {"$multiply": [{"$toDecimal": value}, decimal_scale]},
                        {"$toDecimal": "0.5"},
                    ]
                }
            },
            decimal_scale,
        ]
    }


def department_trend_pipeline(
    department: str,
    from_date: str,
    to_date: str,
) -> list[dict[str, Any]]:
    from_day = datetime.combine(parse_ymd(from_date), time.min, tzinfo=timezone.utc)
    to_day_exclusive = datetime.combine(parse_ymd(to_date) + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return [
        {"$documents": [{"day": from_day}]},
        {"$densify": {
            "field": "day",
            "range": {"step": 1, "unit": "day", "bounds": [from_day, to_day_exclusive]},
        }},
        {"$set": {"date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$day", "timezone": "UTC"}}}},
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"attendance_date": "$date"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$date", "$$attendance_date"]}}},
                {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "employee"}},
                {"$unwind": "$employee"},
                {"$match": {"employee.department": department}},
                {"$group": {
                    "_id": None,
                    "present_count": {"$sum": {"$cond": [
                        {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                        {"$cond": ["$half_day", 0.5, 1.0]},
                        0,
                    ]}},
                    "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
                }},
            ],
            "as": "daily_metrics",
        }},
        {"$lookup": {
            "from": "employees",
            "let": {"attendance_date": "$date"},
            "pipeline": [
                {"$match": {
                    "department": department,
                    "$expr": {"$lte": ["$joined_on", "$$attendance_date"]},
                }},
                {"$count": "headcount"},
            ],
            "as": "headcount_metrics",
        }},
        {"$set": {
            "is_working_day": {"$lte": [{"$isoDayOfWeek": "$day"}, 5]},
            "headcount": {"$ifNull": [{"$arrayElemAt": ["$headcount_metrics.headcount", 0]}, 0]},
            "present_count": {"$ifNull": [{"$arrayElemAt": ["$daily_metrics.present_count", 0]}, 0]},
            "late_count": {"$ifNull": [{"$arrayElemAt": ["$daily_metrics.late_count", 0]}, 0]},
        }},
        {"$set": {
            "attendance_rate": {"$cond": [
                {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
                mongo_round_half_up({"$divide": ["$present_count", "$headcount"]}, 4),
                None,
            ]},
        }},
        {"$setWindowFields": {
            "sortBy": {"day": 1},
            "output": {
                "moving_avg_raw": {
                    "$avg": "$attendance_rate",
                    "window": {"documents": [-6, 0]},
                },
            },
        }},
        {"$project": {
            "_id": 0,
            "day": 1,
            "date": 1,
            "is_working_day": 1,
            "headcount": 1,
            "present_count": 1,
            "late_count": 1,
            "attendance_rate": 1,
            "moving_avg_7d": {"$cond": [
                {"$ne": ["$moving_avg_raw", None]},
                mongo_round_half_up("$moving_avg_raw", 4),
                None,
            ]},
        }},
        {"$sort": {"day": 1}},
        {"$unset": "day"},
    ]


def explain_aggregation(collection: str | int, pipeline: list[dict[str, Any]]) -> dict[str, Any]:
    return db.command(
        "explain",
        {"aggregate": collection, "pipeline": pipeline, "cursor": {}},
        verbosity="executionStats",
    )
