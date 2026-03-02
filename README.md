# Trajan Backend

A structured, async Python backend for managing software products, repositories,
documentation, and development work. Built with FastAPI, SQLModel, and PostgreSQL.

Trajan is a lightweight developer workspace — not a project management tool.
It gives teams a calm, repo-centric place to track what they're building, maintain
documentation alongside code, and keep essential project context (env vars, infra notes,
service URLs) in one place. Designed for humans first, with an architecture that supports
AI agents without requiring them.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          FastAPI Application                        │
│                                                                     │
│  Middleware Stack                                                    │
│  ┌───────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Proxy     │→ │ CORS     │→ │ Request  │→ │ Public Domain     │  │
│  │ Headers   │  │          │  │ Logging  │  │ Host Filtering    │  │
│  └───────────┘  └──────────┘  └──────────┘  └───────────────────┘  │
│                                                                     │
│  ┌──────────────────── API Layer (v1) ─────────────────────────┐    │
│  │                                                             │    │
│  │  Routes          Dependencies (injected)                    │    │
│  │  ┌──────────┐    ┌──────────────────────────────────┐       │    │
│  │  │ products │    │ CurrentUser    (JWT validation)   │       │    │
│  │  │ orgs     │───→│ DbSession      (async session)   │       │    │
│  │  │ docs     │    │ ProductAccess  (3-level authz)   │       │    │
│  │  │ progress │    │ FeatureGate    (plan limits)     │       │    │
│  │  │ billing  │    │ SubContext     (org + plan)      │       │    │
│  │  │ tickets  │    └──────────────────────────────────┘       │    │
│  │  └──────────┘                                               │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              │                                      │
│  ┌──────────────────── Domain Layer ───────────────────────────┐    │
│  │                                                             │    │
│  │  BaseOperations[T]  (generic CRUD)                          │    │
│  │       │                                                     │    │
│  │       ├── ProductOperations                                 │    │
│  │       ├── OrganizationOperations                            │    │
│  │       ├── DocumentOperations                                │    │
│  │       ├── SubscriptionOperations                            │    │
│  │       └── ... (22 model-specific operation classes)         │    │
│  │                                                             │    │
│  │  Each instantiated as a module-level singleton:             │    │
│  │       product_ops = ProductOperations()                     │    │
│  │                                                             │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              │                                      │
│  ┌──────────── Services ─────┴───────────────────────────────┐      │
│  │  GitHub API    Stripe     Claude (AI)    Postmark Email   │      │
│  │  (httpx/H2)   (webhooks)  (analysis)     (transactional)  │      │
│  │                                                           │      │
│  │  APScheduler ── advisory locks ── multi-instance safe     │      │
│  └───────────────────────────────────────────────────────────┘      │
│                              │                                      │
│  ┌──────────── Core ─────────┴───────────────────────────────┐      │
│  │  Database         RLS Context       Request Cache         │      │
│  │  (dual engines)   (SET LOCAL)       (ContextVar)          │      │
│  │                                                           │      │
│  │  Rate Limiter     Encryption        Security              │      │
│  │  (sliding window) (Fernet)          (JWT + JWKS)          │      │
│  └───────────────────────────────────────────────────────────┘      │
│                              │                                      │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼──────┐  ┌─────▼──────┐  ┌──────▼───────┐
     │  PostgreSQL   │  │  Supabase  │  │   External   │
     │  (Supabase)   │  │  Auth      │  │   APIs       │
     │               │  │            │  │              │
     │  - RLS        │  │  - JWKS    │  │  - GitHub    │
     │  - Advisory   │  │  - JWT     │  │  - Stripe    │
     │    locks      │  │  - OAuth   │  │  - Anthropic │
     │  - pg_trgm    │  │            │  │  - Postmark  │
     └───────────────┘  └────────────┘  └──────────────┘
