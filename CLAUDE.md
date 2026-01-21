# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Docker (Recommended)

```bash
# Start application (always includes postgres)
docker-compose up

# Run migrations in container
docker exec -it sinas-app alembic upgrade head

# Create new migration
docker exec -it sinas-app alembic revision --autogenerate -m "description"

# Access container shell
docker exec -it sinas-app sh
```

### Local Development (Without Docker)

```bash
# Install dependencies
poetry install

# Run server with hot reload
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Database migrations
poetry run alembic upgrade head
poetry run alembic revision --autogenerate -m "description"

# Code quality
poetry run black .
poetry run ruff check .
poetry run mypy .

# Tests
poetry run pytest
```

### Declarative Configuration

```bash
# Apply configuration from YAML file
curl -X POST http://localhost:8000/api/v1/config/apply \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"config\": \"$(cat config/example-simple.yaml)\"}"

# Validate configuration without applying
curl -X POST http://localhost:8000/api/v1/config/validate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"config\": \"$(cat config/example-simple.yaml)\"}"

# Dry run (preview changes without applying)
curl -X POST http://localhost:8000/api/v1/config/apply \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"config\": \"$(cat config/example-simple.yaml)\", \"dryRun\": true}"

# Auto-apply config on startup
# Set in .env:
# CONFIG_FILE=config/default-data.yaml
# AUTO_APPLY_CONFIG=true
```

### Testing Authentication

```bash
# Get token for API testing (set admin email in .env first)
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# Use in curl
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/...
```

## Architecture Overview

### Three Core Subsystems

SINAS is built around three independent but integrated subsystems:

1. **AI Chat & Assistants** - Multi-provider LLM integration with conversation management
2. **Ontology System** - Semantic data layer connecting logical concepts to physical database tables
3. **Function Execution** - Python runtime with webhooks, scheduling, and automatic tracking

### Permission System

**Format:** `sinas.{service}.{resource}.{...segments}.{action}:{scope}`

**Scope Hierarchy (automatic):**
- `:all` grants `:group` and `:own`
- `:group` grants `:own`
- Admins have `sinas.*:all` (full system access)

**Key Implementation Details:**
- `check_permission()` in `app/core/permissions.py` handles ALL permission checks
- Scope hierarchy is automatic - never manually check multiple scopes
- Wildcards supported: `sinas.ontology.*.create:group` matches any ontology resource
- Pattern matching in `matches_permission_pattern()` handles both wildcards and scope hierarchy

**Common Pattern (CORRECT):**
```python
# Only check the requested scope - hierarchy is automatic
if check_permission(permissions, f"sinas.ontology.concepts.{namespace}.{concept}.read:group"):
    # Users with :all automatically get access
```

**Anti-Pattern (WRONG):**
```python
# Never do this - inefficient and unnecessary
if check_permission(permissions, perm_group) or check_permission(permissions, perm_all):
```

### Ontology System Architecture

The ontology system connects logical **Concepts** (e.g., Customer, Order) to physical database tables via **TableMappings**.

**Core Components:**
- **Concept**: Logical entity definition with properties (name, email, etc.)
- **Property**: Attributes of a concept with data types
- **TableMapping**: Maps concept to physical table in a DataSource
  - `table_name`: Physical table/view name
  - `column_mappings`: JSON mapping property names to column names (empty = exact match)
  - `user_ownership_column`: Column for row-level :own scope filtering
  - `group_ownership_column`: Column for row-level :group scope filtering
- **DataSource**: Database connection (Postgres, Snowflake, BigQuery)

**Data Flow:**
1. LLM queries concept via `query_ontology_records(concept="Customer", filters={...})`
2. System loads Concept → TableMapping → DataSource
3. Applies column mappings to translate property names
4. Builds SQL query with ownership filters
5. Executes against external datasource
6. Returns results

**Key Files:**
- `app/models/ontology.py` - Core models (Concept, Property, TableMapping, DataSource)
- `app/services/ontology/query_executor.py` - Executes queries against datasources
- `app/services/ontology/ownership_filter.py` - Applies row-level security
- `app/api/v1/endpoints/ontology_records.py` - Query endpoints
- `app/services/ontology_tools.py` - LLM tools for querying ontology data

