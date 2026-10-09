"""Employee management endpoints."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pymongo.errors import DuplicateKeyError

from app.db.mongo import db
from app.models.schemas import EmployeeCreate
from app.services.serialization import serialize_employee

router = APIRouter(tags=["employees"])


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(payload: EmployeeCreate):
    existing = db.employees.find_one({"emp_code": payload.emp_code})
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "emp_code already exists")
    doc = payload.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "emp_code already exists") from exc
    return serialize_employee(doc)


@router.get("/employees")
def list_employees(
    department: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = {}
    if department is not None:
        query["department"] = department
    total = db.employees.count_documents(query)
    items = list(db.employees.find(query, {"_id": 0}).sort("emp_code", 1).skip((page - 1) * page_size).limit(page_size))
    return {"items": [serialize_employee(item) for item in items], "total": total, "page": page, "page_size": page_size}