```

---

## Request Lifecycle

Every authenticated request follows the same path through the dependency injection
chain. FastAPI resolves the full graph before the route handler executes:

```
 HTTP Request
      │
      ▼
 ┌─────────────────────────────────────────────────┐
 │ 1. Extract Bearer token from Authorization hdr  │
 │                                                 │
 │ 2. Validate JWT against Supabase JWKS           │
 │    - ES256 signature verification               │
 │    - 1-hour JWKS cache with rotation retry      │
 │    - Auto-create User record on first API call  │
 │                                                 │
 │ 3. Acquire async DB session from pool           │
 │    - Transaction pooler (port 6543)             │
 │    - Prepared statements disabled (PgBouncer)   │
 │                                                 │
 │ 4. SET LOCAL app.current_user_id = '{uuid}'     │
 │    - Transaction-scoped (auto-resets on commit)  │
 │    - All subsequent queries filtered by RLS     │
 │                                                 │
 │ 5. Resolve access control                       │
 │    - Organization role: owner/admin/member/viewer│
 │    - Product-level override: admin → none       │
 │    - Effective = max(org_role, product_access)   │
 │                                                 │
 │ 6. Check feature gates (plan limits)            │
 │    - 402 Payment Required if over plan limit    │
 │                                                 │
 │ 7. Route handler executes                       │
 │    - Calls domain operations (BaseOperations)   │
 │    - DB queries already scoped by RLS           │
 │                                                 │
 │ 8. Commit or rollback                           │
 │    - SET LOCAL resets automatically              │
 │    - Connection returned to pool                │
 └─────────────────────────────────────────────────┘
```

---

## Design Decisions

### Row-Level Security with Connection Pooling

The hardest part of using PostgreSQL RLS in a pooled environment is ensuring one
user's session context never leaks to another request. Trajan solves this with
`SET LOCAL`, which scopes the setting to the current **transaction** — not the
session. When the transaction commits or rolls back, the setting disappears. This
is safe with PgBouncer's transaction pooling mode because each transaction gets
an isolated context, even if the underlying connection is reused.

```python
# core/rls.py — the entire implementation
await session.execute(
    text(f"SET LOCAL app.current_user_id = '{user_id}'")
)
```

RLS policies reference this via a helper function defined in migration:

```sql
CREATE FUNCTION app_user_id() RETURNS uuid AS $$
  SELECT current_setting('app.current_user_id', true)::uuid
$$ LANGUAGE sql STABLE;

CREATE POLICY select_own ON products
  FOR SELECT USING (user_id = app_user_id());
```

The `user_id` parameter is a validated `UUID` type — only hex characters and
hyphens — so the string interpolation is safe despite not using parameterized
queries (PostgreSQL's `SET LOCAL` doesn't support `$1` placeholders).

### Dual Connection Pools

Supabase exposes PostgreSQL through two endpoints: a transaction pooler (port 6543)
for normal operations, and a direct connection (port 5432) for long-running work.
Trajan maintains separate SQLAlchemy engines for each:

```
Transaction Pooler (port 6543)           Direct Connection (port 5432)
─────────────────────────────           ────────────────────────────
pool_size=10, max_overflow=20            pool_size=3, max_overflow=5
command_timeout=60s                      command_timeout=300s
statement_cache_size=0                   Prepared statements enabled

Used for: API endpoints                 Used for: Doc generation,
(95% of traffic)                        AI analysis, migrations
```

Route handlers use `Depends(get_db)` for the pooler and `Depends(get_direct_db)`
for long operations. The distinction is invisible to domain logic.

### Generic Domain Layer

Business logic lives in operation classes that extend `BaseOperations[T]`, a
generic repository providing type-safe CRUD:

```python
class BaseOperations(Generic[ModelType]):
    def __init__(self, model: type[ModelType]):
        self.model = model

    async def get(self, db, id) -> ModelType | None: ...
    async def get_by_user(self, db, user_id, id) -> ModelType | None: ...
    async def get_multi_by_user(self, db, user_id, skip, limit) -> list[ModelType]: ...
    async def create(self, db, obj_in, user_id) -> ModelType: ...
    async def update(self, db, db_obj, obj_in) -> ModelType: ...
    async def delete(self, db, id, user_id) -> bool: ...
