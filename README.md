# Employee Attendance & Analytics API

FastAPI service backed by MongoDB. The implementation follows `openapi.yaml` and `DATA_MODEL.md`.

## Run locally

1. Install Python 3.11+ and MongoDB 6.0+ (or configure an Atlas cluster).
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set `MONGO_URI` and `MONGO_DB`.
4. Start the API from the project root:

   ```powershell
   uvicorn app.main:app --port 8000
   ```

   Swagger UI is available at `http://localhost:8000/docs`. The implementation is split by responsibility: `app/api/routers/` contains domain routes, `app/models/schemas.py` defines request models, `app/services/` holds business rules and analytics, `app/db/mongo.py` manages MongoDB, and `app/core/config.py` loads configuration.

To load the sample data into the configured database, run `python sample_seed.py`. This replaces the documents in the
`employees` and `attendance_logs` collections; do not run it against a database whose data you need to preserve.

## Tests

Install the test dependencies with `pip install -r requirements-dev.txt`, then run `python -m pytest -q`. Tests use an
isolated in-memory MongoDB mock and do not modify the database configured in `.env`.

Do not publish `.env` or credentials. `.gitignore` excludes local environment files and generated Python/test artifacts.

## Atlas connection troubleshooting

If startup fails with `ServerSelectionTimeoutError` and `SSL handshake failed`, verify that the Atlas cluster is running,
the machine's current public IP is allowed in the cluster's Network Access list, and outbound TCP port 27017 is permitted.
Also confirm that `MONGO_URI` points to the correct cluster and database user; URL-encode special characters in the
password. Do not disable TLS verification. Rotate any database password previously shared in chat and update `.env`.
After connectivity is restored, startup creates the indexes and `/health` should return `{"status":"ok"}`.
