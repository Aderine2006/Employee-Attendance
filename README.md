# Employee Attendance & Analytics API

A FastAPI service for employee records, daily attendance, punch-in/out, manual attendance
corrections, and MongoDB-backed attendance analytics. The HTTP interface and business
rules are specified in [`openapi.yaml`](openapi.yaml); collection shapes and sample
documents are documented in [`DATA_MODEL.md`](DATA_MODEL.md).

## Project structure

```text
app/
  main.py                    FastAPI app factory and stable Uvicorn entry point
  core/
    config.py                .env/environment configuration
    time.py                  UTC/IST conversions and attendance calculations
  db/
    mongo.py                 MongoDB client, database access, and startup indexes
  models/
    schemas.py               Pydantic request schemas and input validation
  services/
    attendance.py            Attendance helpers and employee-month calculations
    analytics.py             MongoDB analytics pipelines and explain helper
    serialization.py         Database-to-API response conversion
  api/routers/
    system.py                Readiness endpoint
    employees.py             Employee routes
    attendance.py            Punch, list, and regularization routes
    analytics.py             Employee and department analytics routes
    admin.py                 Query explain route
tests/
  conftest.py                Isolated mongomock database for every test
  test_api.py                API, business-rule, concurrency, and pipeline tests
```

The application remains runnable through the required import path:

```powershell
uvicorn app.main:app --port 8000
```

Run that command from the project root. Interactive API documentation is at
`http://localhost:8000/docs`; the generated schema is at `/openapi.json`.

## Requirements and local setup

- Python 3.11 or newer
- MongoDB 6.0 or newer (local server or MongoDB Atlas)
- Dependencies in `requirements.txt`

For a new local virtual environment in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` to configure the connection before starting the application. The supplied
`.env.example` uses a local MongoDB URI and the `attendance_db` database. Real process
environment variables take precedence over `.env`; see `.gitignore` and do not publish
`.env` or credentials.

For example, set a value only in the current PowerShell session with
`$env:MONGO_URI = "mongodb://localhost:27017"` and
`$env:MONGO_DB = "attendance_db"`. These process values override values loaded from
`.env`. The service does not contact any external service; MongoDB is its only
infrastructure dependency.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` | PyMongo connection string |
| `MONGO_DB` | `attendance_db` | Database containing the two application collections |

The application creates its MongoDB client during import and creates indexes in the
FastAPI startup lifespan. Startup therefore requires a reachable MongoDB server.
`GET /health` pings MongoDB and returns `{"status":"ok"}` when it is available, or
HTTP 503 if the ping fails.

## Data model and API conventions

The database contains `employees` and `attendance_logs`; the API uses `emp_code` as the
employee identifier and (`emp_code`, `date`) as an attendance record's natural key.
MongoDB's internal `_id` is not accepted or returned. Instants are BSON UTC datetimes
in MongoDB and integer epoch milliseconds in HTTP requests/responses. Calendar dates
are `YYYY-MM-DD` strings, month parameters are `YYYY-MM`, and shift times are 24-hour
`HH:MM` strings in IST (UTC+05:30). See [`DATA_MODEL.md`](DATA_MODEL.md) for every
stored field and the example data.

Attendance statuses:

| Status | Meaning | Has punch times? | Counts as present? |
|---|---|---:|---:|
| `PRESENT` | Worked on site | Yes | Yes |
| `WFH` | Worked from home | Yes | Yes |
| `ON_DUTY` | Official duty away from the office | Yes | Yes |
| `ABSENT` | Did not work and is not on approved leave | No | No |
| `LEAVE` | Approved leave | No | No |

Punch-in creates a presence record. No endpoint creates `ABSENT` or `LEAVE`; those
records may be seeded by back-office processes or set through regularization. A day
with no record is distinct from an absent day. Derived values (`work_hours`,
`late_minutes`, `overtime_minutes`, and `half_day`) are calculated by the API and are
not client-editable. Analytics use the stored derived values.

## Business rules (R1–R10)

These summarize the contract in `openapi.yaml`; that file remains authoritative.

1. **Timezone and attendance date:** shifts and attendance dates use IST. An overnight
   shift is one where `shift_end <= shift_start`; a punch-in earlier than its end time
   belongs to the preceding shift-start date. Shift end is on the following calendar
   day. Instants are truncated to whole seconds before storage and response.
2. **Late arrival:** there is a 10-minute grace period. Arrival is late only when it is
   strictly more than 10 minutes after shift start; late minutes are floored elapsed
   minutes since shift start (not since the end of grace).
3. **Overtime:** whole floored minutes after shift end count only when the elapsed
   overtime is at least 30 minutes.
4. **Work hours:** `(punch_out - punch_in)` in hours, rounded to two decimals using
   half-up rounding; null until punch-out.
5. **Half day:** after punch-out, true if the rounded work duration is below 4.50 hours.
   In present-day analytics, a half day contributes 0.5.
6. **Presence:** `PRESENT`, `WFH`, and `ON_DUTY` count as present; `ABSENT` and `LEAVE`
   do not.
