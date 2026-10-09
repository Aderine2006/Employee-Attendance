# Starter implementation review

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | Application layout and startup | The required `app.main:app` entry point and idempotent startup indexes were missing or incomplete. | Starting with the required Uvicorn command fails or concurrent duplicate requests create duplicate keys. | Keep `app.main:app` as the startup entry point, compose domain routers there, and create named unique/query indexes at startup through the database module. |
| 2 | Time helpers and punch endpoints | Naive PyMongo datetimes were compared to timezone-aware UTC values; dates and overnight shifts were not consistently derived in IST. | A punch-out can raise `TypeError`, or an overnight punch is assigned to the wrong day. | Normalize database instants to UTC, truncate to seconds, and derive attendance/shift dates in IST. |
| 3 | Punch-in and punch-out | Check-then-write handling did not guarantee duplicate or concurrent requests were safe. | Repeated punch-ins can create duplicates, or concurrent punch-outs overwrite each other. | Use unique natural-key indexes and conditional writes with a version/null guard. |
| 4 | Attendance listing and regularization | Filtering, pagination, timestamp validation, correction history, and concurrent update handling were incomplete. | Invalid dates/statuses are accepted, totals disagree with pages, or history is lost during simultaneous corrections. | Apply contract validation and filters, use bounded database pagination, append changed-field history, and reject stale updates. |
| 5 | Monthly/department analytics | Required aggregation-based calculations and business rules for weekends, join dates, open records, and stored derived values were missing or inconsistent. | Totals differ for weekend punches, mid-month hires, employees with no logs, or unclosed records. | Aggregate stored log values; calculate working days/headcount against half-open month bounds; retain zero-log employees. |
| 6 | Leaderboard, trend, and explain | Tie ranking, date gap filling, moving averages, and explain query construction did not follow the API contract. | Tied employees get distinct ranks, empty dates vanish, or explain runs a different pipeline from the endpoint. | Use rank by late total only, MongoDB date densification/window aggregation, and shared pipeline builders for explain. |

## Reviewed, not defects

- MongoDB `_id` remains internal; API records use the natural keys `emp_code` and (`emp_code`, `date`).
- The stored derived attendance fields are authoritative for analytics, as required by the data model.
- `.env` remains a local configuration file; it is excluded from source control rather than deleted, so local setup still works.