```

Each model extends this with domain-specific methods:

```python
class ProductOperations(BaseOperations[Product]):
    def __init__(self):
        super().__init__(Product)

    async def get_by_organization(self, db, org_id): ...
    async def get_with_relations(self, db, user_id, id): ...
    async def enable_quick_access(self, db, product): ...

# Module-level singleton — imported and used directly
product_ops = ProductOperations()
```

22 operation classes follow this pattern. Route handlers never contain SQL or
business logic — they validate input, call operations, and return responses.

### Three-Level Access Control

Access is resolved through the composition of organization roles and per-product
overrides:

```
Organization Role          Product Access Override      Effective Access
─────────────────          ──────────────────────       ────────────────
owner                      (any or none)            →   admin
admin                      (any or none)            →   admin
member                     editor                   →   editor
member                     viewer                   →   viewer
member                     none                     →   none (blocked)
viewer                     (any or none)            →   viewer
```

This lets an organization keep someone as a `member` broadly while restricting
them to `viewer` on specific products, or blocking access entirely with `none`.
Dependencies like `require_product_editor()` compose naturally in FastAPI's DI:

```python
@router.patch("/{product_id}")
async def update_product(
    product_id: UUID,
    body: ProductUpdate,
    access: ProductAccessContext = Depends(require_product_editor),
    db: DbSession,
):
    # Only reaches here if user has editor or admin access
    ...
```

### Multi-Instance Scheduling

Background jobs (email digests, auto-progress generation) run inside the FastAPI
process via APScheduler. When multiple instances are running (e.g., Fly.io
auto-scaling), PostgreSQL advisory locks prevent duplicate execution:

```python
async with advisory_lock(AUTO_PROGRESS_LOCK_ID) as acquired:
    if not acquired:
        return  # Another instance already running this job
    await auto_progress_generator.run_for_all_orgs(db)
```

`pg_try_advisory_lock()` is non-blocking — the losing instance skips immediately
rather than waiting. No Redis, no external coordinator, just PostgreSQL.

### Request-Scoped Caching

Some data (like a user's organization role) is needed multiple times per request —
once in the auth dependency, again in the route handler. A `ContextVar`-based
cache avoids redundant database queries:

```python
_request_cache: ContextVar[dict[str, Any] | None] = ContextVar(
    "request_cache", default=None
)

# In organization_ops.get_member_role():
cache_key = f"member_role:{org_id}:{user_id}"
if cached := get_request_cache_value(cache_key):
    return cached  # Skip DB query