7. **Working days:** Monday–Friday, without a holiday calendar. For a mid-month hire,
   count from `joined_on`. Present days count only weekday records; weekend records can
   still contribute to late/overtime totals.
8. **Reported rounding:** numbers use half-up rounding to two decimals, except rates,
   which use four decimals.
9. **Headcount:** employees count from their `joined_on` date through the relevant
   period date, even if they have no attendance logs. Future joiners do not count.
10. **Pagination:** pages start at 1, default page size is 20, maximum is 100, and
    `total` is calculated after filters.

All point-in-time request fields reject seconds instead of milliseconds, floats,
strings, and out-of-range epoch values with HTTP 422. See the contract for validation,
error, and history details.

## Endpoint catalog

All errors use FastAPI's standard `{"detail": ...}` response. Invalid inputs generally
return 422, unknown employees or records return 404 where applicable, and unique-key
or concurrent-write conflicts return 409.

| Method and path | Purpose | Main inputs / behavior |
|---|---|---|
| `GET /health` | Readiness check | Returns 200 only when MongoDB answers a ping; otherwise 503. |
| `POST /employees` | Create employee | Client provides unique `emp_code`, name, email, department, and `joined_on`; optional shift times default to `09:30`–`18:30`. Returns 201; duplicate code returns 409. |
| `GET /employees` | List employees | Optional exact `department`, `page`, and `page_size`; sorted by `emp_code` ascending. |
| `POST /attendance/punch-in` | Record punch-in | `emp_code`, optional `punched_at` epoch milliseconds, optional presence `status` (defaults to `PRESENT`). Returns 201; one record per employee/date. |
| `POST /attendance/punch-out` | Record punch-out | `emp_code` and optional `punched_at`. Requires an open punch-in; punch-out must be later and no more than 24 hours later. |
| `GET /attendance` | List attendance | Optional `emp_code`, inclusive `date_from`/`date_to`, `status`, `page`, and `page_size`; newest date first. |
| `PATCH /attendance/{emp_code}/{date}` | Regularize a record | Optional status and punch-time corrections plus required `reason` and `regularized_by`; recomputes derived values and appends audit history. |
| `GET /analytics/employees/{emp_code}/monthly` | Employee monthly summary | Requires `month=YYYY-MM`; reports working/present/leave days, lateness/overtime totals and attendance percentage. |
| `GET /analytics/departments/summary` | Department summary | Requires `month=YYYY-MM`; optional exact `department`; includes people without logs. |
| `GET /analytics/leaderboard/late` | Monthly late leaderboard | Requires `month=YYYY-MM`; optional `limit` (1–50, default 10) and department. Tied employees share competition rank. |
| `GET /analytics/departments/{department}/trend` | Daily department trend | Inclusive `from` and `to` date query parameters; range must be at most 92 days. Returns one row per date. |
| `GET /admin/explain/{endpoint}` | Explain a supported query | `endpoint` is one of `attendance_list`, `employee_monthly`, `department_summary`, `late_leaderboard`, or `department_trend`; accepts that query's corresponding parameters. |

Example monthly summary request:

```text
GET http://localhost:8000/analytics/employees/EMP0001/monthly?month=2026-07
```

The `month` value is a calendar month (`YYYY-MM`), not a timestamp. Department summary
and leaderboard requests use the same format, for example:

```text
GET http://localhost:8000/analytics/departments/summary?month=2026-07&department=Engineering
GET http://localhost:8000/analytics/leaderboard/late?month=2026-07&limit=10
```

Regularization only records fields that actually changed in its history entry. Setting
status to `ABSENT` or `LEAVE` clears punch times; presence statuses require a punch-in.
Corrections cannot move a punch-in to a different attendance date. Optimistic
concurrency checks reject stale writes rather than silently overwriting another edit's
history.

The trend response includes working-day flag, headcount, present count, late count,
attendance rate, and seven-calendar-day moving average. Rate is null on weekends or
when headcount is zero; moving averages ignore null rates and start at the requested
`from` date.

### Example requests

Create an employee (shift times are optional and default to `09:30`–`18:30`):

```powershell
$employee = @{
    emp_code = "EMP0007"
    name = "Mira Das"
    email = "mira@example.com"
    department = "Engineering"
    joined_on = "2026-10-01"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/employees" `
    -ContentType "application/json" -Body $employee
