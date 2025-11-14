# SINAS - Semantic Intelligence & Natural Automation System

**A comprehensive AI-powered platform for building intelligent automation workflows with semantic data management, multi-LLM chat, Python execution, and advanced document processing.**

SINAS combines multiple powerful systems into a unified platform:
- 🤖 **AI Chat & Assistants** - Multi-provider LLM integration with tool calling (OpenAI, Ollama, Anthropic)
- 📊 **Ontology System** - Three-mode semantic data layer (query, sync, self-managed)
- ⚡ **Function Execution** - Sandboxed Python runtime with automatic execution tracking and call trees
- 📄 **Document Management** - Hierarchical storage with AI-powered auto-tagging
- 🏷️ **Tagging System** - Flexible metadata with LLM-based auto-tagging
- 📧 **Email Integration** - Send/receive emails with template rendering and webhook triggers
- 🌐 **Webhooks & Scheduling** - HTTP triggers and cron-based automation
- 💾 **Context Store** - Key-value memory for AI context injection
- 🔗 **MCP Integration** - Model Context Protocol for extended capabilities
- 🔐 **Fine-Grained Permissions** - Group-based access control with scope hierarchy

---

## Quick Start

### Prerequisites

- Docker & Docker Compose (recommended)
- Python 3.11+ and Poetry (for local development)

### Docker Installation (Recommended)

1. **Clone and configure:**
```bash
git clone <repository-url>
cd SINAS
cp .env.example .env
```

2. **Generate encryption key:**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

3. **Edit `.env` with required settings:**
```bash
# Security (REQUIRED)
SECRET_KEY=your-secret-key-change-in-production
ENCRYPTION_KEY=<output-from-above-command>

# Database (REQUIRED - choose one)
# Option 1: Use docker-compose postgres (easiest)
DATABASE_PASSWORD=your-secure-postgres-password

# Option 2: External database
# DATABASE_URL=postgresql://user:password@host:5432/sinas

# SMTP for OTP authentication (REQUIRED)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_DOMAIN=yourdomain.com

# Admin user (optional but recommended)
SUPERADMIN_EMAIL=admin@yourdomain.com

# Application Port (optional, default: 8000)
APP_PORT=8000
```

4. **Start the application:**
```bash
docker-compose up
```

5. **Access the API:**
- API: http://localhost:8000
- Interactive API Docs: http://localhost:8000/docs
- Alternative Docs: http://localhost:8000/redoc

6. **Login as admin:**
```bash
# Request OTP
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@yourdomain.com"}'

# Check your email for the OTP code, then verify:
curl -X POST http://localhost:8000/api/v1/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<session_id>", "otp_code": "123456"}'
```

7. **Configure LLM providers (via API):**

LLM providers are now managed through the database instead of environment variables:

```bash
# Add OpenAI provider
curl -X POST http://localhost:8000/api/v1/llm-providers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "openai-main",
    "provider_type": "openai",
    "api_key": "sk-...",
    "is_default": true
  }'

# Add Ollama provider
curl -X POST http://localhost:8000/api/v1/llm-providers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ollama-local",
    "provider_type": "ollama",
    "api_endpoint": "http://localhost:11434",
    "is_default": false
  }'

# List all providers
curl http://localhost:8000/api/v1/llm-providers \
  -H "Authorization: Bearer $TOKEN"
```

### Local Development (Without Docker)

1. **Install dependencies:**
```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
poetry install
```

2. **Setup databases:**
```bash
# PostgreSQL
createdb sinas

# Redis
redis-server

# MongoDB (optional, for document content)
# Install and start MongoDB
```

3. **Configure `.env`:**
```bash
DATABASE_URL=postgresql://postgres:password@localhost:5432/sinas
REDIS_URL=redis://localhost:6379/0
# Add other required variables from .env.example
```

4. **Run migrations:**
```bash
poetry run alembic upgrade head
```

5. **Start the server:**
```bash
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Core Features

### 🤖 AI Chat & Assistants

**Conversational AI with multiple LLM providers:**
- OpenAI (GPT-4, GPT-3.5)
- Ollama (local models)
- Anthropic Claude
- Custom endpoints

**Advanced Features:**
- Streaming responses via SSE
- Tool calling (webhooks, MCP tools, other assistants)
- Context injection from Context Store
- Ontology data access
- Custom system prompts and initial messages
- Input/output JSON schema validation
- Chat history management
- Per-message provider/model override

**Example:**
```bash
# Create assistant with tools
POST /api/v1/assistants
{
  "name": "Support Bot",
  "provider": "openai",
  "model": "gpt-4",
  "system_prompt": "You are a helpful support agent...",
  "enabled_webhooks": ["search-docs"],
  "enabled_mcp_tools": ["filesystem.read"],
  "context_namespaces": ["support-kb"],
  "ontology_concepts": ["crm.customer"]
}