### Function Execution System

**Execution Flow:**
1. Function code parsed and validated
2. AST injection adds `@track` decorator to all function definitions
3. Code executed in isolated namespace with tracking and context
4. Functions can call other functions - tracked as step executions
5. All calls logged to Execution and StepExecution tables

**Function Signature:**
All functions receive two parameters:
```python
def my_function(input, context):
    """
    Args:
        input: Input data validated against input_schema
        context: Execution context dict containing:
            - user_id: Authenticated user's ID
            - user_email: User's email address
            - access_token: JWT token for making authenticated API calls
            - execution_id: Current execution ID
            - trigger_type: How function was triggered (WEBHOOK, AGENT, SCHEDULE)
            - chat_id: Optional chat ID if triggered from a chat
    """
    # Use access_token to make authenticated API calls
    import requests
    headers = {"Authorization": f"Bearer {context['access_token']}"}
    response = requests.get("http://host.docker.internal:8000/api/v1/...", headers=headers)
    return response.json()
```

**Key Components:**
- `app/services/execution_engine.py` - Core execution with AST injection for tracking
- `app/services/user_container_manager.py` - Docker container management for isolated execution
- `backend/container_executor.py` - Container runtime that executes functions
- `app/services/tracking.py` - ExecutionTracker for multi-step function calls
- `app/models/execution.py` - Execution, StepExecution models
- `app/api/v1/endpoints/webhook_handler.py` - HTTP webhook triggers

**Tracking Implementation:**
- `ASTInjector.inject_tracking_decorator()` modifies function AST to add `@track` decorators
- `TrackingDecorator` wraps function calls to record StepExecutions
- Execution tree captured: parent function → child function calls → grandchild calls, etc.

**Important:**
- Functions execute with `dill` serialization for complex types, `jsonschema` validation on inputs/outputs
- Context object is automatically injected with fresh JWT token on each execution
- Access token allows functions to make authenticated API calls back to SINAS

### Database Architecture

**Primary Database (PostgreSQL):**
- User accounts, groups, permissions
- Chat history, messages, assistants
- Ontology metadata (concepts, properties, table mappings, datasources)
- Function definitions and execution history

**Redis:**
- Execution logs (before persisting to ClickHouse)
- Real-time streaming of execution output
- Session management for OTP authentication

**ClickHouse (Optional):**
- Request logging and analytics
- HTTP request/response tracking via `RequestLoggerMiddleware`
- Table: `request_logs` (auto-created on startup)

### Startup Sequence (app/main.py)

1. Redis connection established
2. APScheduler started for cron jobs
3. Default groups created (GuestUsers, Users, Admins)
4. Superadmin user created if `SUPERADMIN_EMAIL` set and Admins group empty
5. Declarative config applied if `CONFIG_FILE` and `AUTO_APPLY_CONFIG=true`
6. MCP (Model Context Protocol) client initialized
7. Default assistants created

### Declarative Configuration (Preferred)

SINAS supports **declarative configuration** via YAML files for GitOps and Infrastructure as Code workflows.

**Configuration Files:**
- `config/default-data.yaml` - Full demo configuration (CRM ontology, functions, assistants)
- `config/example-simple.yaml` - Minimal example for testing

**Auto-Apply on Startup:**
```bash
# In .env
CONFIG_FILE=config/default-data.yaml
AUTO_APPLY_CONFIG=true
```

**Features:**
- ✅ **Idempotent** - Safe to apply multiple times
- ✅ **Change Detection** - Only updates what changed (hash-based)
- ✅ **Resource Tracking** - Marks resources as config-managed
- ✅ **Environment Variables** - Supports `${VAR_NAME}` interpolation
- ✅ **Dry Run** - Preview changes without applying
- ✅ **Validation** - Schema and reference validation before apply

**See:** `FEATURES.md` Section 14 for complete documentation

### Authentication Flow

1. User requests OTP via `/api/v1/auth/request-otp`
2. System generates 6-digit code, sends via SMTP
3. User submits OTP via `/api/v1/auth/verify-otp`
4. System returns JWT token (default expiry: 7 days)
5. Token used in `Authorization: Bearer {token}` header

### Database Migrations