```

Punch in now (or provide `punched_at` as an integer epoch-millisecond timestamp):

```powershell
$punch = @{ emp_code = "EMP0007"; status = "PRESENT" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/attendance/punch-in" `
    -ContentType "application/json" -Body $punch
```

Punch out and request the employee's October 2026 monthly summary:

```powershell
$punchOut = @{ emp_code = "EMP0007" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/attendance/punch-out" `
    -ContentType "application/json" -Body $punchOut

Invoke-RestMethod -Method Get `
    -Uri "http://localhost:8000/analytics/employees/EMP0007/monthly?month=2026-10"
```

The monthly `month` query parameter is required and must be `YYYY-MM`, such as
`2026-10`; it is not a day or an epoch value. Timestamp request/response properties
use integer epoch milliseconds, while attendance dates use `YYYY-MM-DD`.

## MongoDB analytics, indexes, and concurrency

- Employee-month and department-summary metrics are computed with MongoDB aggregation
  pipelines and read the stored derived attendance values. Department summaries start
  from employees, so headcount includes employees with no logs.
- The late leaderboard groups records by employee, applies MongoDB `$rank` so ties get
  standard competition ranks, then applies the rank limit and stable output ordering.
- Department trends are generated inside MongoDB with `$documents`, `$densify`,
  `$setWindowFields`, and database lookups; the API does not synthesize missing days
  in a Python loop. Use MongoDB 6.0+ for the supported pipeline stages.
- Index creation is idempotent and runs at startup: unique employee code; department
  and join-date lookup indexes; unique (`emp_code`, `date`) attendance key; and
  date/employee/status index for attendance listing and analytics.
- The unique indexes are the final guard against duplicate employee codes and duplicate
  daily attendance. Punch-in maps a duplicate-key race to 409. Punch-out and
  regularization use conditional version-aware updates; concurrent losers receive 409.
- Explain plans run with `executionStats` for the same query/pipeline and filters used
  by the named endpoint. Use them on representative data to check index use and
  investigate scans or latency.

For example, explain the employee-monthly aggregation:

```text
GET http://localhost:8000/admin/explain/employee_monthly?emp_code=EMP0001&month=2026-07
```

Other explain selectors are `attendance_list`, `department_summary`,
`late_leaderboard`, and `department_trend`. Supply the corresponding filters:
`date_from`, `date_to`, `status`, `page`, and `page_size` for attendance listing;
`month` (and optional `department`) for monthly/department analytics; and
`department`, `from`, and `to` for a trend. Missing required parameters return 422.
The response includes the selector, collection/database name, and raw MongoDB explain
document. Explain stages and their plans depend on the MongoDB server version and
dataset.

## Sample data

The root-level `employees.json` and `attendance_logs.json` are MongoDB Extended JSON
examples documenting record shapes. To load them:

```powershell
python sample_seed.py
```

The seed script clears and replaces the `employees` and `attendance_logs` collections
in the configured database. **It is destructive**; verify `MONGO_URI` and `MONGO_DB`
and do not run it against data that must be preserved. The sample documents illustrate
shapes, not the hidden/evaluation data distribution, and are insufficient to validate
edge cases such as ties, weekends, mid-month hires, or employees without logs. See
[`DATA_MODEL.md`](DATA_MODEL.md) for document examples and details.

## Tests

Install test dependencies if they are not already available, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

For a local virtual environment named `.venv-1`, use its interpreter instead:

```powershell
.\.venv-1\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Tests use an isolated `mongomock` database and do not read or write the configured
Atlas/local database. They cover HTTP behavior, validation, time calculations,
regularization history, concurrent duplicate requests, pagination, and aggregation
pipeline construction. MongoDB-specific aggregation features and real query plans
still require validation against a reachable MongoDB server.

## Security and connection troubleshooting

- Keep `.env` local; never commit it, paste connection strings into tickets, or publish
  database credentials. Rotate credentials that may have been exposed.
- Use a least-privilege database user and URL-encode special characters in its
  password. Do not disable TLS certificate validation.
- If startup fails with `ServerSelectionTimeoutError` or an SSL/TLS handshake error,
  confirm the cluster is running, the client's public IP is allowed in Atlas Network
  Access, outbound TCP 27017 is permitted, and the URI points to the correct cluster
  and user. Check local/VPN/firewall TLS interception as well.
- If MongoDB reports `bad auth` or `authentication failed`, the server was reached but
  rejected the database credentials. In Atlas, confirm the **database user** (not the
  Atlas website login), password, and required authentication database; URL-encode
  reserved password characters in the URI. Update `.env` or the process environment,
  then restart the app. Never paste the URI into logs or support messages.
- The application creates indexes during startup, so an unreachable MongoDB prevents
  the lifespan from completing; `/health` will not report ready until MongoDB responds.
- Authentication and authorization are outside this assignment contract; the
  `regularized_by` field is audit metadata, not identity verification.

If an Atlas TLS/network or authentication failure persists, tests can still verify API
behavior using the isolated mock, but production startup, MongoDB server-side analytics,
index selection, and explain plans remain unverified until connectivity is restored.

## Assignment references and known verification limits

- [`openapi.yaml`](openapi.yaml) is the authoritative HTTP contract: routes, parameters,
  response fields, status codes, and business rules.
- [`DATA_MODEL.md`](DATA_MODEL.md) documents MongoDB collection fields and sample
  documents.
- [`REVIEW.md`](REVIEW.md) records the starter-code review and fixes.
- [`DECISIONS.md`](DECISIONS.md) explains indexing, concurrency, ranking, headcount,
  and scale tradeoffs.
- [`PROBLEM_STATEMENT.docx`](PROBLEM_STATEMENT.docx) is the supplied assignment brief.

The automated test suite uses `mongomock`; it does not prove compatibility of every
server-side pipeline stage or index plan with a live MongoDB instance. Validate those
against MongoDB 6.0+ after connection access is available. The supplied sample data is
illustrative and does not replace tests for the larger edge cases described in the
contract.