# Create chat and send message
POST /api/v1/chats
{"title": "Customer Issue", "assistant_id": "..."}

POST /api/v1/chats/{id}/messages
{
  "content": "How do I reset my password?",
  "inject_context": true
}
```

### 📊 Ontology System

**Semantic data layer with three operational modes:**

#### 1. External Query Mode
Query external databases in real-time without copying data:
```bash
POST /api/v1/ontology/datasources
{
  "name": "Production DB",
  "type": "postgres",
  "conn_string": "postgresql://...",
  "group_id": "..."
}

POST /api/v1/ontology/concepts
{
  "namespace": "crm",
  "name": "customer",
  "is_self_managed": false
}

POST /api/v1/ontology/queries
{
  "concept_id": "...",
  "data_source_id": "...",
  "sql_text": "SELECT id, email, name FROM customers",
  "sync_enabled": false
}
```

#### 2. Synced Mode
Periodically sync external data to local tables:
```bash
POST /api/v1/ontology/queries
{
  "sql_text": "SELECT * FROM customers",
  "sync_enabled": true,
  "sync_schedule": "0 */6 * * *"  # Every 6 hours
}
```

#### 3. Self-Managed Mode
Full CRUD APIs auto-generated for your concepts:
```bash
POST /api/v1/ontology/concepts
{
  "namespace": "crm",
  "name": "contact",
  "is_self_managed": true
}

# Auto-generated endpoints:
POST   /api/v1/ontology/data/crm/contact      # Create
GET    /api/v1/ontology/data/crm/contact      # List
GET    /api/v1/ontology/data/crm/contact/{id} # Get
PATCH  /api/v1/ontology/data/crm/contact/{id} # Update
DELETE /api/v1/ontology/data/crm/contact/{id} # Delete
```

**Query Endpoints:**
- Configurable filters, joins, sorting, aggregations
- SQL compiled from declarative configuration
- Parameterized queries with type validation
- JSON and CSV response formats

**Schema Management:**
- Automatic table creation for self-managed concepts
- Dynamic schema migrations (add/change/remove properties)
- Column preservation on type changes
- Safe deletions (rename with timestamp)

### ⚡ Function Execution

**Python runtime with automatic tracking:**

```bash
POST /api/v1/functions
{
  "name": "process_order",
  "code": "def process_order(order_id):\n    customer = get_customer(order_id)\n    return {'status': 'processed'}",
  "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
  "output_schema": {"type": "object"},
  "requirements": ["requests>=2.28.0"]
}
```

**Key Features:**
- Functions can call other functions (automatically tracked)
- AST injection adds `@track` decorator to all function defs
- Complete execution trees (parent → child → grandchild calls)
- StepExecution records for each nested call
- Input/output validation via JSON Schema
- Package installation support
- Configurable timeout and memory limits
- Version tracking on code changes
- Dill serialization for complex types

**Execution Statuses:**
- `pending` - Queued
- `running` - Executing
- `completed` - Success
- `failed` - Error
- `awaiting_input` - Paused for user input

**View Execution Tree:**
```bash
GET /api/v1/executions/{execution_id}/steps
```

### 🌐 Webhooks & Scheduling

**HTTP Webhooks:**
```bash
POST /api/v1/webhooks
{
  "path": "process-order",
  "function_name": "process_order",
  "http_method": "POST",
  "requires_auth": true,
  "default_values": {"source": "web"}
}

# Trigger:
POST /webhooks/process-order
{"order_id": "ORD-123"}
```

**Cron Scheduling:**
```bash
POST /api/v1/schedules
{
  "name": "daily_report",
  "function_name": "generate_report",
  "cron_expression": "0 9 * * *",  # 9 AM daily
  "timezone": "America/New_York",
  "input_data": {"report_type": "sales"}
}
```

### 📄 Document Management

**Hierarchical storage with PostgreSQL metadata and MongoDB content:**

```bash
# Create folder structure
POST /api/v1/documents/folders
{
  "name": "Product Docs",
  "owner_type": "group",
  "group_id": "..."
}

# Upload document
POST /api/v1/documents
{
  "name": "API Guide",
  "content": "# API Reference\n\n...",
  "filetype": "markdown",
  "folder_id": "...",
  "auto_description_webhook_id": "..."
}