**Creating Migrations:**
```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "add feature"

# Review generated migration in alembic/versions/
# Edit if needed (auto-generation may miss some changes)

# Apply migration
alembic upgrade head
```

**Migration Strategy:**
- Ontology table changes (self-managed concepts) handled by SchemaManager at runtime
- Application model changes require Alembic migrations
- Always review auto-generated migrations before applying

### Common Gotchas

1. **Permission Checking:** Always use `check_permission()`, never manually check multiple scopes. Scope hierarchy (:all → :group → :own) is automatic.

2. **Ontology Mode Confusion:** Check if concept `is_self_managed` before attempting to query. Self-managed concepts don't have ConceptQuery records.

3. **Async Context:** Most DB operations are async. Use `AsyncSession`, `await db.execute()`, and `await db.commit()`.

4. **Encryption:** DataSource connection strings are encrypted with Fernet (ENCRYPTION_KEY env var). Use `EncryptionService` for encrypt/decrypt.

5. **Function Execution:** Functions can call other functions. The ExecutionTracker builds a tree of StepExecution records. Parent execution ID must be passed through tracking context.

6. **MCP Tools:** MCP (Model Context Protocol) servers provide tools to assistants. Configured per assistant. Tools are dynamically loaded from MCP servers on startup.

7. **Query Validation:** External SQL queries are validated to prevent dangerous operations (no DROP, DELETE, INSERT, UPDATE allowed in query mode - only SELECT with JOINs).

## Key Integration Points

### Adding New Permission-Protected Endpoints

```python
from app.core.auth import get_current_user
from app.core.permissions import check_permission
from app.middleware.request_logger import set_permission_used

@router.get("/resource")
async def list_resource(
    request: Request,
    current_user_data: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    user_id, permissions = current_user_data

    # Check permission (scope hierarchy automatic)
    if not check_permission(permissions, "sinas.resource.read:group"):
        set_permission_used(request, "sinas.resource.read:group", has_perm=False)
        raise HTTPException(status_code=403, detail="Not authorized")

    set_permission_used(request, "sinas.resource.read:group", has_perm=True)
    # ... implementation
```

### Adding New Ontology Property Types

1. Add to `PropertyDataType` enum in `app/models/ontology.py`
2. Update type mapping in `SchemaManager._get_column_type()`
3. Update validation in `query_validator.py` if needed

### Adding New LLM Providers

1. Add provider to config in `app/core/config.py`
2. Implement provider client in `app/services/llm/`
3. Update provider selection in `app/services/message_service.py`
4. Add to Assistant model validation

### Adding Scheduled Jobs

Jobs can be added programmatically or via API:

```python
from app.services.scheduler import scheduler

# Via API
POST /api/v1/schedules
{
  "name": "job_name",
  "function_name": "my_function",
  "cron_expression": "0 * * * *",  # Every hour
  "input_data": {...}
}

# Programmatically
await scheduler.schedule_function(
    function_name="my_function",
    cron_expression="0 * * * *",
    input_data={...}
)
```

## Environment Variables Reference

**Required:**
- `SECRET_KEY` - JWT signing key
- `ENCRYPTION_KEY` - Fernet key for encrypting datasource credentials
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_DOMAIN` - Email for OTP

**Database:**
- `DATABASE_URL` - PostgreSQL connection string (optional, overrides local postgres)
- `DATABASE_PASSWORD` - Password for local postgres (required if DATABASE_URL not set)
- `DATABASE_USER`, `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME` - Optional postgres config
- `REDIS_URL` - Redis connection (default: redis://redis:6379/0)
- `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, etc. - ClickHouse config (optional)

**LLM Providers:**
- LLM providers are now managed via the `/api/v1/llm-providers` API (admin only)
- No environment variables needed - configure through the database after startup
- API keys are encrypted in the database using `ENCRYPTION_KEY`

**Admin:**
- `SUPERADMIN_EMAIL` - Auto-create admin user on startup if Admins group empty

**Function Execution:**
- `FUNCTION_TIMEOUT` - Max execution time in seconds (default: 300)
- `MAX_FUNCTION_MEMORY` - Max memory in MB (default: 512)
- `ALLOW_PACKAGE_INSTALLATION` - Allow pip install in functions (default: true)
