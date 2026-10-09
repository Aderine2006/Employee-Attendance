"""Timezone, attendance-date, and derived-time calculations."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

IST = timezone(timedelta(hours=5, minutes=30))
PRESENCE_STATUSES = {"PRESENT", "WFH", "ON_DUTY"}


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def truncate_seconds(dt: datetime) -> datetime:
    dt = ensure_utc(dt)
    if dt is None:
        raise ValueError("datetime is required")
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def epoch_ms(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    dt = ensure_utc(truncate_seconds(dt))
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def dt_from_epoch(ms: Optional[int]) -> Optional[datetime]:
    if ms is None:
        return None
    if not isinstance(ms, int) or isinstance(ms, bool):
        raise ValueError("epoch milliseconds must be an integer")
    if ms < 100000000000 or ms > 4102444800000:
        raise ValueError("epoch milliseconds out of range")
    return ensure_utc(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))


def round_half_up(value: float | int | Decimal, places: int) -> float:
    quant = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def parse_ymd(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")
    return parsed


def parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def minutes_of_day(value: str | time) -> int:
    if isinstance(value, str):
        hh, mm = value.split(":")
        return int(hh) * 60 + int(mm)
    return value.hour * 60 + value.minute


def iso_ist(dt: Optional[datetime]) -> Optional[datetime]:
    dt = ensure_utc(dt)
    if dt is None:
        return None
    return dt.astimezone(IST)


def is_overnight(shift_start: str, shift_end: str) -> bool:
    return minutes_of_day(shift_end) <= minutes_of_day(shift_start)


def attendance_date_for_instant(emp: dict[str, Any], instant_utc: datetime) -> str:
    ist_dt = iso_ist(instant_utc)
    shift_start = emp["shift_start"]
    shift_end = emp["shift_end"]
    if is_overnight(shift_start, shift_end):
        if ist_dt.time() < parse_hhmm(shift_end):
            return (ist_dt.date() - timedelta(days=1)).isoformat()
    return ist_dt.date().isoformat()


def shift_start_dt_for_emp(emp: dict[str, Any], instant_utc: datetime) -> datetime:
    record_date = parse_ymd(attendance_date_for_instant(emp, instant_utc))
    start_h, start_m = map(int, emp["shift_start"].split(":"))
    return datetime.combine(record_date, time(start_h, start_m, tzinfo=IST))


def shift_end_dt_for_record(emp: dict[str, Any], record_date_str: str) -> datetime:
    record_date = parse_ymd(record_date_str)
    end_h, end_m = map(int, emp["shift_end"].split(":"))
    end_time = time(end_h, end_m)
    if is_overnight(emp["shift_start"], emp["shift_end"]):
        return datetime.combine(record_date + timedelta(days=1), end_time, tzinfo=IST)
    return datetime.combine(record_date, end_time, tzinfo=IST)


def compute_late_minutes(punch_in_utc: datetime, shift_start: str, shift_end: str) -> int:
    punch_in_utc = ensure_utc(truncate_seconds(punch_in_utc))
    emp_like = {"shift_start": shift_start, "shift_end": shift_end}
    start_dt = shift_start_dt_for_emp(emp_like, punch_in_utc)
    elapsed_seconds = (punch_in_utc.astimezone(IST) - start_dt.astimezone(IST)).total_seconds()
    return max(0, int(elapsed_seconds // 60)) if elapsed_seconds > 10 * 60 else 0


def compute_work_hours(punch_in_utc: datetime, punch_out_utc: datetime) -> float:
    punch_in_utc = ensure_utc(punch_in_utc)
    punch_out_utc = ensure_utc(punch_out_utc)
    delta = punch_out_utc - punch_in_utc
    hours = Decimal(delta.total_seconds()) / Decimal(3600)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def recompute_derived_fields(record: dict[str, Any], emp: dict[str, Any]) -> dict[str, Any]:
    status = record.get("status")
    punch_in = record.get("punch_in")
    punch_out = record.get("punch_out")
    punch_in = truncate_seconds(punch_in) if punch_in is not None else None
    punch_out = truncate_seconds(punch_out) if punch_out is not None else None
    record["punch_in"] = punch_in
    record["punch_out"] = punch_out
    if status in {"ABSENT", "LEAVE"}:
        record["late_minutes"] = 0
        record["overtime_minutes"] = 0
        record["half_day"] = False
        record["work_hours"] = None
        return record
    if punch_in is None:
        record["late_minutes"] = 0
        record["overtime_minutes"] = 0
        record["half_day"] = False
        record["work_hours"] = None
        return record

    record["late_minutes"] = compute_late_minutes(punch_in, emp["shift_start"], emp["shift_end"])
    if punch_out is not None:
        work_hours = compute_work_hours(punch_in, punch_out)
        record["work_hours"] = work_hours
        record["overtime_minutes"] = max(
            0,
            int((punch_out.astimezone(IST) - shift_end_dt_for_record(emp, record["date"]).astimezone(IST)).total_seconds() / 60),
        )
        if record["overtime_minutes"] < 30:
            record["overtime_minutes"] = 0
        record["half_day"] = work_hours < 4.50
    else:
        record["work_hours"] = None
        record["overtime_minutes"] = 0
        record["half_day"] = False
    return record