# Query with tags
GET /api/v1/documents?tags=[{"key":"category","value":"technical"}]&tag_match=AND
```

**Features:**
- User or group ownership
- Permission inheritance from folders
- Auto-description generation via webhooks
- Version tracking
- Tag-based filtering
- Multiple file types support

### 🏷️ Tagging System

**Flexible metadata with AI auto-tagging:**

```bash
# Define tag schemas
POST /api/v1/tags/definitions
{
  "name": "priority",
  "value_type": "enum",
  "allowed_values": ["low", "medium", "high"],
  "applies_to": ["document", "email"]
}

# Create AI tagger rule
POST /api/v1/tags/tagger-rules
{
  "name": "Document Auto-Tagger",
  "scope_type": "folder",
  "tag_definition_ids": ["priority_uuid", "category_uuid"],
  "assistant_id": "...",
  "folder_id": "...",
  "auto_trigger": true
}

# Bulk tag all documents in folder
POST /api/v1/tags/tagger-rules/{rule_id}/run-bulk
{
  "folder_id": "...",
  "force_retag": false
}
```

**Features:**
- Reusable tag definitions
- Value type validation (string, enum, number, boolean, date)
- AI-powered auto-tagging via assistants
- Bulk tagging operations
- Tag value counts and analytics
- AND/OR filtering

### 📧 Email Management

**Full email workflow:**

```bash
# Create template
POST /api/v1/email-templates
{
  "name": "welcome_email",
  "subject": "Welcome {{user_name}}!",
  "html_template": "<h1>Hello {{user_name}}</h1>",
  "variables": ["user_name"]
}

# Setup inbox with webhook
POST /api/v1/email-inboxes
{
  "email_address": "support@company.com",
  "webhook_id": "...",
  "auto_tagger_rule_id": "..."
}

# Send email
POST /api/v1/emails/send
{
  "to_email": "customer@example.com",
  "template_name": "welcome_email",
  "template_variables": {"user_name": "John"},
  "attachments": [...]
}
```

**Features:**
- Jinja2 template rendering
- Inbox webhooks on email receipt
- Auto-tagging of received emails
- HTML and plain text support
- Attachments (base64)
- CC/BCC support
- Delivery status tracking
- Resend capability

### 💾 Context Store

**Key-value memory for AI context injection:**

```bash
POST /api/v1/contexts
{
  "namespace": "support-kb",
  "key": "return-policy",
  "value": "Returns accepted within 30 days...",
  "visibility": "group",
  "relevance_score": 0.95,
  "tags": ["policy", "returns"],
  "expires_at": "2026-01-01T00:00:00Z"
}
```

**Features:**
- Namespace organization
- Visibility levels (private, group, public)
- Relevance scoring for ranking
- Tag-based retrieval
- Optional expiration
- Assistant-specific contexts
- Automatic injection into conversations
- Search by key/description

### 🔗 MCP Integration

**Model Context Protocol for extended capabilities:**

```bash
POST /api/v1/mcp-servers
{
  "name": "filesystem",
  "server_url": "http://localhost:3000/mcp",
  "is_active": true
}
```

Tools automatically discovered and made available to assistants.

### 🔐 Authentication & Permissions

**Passwordless OTP authentication:**
```bash
POST /api/v1/auth/login
{"email": "user@example.com"}

POST /api/v1/auth/verify-otp
{"session_id": "...", "otp_code": "123456"}
```

**API Keys for programmatic access:**
```bash
POST /api/v1/auth/api-keys
{
  "name": "Production Key",
  "permissions": {"sinas.functions.read:own": true},
  "expires_at": "2026-01-15T00:00:00Z"
}
```

**Permission System:**
- Format: `sinas.{service}.{resource}.{action}:{scope}`
- Scopes: `:all` (grants :group and :own), `:group` (grants :own), `:own`
- Automatic hierarchy resolution
- Wildcard pattern matching
- Per-request permission tracking

**Default Groups:**
- **GuestUsers** - Read-only access
- **Users** - Standard permissions (:own scope)
- **Admins** - Full access (`sinas.*:all`)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         SINAS API                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │   AI     │ │ Ontology │ │Functions │ │Documents │          │
│  │          │ │          │ │          │ │          │          │
│  │• Chats   │ │• Concepts│ │• Exec    │ │• Folders │          │
│  │• Msgs    │ │• Props   │ │• Webhooks│ │• Tags    │          │
│  │• Assists │ │• Queries │ │• Schedule│ │• Emails  │          │
│  │• Context │ │• Sync    │ │• Tracking│ │• Context │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
├─────────────────────────────────────────────────────────────────┤
│                      Core Services                               │
│  • Query Compiler & Executor    • Execution Engine              │
│  • Schema Manager               • Tag Service                   │
│  • APScheduler                  • Email Service                 │
│  • MCP Client                   • Document Service              │
└─────────────────────────────────────────────────────────────────┘
      │              │              │              │
      ▼              ▼              ▼              ▼
  PostgreSQL      Redis        ClickHouse      MongoDB
  (metadata)    (cache/logs)  (analytics)    (content)
```

