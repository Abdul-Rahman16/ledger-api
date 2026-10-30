# Ledger API

A high-performance, secure FastAPI backend service for **Ledger** — an intelligent data analytics and exploration platform.

Ledger API powers dataset ingestion (CSV, Excel, JSON), automated data profiling and schema inference, custom semantic metric definitions with versioning, strict SQL injection prevention, and query management.

---

## Key Features

- **Automated Data Ingestion & Sanitization**:
  - Supports CSV, Excel (`.xlsx`), and JSON formats with strict safety limits (up to 5 MB, 100,000 rows, 100 columns).
  - Automatically cleans whitespace, drops redundant empty rows/columns, removes exact duplicates, and normalizes column headers.
  - Safe, conservative type inference (`boolean`, `integer`, `float`, `datetime`, `text`) without silent data loss.

- **Automated Data Profiling & Quality Scoring**:
  - Computes comprehensive column-level statistics (min, max, mean for numeric; min/max for datetimes; top values for text).
  - Calculates null percentages, unique value counts, and an overall dataset health/quality score (0–100).
  - Ingests cleaned data into isolated, server-generated PostgreSQL tables (`ds_<uuid>`).

- **Secure Semantic Metric Engine**:
  - Closed-grammar tokenizer and allow-list recursive descent parser for metric formulas and filters.
  - Rebuilds validated expressions into safe canonical SQL with quoted identifiers, escaped literals, and division-by-zero protection (`NULLIF(..., 0)`).
  - Strict SQL injection defense rejecting arbitrary statements, subqueries, comments, and unapproved SQL functions.

- **Metric Versioning & Lifecycle**:
  - Immutable version history for business metrics.
  - Concurrency-safe updates with row-level locks and database-enforced unique active version constraints.
  - Soft deletion / retirement for full auditability.

- **Security & Multi-Tenancy**:
  - Guest mode support (datasets accessible by unguessable UUIDs).
  - Authenticated user isolation via secure internal HMAC credentials (`X-User-Id` + `X-Internal-Secret`) delegated from the frontend.
  - Built-in sliding-window rate limiting on read, write, and upload endpoints.
  - Structured JSON logging using `structlog`.

---

## Architecture & Project Structure

```text
ledger-api/
├── alembic/                # Database migration scripts and environment
│   ├── versions/           # Migration revision files
│   └── env.py              # Alembic configuration connected to application settings
├── alembic.ini             # Alembic configuration
├── api/                    # API routes and request/response schemas
│   ├── datasets.py         # Dataset upload, retrieval, and listing endpoints
│   ├── metrics.py          # Semantic metric validation, CRUD, and versioning endpoints
│   ├── schemas.py          # Pydantic schemas for datasets and column profiles
│   └── metric_schemas.py   # Pydantic schemas for metrics and validation results
├── core/                   # Application foundation and utilities
│   ├── config.py           # Environment settings via pydantic-settings
│   ├── db.py               # SQLAlchemy database session and engine setup
│   ├── logging.py          # Structured JSON logging configuration (structlog)
│   ├── ratelimit.py        # Sliding-window in-memory rate limiter
│   └── security.py         # Identity resolution and HMAC internal credential checks
├── domain/                 # Core business logic and database models
│   ├── dataset_service.py  # Dataset access control and query logic
│   ├── ingestion.py        # Upload parsing, limits validation, and database ingestion
│   ├── metric_service.py   # Metric versioning, state management, and lifecycle logic
│   ├── metric_validator.py # Custom AST tokenizer, validator, and SQL compiler
│   ├── models.py           # SQLAlchemy ORM models (Dataset, DatasetColumn, MetricDefinition, QueryLog)
│   └── profiling.py        # DataFrame cleaning, type inference, profiling, and quality score
├── tests/                  # Automated test suite
│   └── unit/               # Unit tests for API, profiling, ingestion, and metric validation
├── docker-compose.yml      # Local PostgreSQL service definition
├── main.py                 # FastAPI application entrypoint and route registration
├── requirements.txt        # Project Python dependencies
└── pytest.ini              # Pytest configuration
```

---

## Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.10+)
- **Database**: [PostgreSQL 16](https://www.postgresql.org/)
- **ORM & Migrations**: [SQLAlchemy 2.x](https://www.sqlalchemy.org/) & [Alembic](https://alembic.sqlalchemy.org/)
- **PostgreSQL Driver**: [Psycopg 3](https://www.psycopg.org/psycopg3/) / [psycopg2-binary](https://pypi.org/project/psycopg2-binary/)
- **Data Processing**: [Pandas](https://pandas.pydata.org/), [NumPy](https://numpy.org/), [openpyxl](https://openpyxl.readthedocs.io/)
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/) & [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- **Testing**: [pytest](https://docs.pytest.org/) & [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)

---

## Getting Started

### Prerequisites

- **Python 3.10+** (Python 3.11 or 3.12 recommended)
- **Docker** and **Docker Compose** (for PostgreSQL)

---

### 1. Clone the Repository

```bash
git clone https://github.com/Abdul-Rahman16/ledger-api.git
cd ledger-api
```

### 2. Set Up Virtual Environment

#### On Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### On macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Configure Environment Variables

Create a `.env` file from the provided `.env.example`:

```bash
cp .env.example .env
```

Default `.env` configuration:
```env
DATABASE_URL=postgresql://ledger:ledger@localhost:5434/ledger
INTERNAL_SECRET=your-internal-secret-key-here
GROQ_API_KEY=
GEMINI_API_KEY=
ENVIRONMENT=development
```

> **Note**: In SQLAlchemy 2.0+, standard `postgresql://` connection URLs use `psycopg` (Psycopg 3) directly.

---

### 5. Start the PostgreSQL Database

Start the PostgreSQL service using Docker Compose:

```bash
docker compose up -d db
```

The database container will run on port `5434` (mapped to internal `5432`).

---

### 6. Run Database Migrations

Apply Alembic migrations to create the database tables:

```bash
python -m alembic upgrade head
```

To autogenerate a new migration after editing `domain/models.py`:
```bash
python -m alembic revision --autogenerate -m "describe changes"
python -m alembic upgrade head
```

> **Windows / Device Guard Tip**: Use `python -m alembic ...` instead of `alembic ...` to bypass Device Guard / WDAC execution policies that block unsigned binary stubs in `.venv\Scripts`.

---

### 7. Run the API Server

Start the local development server with auto-reload:

```bash
python -m uvicorn main:app --reload --port 8000
```

- **API Base URL**: `http://localhost:8000`
- **Interactive Swagger Docs**: `http://localhost:8000/docs`
- **ReDoc API Documentation**: `http://localhost:8000/redoc`

---

## Running Tests

Run the full unit test suite with `pytest`:

```bash
python -m pytest
```

Run tests with verbose output:
```bash
python -m pytest -v
```

---

## API Overview

### Health Check
- `GET /health` — Check server status (`{"status": "ok"}`).

### Datasets (`/datasets`)
- `POST /datasets` — Upload and profile a file (`multipart/form-data`: `file`).
- `GET /datasets` — List datasets for the current identity (supports pagination via `limit` and `offset`).
- `GET /datasets/{dataset_id}` — Retrieve detailed dataset metadata and column profiles.

### Metrics (`/datasets/{dataset_id}/metrics`)
- `POST /datasets/{dataset_id}/metrics/validate` — Dry-run validation of a metric expression & optional filter (does not save).
- `POST /datasets/{dataset_id}/metrics` — Create a new named semantic metric.
- `GET /datasets/{dataset_id}/metrics` — List all active metrics for the dataset.
- `GET /datasets/{dataset_id}/metrics/{name}` — Get the active definition of a specific metric.
- `GET /datasets/{dataset_id}/metrics/{name}/versions` — Get full version history for a metric.
- `POST /datasets/{dataset_id}/metrics/{name}/versions` — Publish a new version of an existing metric.
- `DELETE /datasets/{dataset_id}/metrics/{name}` — Retire (soft-delete) a metric.

### Queries (`/datasets/{dataset_id}/query`)
- `POST /datasets/{dataset_id}/query` — Execute governed semantic queries with metric formulas, grouping, time bucketing (`day`, `week`, `month`, `quarter`, `year`), date filtering, and sorting.

---

## Metric Expression Grammar

Metrics are parsed by an allow-list compiler, never executed as free-form SQL:

- **Aggregates**: `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, `COUNT(DISTINCT column)`
- **Arithmetic**: `+`, `-`, `*`, `/` across aggregates and numeric literals (e.g., `SUM(revenue) / COUNT(DISTINCT user_id)`)
- **Filters**: Boolean expressions with `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=`, `IS [NOT] NULL`, `[NOT] IN (...)`, `[NOT] LIKE`, `BETWEEN ... AND ...`

#### Example Valid Metric
```json
{
  "name": "aov_completed",
  "description": "Average order value for completed orders",
  "expression": "SUM(order_total) / COUNT(DISTINCT order_id)",
  "filter": "status = 'completed' AND order_total > 0"
}
```

---

## Security & Authentication

- **Guest Access**: Omitting headers treats the caller as a guest. Guest datasets are referenced by UUID and are not listed in library queries.
- **Authenticated Access**: The Next.js frontend sends:
  - `X-User-Id`: The authenticated user's ID.
  - `X-Internal-Secret`: Shared secret verified using constant-time comparison against `INTERNAL_SECRET`.
  If `INTERNAL_SECRET` is unset or fails verification, authenticated requests fail closed (`401 Unauthorized`).