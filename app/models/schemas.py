"""Pydantic request schemas and contract validation."""
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.time import parse_ymd

class EmployeeCreate(BaseModel):
    emp_code: str
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., max_length=120)
    department: str = Field(..., min_length=1, max_length=50)
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("emp_code")
    @classmethod
    def validate_emp_code(cls, v: str) -> str:
        if re.fullmatch(r"EMP\d{4,6}", v) is None:
            raise ValueError("emp_code must match EMP followed by 4 to 6 digits")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) is None:
            raise ValueError("invalid email")
        return v

    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_hhmm(cls, v: str) -> str:
        if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", v) is None:
            raise ValueError("time must be HH:MM")
        return v

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, v: str) -> str:
        try:
            parse_ymd(v)
        except ValueError as exc:
            raise ValueError("joined_on must be YYYY-MM-DD") from exc
        return v

    @model_validator(mode="after")
    def validate_shift_times(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must differ")
        return self


class PunchInRequest(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(default=None, strict=True)
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"

    @field_validator("punched_at")
    @classmethod
    def validate_punched_at(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if isinstance(v, bool):
            raise ValueError("punched_at must be an integer epoch millisecond value")
        if isinstance(v, float):
            raise ValueError("punched_at must be an integer epoch millisecond value")
        if v < 100000000000 or v > 4102444800000:
            raise ValueError("punched_at out of range")
        return v


class PunchOutRequest(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(default=None, strict=True)

    @field_validator("punched_at")
    @classmethod
    def validate_punched_at(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if isinstance(v, bool):
            raise ValueError("punched_at must be an integer epoch millisecond value")
        if isinstance(v, float):
            raise ValueError("punched_at must be an integer epoch millisecond value")
        if v < 100000000000 or v > 4102444800000:
            raise ValueError("punched_at out of range")
        return v


class RegularizeRequest(BaseModel):
    status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None
    punch_in: Optional[int] = Field(default=None, strict=True)
    punch_out: Optional[int] = Field(default=None, strict=True)
    reason: str = Field(..., min_length=5, max_length=200)
    regularized_by: str = Field(..., min_length=1, max_length=50)

    @field_validator("punch_in", "punch_out")
    @classmethod
    def validate_epoch(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if isinstance(v, bool):
            raise ValueError("epoch values must be integers")
        if isinstance(v, float):
            raise ValueError("epoch values must be integers")
        if v < 100000000000 or v > 4102444800000:
            raise ValueError("epoch value out of range")
        return v