---

## Configuration

### Required Environment Variables

```bash
# Security
SECRET_KEY=your-secret-key-change-in-production
ENCRYPTION_KEY=your-fernet-key  # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Database - Choose one:
POSTGRES_PASSWORD=password  # For docker-compose postgres
# OR
DATABASE_URL=postgresql://user:pass@host:5432/sinas  # External database

# SMTP (for OTP authentication)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_DOMAIN=yourdomain.com

# Admin user (created on startup if Admins group is empty)
SUPERADMIN_EMAIL=admin@yourdomain.com
```

### Optional Environment Variables

```bash
# Redis (defaults to docker-compose redis)
REDIS_URL=redis://localhost:6379/0

# MongoDB (optional, for document content storage)
MONGODB_URI=mongodb://localhost:27017/sinas

# ClickHouse (optional, for request logging)
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=9000
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=

# LLM Providers
OPENAI_API_KEY=sk-...
LOCAL_LLM_ENDPOINT=http://localhost:11434  # Ollama
DEFAULT_LLM_PROVIDER=openai

# Function Execution
FUNCTION_TIMEOUT=300  # seconds
MAX_FUNCTION_MEMORY=512  # MB
ALLOW_PACKAGE_INSTALLATION=true

# JWT Token
ACCESS_TOKEN_EXPIRE_MINUTES=10080  # 7 days
```

See `.env.example` for complete configuration options.

---

## Database Migrations

### Docker

```bash
# Run migrations
docker exec -it sinas-app alembic upgrade head

# Create new migration
docker exec -it sinas-app alembic revision --autogenerate -m "description"
```

### Local

```bash
# Run migrations
poetry run alembic upgrade head

# Create new migration
poetry run alembic revision --autogenerate -m "description"
```

**Note:** Self-managed ontology concepts use runtime schema management (SchemaManager), not Alembic migrations.

---

## API Documentation

Full API documentation available at:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **Features Guide:** [FEATURES.md](FEATURES.md) - Comprehensive feature documentation

### Key API Endpoints

**Authentication:**
- `POST /api/v1/auth/login` - Request OTP
- `POST /api/v1/auth/verify-otp` - Verify OTP, get JWT
- `POST /api/v1/auth/api-keys` - Create API key
- `GET /api/v1/auth/me` - Current user info

**AI Chat:**
- `POST /api/v1/assistants` - Create assistant
- `POST /api/v1/chats` - Create chat
- `POST /api/v1/chats/{id}/messages` - Send message
- `POST /api/v1/chats/{id}/messages/stream` - Stream response (SSE)

**Ontology:**
- `POST /api/v1/ontology/datasources` - Add data source
- `POST /api/v1/ontology/concepts` - Define concept
- `POST /api/v1/ontology/properties` - Add property
- `POST /api/v1/ontology/queries` - Configure query
- `POST /api/v1/ontology/endpoints` - Create endpoint
- `POST /api/v1/ontology/execute/{route}` - Execute query
- `POST /api/v1/ontology/data/{ns}/{concept}` - Self-managed CRUD

**Functions & Automation:**
- `POST /api/v1/functions` - Create function
- `GET /api/v1/functions/{id}/versions` - Version history
- `POST /api/v1/webhooks` - Create webhook
- `POST /api/v1/schedules` - Schedule function
- `GET /api/v1/executions` - List executions
- `GET /api/v1/executions/{id}/steps` - Execution tree

**Documents & Tags:**
- `POST /api/v1/documents/folders` - Create folder
- `POST /api/v1/documents` - Upload document
- `GET /api/v1/documents?tags=[...]` - Query by tags
- `POST /api/v1/tags/definitions` - Define tag
- `POST /api/v1/tags/tagger-rules` - Create tagger rule
- `POST /api/v1/tags/tagger-rules/{id}/run-bulk` - Bulk tag

**Email:**
- `POST /api/v1/email-templates` - Create template
- `POST /api/v1/email-inboxes` - Setup inbox
- `POST /api/v1/emails/send` - Send email
- `GET /api/v1/emails/received` - List received

