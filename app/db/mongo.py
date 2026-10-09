"""MongoDB client, database access, and startup indexes."""
from pymongo import MongoClient

from app.core.config import MONGO_DB, MONGO_URI

client = MongoClient(MONGO_URI)
_database = client[MONGO_DB]


class DatabaseProxy:
    """Resolve database operations against the currently configured database."""

    def __getattr__(self, name):
        return getattr(_database, name)


db = DatabaseProxy()


def set_database(database):
    """Replace the active database, primarily for isolated test fixtures."""
    global _database
    _database = database


def ensure_indexes() -> None:
    db.employees.create_index("emp_code", unique=True, name="ux_employees_emp_code")
    db.employees.create_index([("department", 1), ("emp_code", 1)], name="ix_employees_department_emp_code")
    db.employees.create_index([("department", 1), ("joined_on", 1), ("emp_code", 1)], name="ix_employees_department_joined_emp_code")
    db.employees.create_index([("joined_on", 1), ("department", 1), ("emp_code", 1)], name="ix_employees_joined_department_emp_code")

    db.attendance_logs.create_index([("emp_code", 1), ("date", 1)], unique=True, name="ux_attendance_emp_code_date")
    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1), ("status", 1)],
        name="ix_attendance_date_emp_code_status",
    )