```

Task-local (async-safe), auto-cleared between requests by middleware, no risk of
cross-request leakage.

---

## Project Structure

```
backend/
├── app/
│   ├── main.py                 # FastAPI app, lifespan, middleware
│   ├── api/
│   │   ├── router.py           # Top-level route aggregation
│   │   ├── deps/               # Dependency injection
│   │   │   ├── auth.py         # JWT validation, user resolution
│   │   │   ├── product_access.py  # Three-level access control
│   │   │   └── feature_gates.py   # Plan-based feature checks
│   │   └── v1/
│   │       ├── products/       # Product CRUD, analysis, docs
│   │       ├── organizations/  # Org management, members, settings
│   │       ├── progress/       # Commit tracking, velocity, summaries
│   │       ├── billing.py      # Stripe checkout, webhooks
│   │       ├── work_items.py   # Task tracking
│   │       ├── public_tickets.py  # Public API (API-key auth)
│   │       └── ...
│   ├── domain/                 # Business logic
│   │   ├── base_operations.py  # Generic CRUD (BaseOperations[T])
│   │   ├── product_operations.py
│   │   ├── organization_operations.py
│   │   ├── subscription_operations.py
│   │   └── ... (22 operation classes)
│   ├── models/                 # SQLModel entities
│   │   ├── base.py             # UUIDMixin, TimestampMixin, UserOwnedMixin
│   │   ├── product.py
│   │   ├── organization.py
│   │   ├── subscription.py
│   │   └── ... (22 models)
│   ├── services/               # External integrations
│   │   ├── github/             # GitHub API (httpx, HTTP/2, ETag caching)
│   │   ├── progress/           # Auto-progress, email digests
│   │   ├── email/              # Postmark transactional email
│   │   ├── interpreter/        # AI feedback interpretation
│   │   ├── scheduler.py        # APScheduler + advisory locks
│   │   ├── stripe_service.py   # Billing lifecycle
│   │   ├── analysis_orchestrator.py  # AI-powered repo analysis
│   │   └── content_generator.py     # Claude-powered doc generation
│   ├── core/                   # Infrastructure
│   │   ├── database.py         # Dual async engines (pooler + direct)
│   │   ├── rls.py              # Row-Level Security context
│   │   ├── request_cache.py    # ContextVar per-request cache
│   │   ├── rate_limit.py       # Sliding window rate limiter
│   │   ├── encryption.py       # Fernet symmetric encryption
│   │   └── security.py         # Token generation
│   ├── config/
│   │   ├── settings.py         # Pydantic settings (env vars)
│   │   └── plans.py            # Subscription tier definitions
│   └── schemas/                # Response models
├── tests/
│   ├── unit/                   # Mirrors app/ structure
│   ├── integration/            # Database + API integration tests
│   └── conftest.py
└── pyproject.toml
```

---

## Setup

```bash
cd backend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your Supabase credentials, Stripe keys, etc.

# Start the development server
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive documentation
is generated automatically:

- **OpenAPI (Swagger):** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

### Running from the monorepo root

```bash
npm run dev:backend       # Just the backend
npm run dev               # Frontend + backend concurrently
```

---

## Testing

```bash
# Unit tests (no database required)
pytest tests/unit/

# Integration tests (requires database + TRAJAN_TESTS_ENABLED=1)
TRAJAN_TESTS_ENABLED=1 pytest tests/integration/

# Single file
pytest tests/unit/domain/test_product_operations.py

# Pattern match
pytest -k "test_subscription"
```

The test suite currently includes 1,050+ backend tests across unit, integration,
and full-stack layers.

---

## Linting and Type Checking

```bash
ruff check .          # Lint
ruff format .         # Format
mypy app              # Type check (strict mode)
```

Ruff is configured for Python 3.11+ with a 100-character line length. The full
rule set includes pyflakes, pycodestyle, isort, flake8-bugbear, comprehensions,
pyupgrade, unused arguments, and simplify checks.

---

## Tech Stack

| Layer          | Technology                                              |
| -------------- | ------------------------------------------------------- |
| Framework      | FastAPI 0.109+                                          |
| ORM            | SQLModel 0.0.20+ (SQLAlchemy 2.0 async)                |
| Database       | PostgreSQL via Supabase (asyncpg driver)                |
| Auth           | Supabase JWT (ES256) with JWKS validation               |
| Security       | Row-Level Security, Fernet encryption, rate limiting    |
| AI             | Anthropic Claude (analysis, doc generation, agents)     |
| Billing        | Stripe (subscriptions, metered billing, discount codes) |
| Email          | Postmark (transactional, digest emails)                 |
| GitHub         | httpx with HTTP/2, connection pooling, ETag caching     |
| Scheduling     | APScheduler with PostgreSQL advisory locks              |
| Type checking  | mypy (strict), ruff (lint + format)                     |
| Testing        | pytest + pytest-asyncio                                 |

---

## License

See the repository root for license information.