**Context Store:**
- `POST /api/v1/contexts` - Create context
- `GET /api/v1/contexts` - List contexts

**Users & Groups:**
- `GET /api/v1/users` - List users
- `POST /api/v1/groups` - Create group
- `POST /api/v1/groups/{id}/members` - Add member
- `POST /api/v1/groups/{id}/permissions` - Set permission

---

## Development

### Project Structure

```
SINAS/
├── app/
│   ├── api/v1/endpoints/     # API routes
│   ├── core/                 # Auth, config, database
│   ├── models/               # SQLAlchemy models
│   ├── schemas/              # Pydantic schemas
│   ├── services/             # Business logic
│   │   ├── ontology/         # Query compiler, executor, sync
│   │   ├── execution_engine.py
│   │   ├── scheduler.py
│   │   ├── email_service.py
│   │   ├── document_service.py
│   │   └── tag_service.py
│   ├── middleware/           # Request logging, CORS
│   └── main.py               # FastAPI app
├── alembic/                  # Database migrations
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml            # Dependencies
├── CLAUDE.md                 # Development guide
├── FEATURES.md               # Feature documentation
└── .env.example              # Config template
```

### Code Quality

```bash
# Format
poetry run black .

# Lint
poetry run ruff check .

# Type check
poetry run mypy .

# Tests
poetry run pytest
```

### Docker Commands

```bash
# Start with local database
docker-compose --profile local-db up

# Start with external database
docker-compose up

# View logs
docker logs -f sinas-app

# Access shell
docker exec -it sinas-app sh

# Run migrations
docker exec -it sinas-app alembic upgrade head
```

---

## Common Workflows

### 1. Setup AI Assistant with Custom Tools

```bash
# 1. Create function
POST /api/v1/functions {...}

# 2. Create webhook
POST /api/v1/webhooks {"path": "search", "function_name": "..."}

# 3. Create assistant with webhook enabled
POST /api/v1/assistants {
  "enabled_webhooks": ["search"],
  "enabled_mcp_tools": ["filesystem.read"]
}

# 4. Create chat and send message
POST /api/v1/chats {"assistant_id": "..."}
POST /api/v1/chats/{id}/messages {"content": "Search for..."}
```

### 2. Build Ontology with External Data

```bash
# 1. Add data source
POST /api/v1/ontology/datasources

# 2. Define concept
POST /api/v1/ontology/concepts {"is_self_managed": false}

# 3. Add properties
POST /api/v1/ontology/properties

# 4. Configure query
POST /api/v1/ontology/queries {"sync_enabled": true}

# 5. Create API endpoint
POST /api/v1/ontology/endpoints

# 6. Query data
POST /api/v1/ontology/execute/{route}
```

### 3. Document Management with Auto-Tagging

```bash
# 1. Define tags
POST /api/v1/tags/definitions

# 2. Create AI assistant
POST /api/v1/assistants

# 3. Create tagger rule
POST /api/v1/tags/tagger-rules {
  "assistant_id": "...",
  "auto_trigger": true
}

# 4. Create folder
POST /api/v1/documents/folders

# 5. Upload documents (auto-tagged)
POST /api/v1/documents {"folder_id": "..."}

# 6. Query by tags
GET /api/v1/documents?tags=[{"key":"category","value":"tech"}]
```

### 4. Scheduled Email Reports

```bash
# 1. Create report function
POST /api/v1/functions

# 2. Create email template
POST /api/v1/email-templates

# 3. Schedule daily execution
POST /api/v1/schedules {
  "cron_expression": "0 8 * * *",
  "function_name": "generate_report"
}
```

---

## Security Considerations

- ✅ Passwordless OTP authentication
- ✅ JWT with configurable expiration
- ✅ API key management with scoped permissions
- ✅ Connection strings encrypted at rest (Fernet)
- ✅ SQL injection prevention via query validation
- ✅ Group-based access control with scope hierarchy
- ✅ Request logging and audit trails
- ✅ HTTPS recommended for production
- ✅ Rate limiting support (via reverse proxy)

---

## License

Dual licensed:
- **AGPL v3.0** - Open source license
- **Commercial License** - Available for proprietary use

See [LICENSE](LICENSE) for details.

---

## Support & Contributing

- **Documentation:** [FEATURES.md](FEATURES.md), [CLAUDE.md](CLAUDE.md)
- **Issues:** GitHub Issues
- **Discussions:** GitHub Discussions

For feature requests, bug reports, or questions, please open an issue on GitHub.
