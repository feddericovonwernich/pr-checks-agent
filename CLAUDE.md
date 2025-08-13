# PR Check Agent

A **LangGraph-powered** automated agent that monitors GitHub pull requests, detects failed checks, and invokes Claude Code with failure information for analysis and fixes.

## Why LangGraph?

This agent uses **LangGraph** as its core framework because it provides:
- **Stateful Workflows**: Complex state management across multiple PRs and check runs
- **Cyclical Processing**: Natural support for continuous monitoring and retry loops
- **Human-in-the-Loop**: Built-in escalation and intervention capabilities
- **Multi-Actor Coordination**: Different agent components as graph nodes
- **Error Resilience**: Automatic retry mechanisms and fault tolerance
- **Observability**: Rich debugging and workflow visualization

## Overview

This agent implements a **LangGraph workflow** that continuously monitors GitHub repositories, manages complex state transitions, and coordinates between multiple processing nodes to automatically fix failing PR checks while maintaining human oversight.

## LangGraph Architecture

### Workflow Overview
The agent implements a **multi-graph architecture** with separate workflows for different concerns:

1. **Main Monitoring Graph** (`src/graphs/monitor_graph.py`)
2. **PR Processing Graph** (`src/graphs/pr_graph.py`) 
3. **Fix Attempt Graph** (`src/graphs/fix_graph.py`)
4. **Escalation Graph** (`src/graphs/escalation_graph.py`)

### Core Nodes

#### 1. Repository Scanner Node (`src/nodes/scanner.py`)
- **Function**: Polls GitHub API for repository changes
- **State Updates**: Active PRs, new PRs, closed PRs
- **Edges**: → PR Processor (new PRs), → Check Monitor (active PRs)

#### 2. Check Monitor Node (`src/nodes/monitor.py`)
- **Function**: Monitors CI/CD check status changes
- **State Updates**: Check statuses, failure events
- **Edges**: → Failure Analyzer (on failures), → Success Handler (on success)

#### 3. Failure Analyzer Node (`src/nodes/analyzer.py`)
- **Function**: Extracts failure context and determines fixability
- **State Updates**: Failure details, error classification
- **Edges**: → Claude Invoker (fixable), → Human Escalator (unfixable)

#### 4. Claude Code Invoker Node (`src/nodes/invoker.py`)
- **Function**: Invokes Claude Code with structured context
- **State Updates**: Fix attempts, success/failure status
- **Edges**: → Success Handler (fixed), → Retry Controller (failed), → Escalator (max attempts)

#### 5. Retry Controller Node (`src/nodes/retry.py`)
- **Function**: Manages retry logic and attempt counting
- **State Updates**: Attempt counters, retry delays
- **Edges**: → Claude Invoker (retry), → Escalator (threshold exceeded)

#### 6. Human Escalation Node (`src/nodes/escalation.py`)
- **Function**: Handles Telegram notifications and human intervention
- **State Updates**: Escalation status, human responses
- **Edges**: → Human Input (wait for response), → Resolution Handler (resolved)

### State Schema (`src/state/schemas.py`)
```python
from langgraph import StateGraph
from typing_extensions import TypedDict
from typing import List, Dict, Optional
from datetime import datetime

class PRState(TypedDict):
    pr_number: int
    repository: str
    branch: str
    status: str
    checks: Dict[str, CheckStatus]
    fix_attempts: Dict[str, int]
    escalations: List[EscalationRecord]
    last_updated: datetime

class CheckStatus(TypedDict):
    name: str
    status: str  # pending, success, failure
    conclusion: Optional[str]
    details_url: str
    failure_logs: Optional[str]
    
class FixAttempt(TypedDict):
    timestamp: datetime
    check_name: str
    context: str
    result: str
    success: bool
```

## Configuration

### Environment Variables
- `GITHUB_TOKEN`: GitHub personal access token with repo access
- `ANTHROPIC_API_KEY`: API key for Claude Code
- `TELEGRAM_BOT_TOKEN`: Telegram bot token for human notifications
- `TELEGRAM_CHAT_ID`: Telegram chat/channel ID for escalations
- `METRICS_PORT`: Port for Prometheus metrics endpoint (default: 8080)
- `POLLING_INTERVAL`: Seconds between polling cycles (default: 300)
- `MAX_CONCURRENT_WORKFLOWS`: Maximum parallel PR workflows (default: 10)
- `MAX_FIX_ATTEMPTS`: Maximum Claude Code fix attempts per PR/check (default: 3)
- `ESCALATION_COOLDOWN`: Hours between repeated escalations for same issue (default: 24)
- `WORKFLOW_TIMEOUT`: Maximum workflow execution time in minutes (default: 60)
- `REDIS_URL`: Redis connection string (default: redis://localhost:6379/0)
- `LOG_LEVEL`: Logging level (default: INFO)
- `WEBHOOK_SECRET`: Secret for GitHub webhook verification (optional)

### Repository Configuration (`config/repos.json`)
```json
{
  "repositories": [
    {
      "owner": "owner-name",
      "repo": "repo-name",
      "branch_filter": ["main", "develop"],
      "check_types": ["ci", "tests", "linting"],
      "claude_context": {
        "project_type": "nodejs",
        "test_framework": "jest",
        "linting": "eslint"
      },
      "fix_limits": {
        "max_attempts": 3,
        "cooldown_hours": 6,
        "escalation_enabled": true
      },
      "priorities": {
        "check_types": {
          "security": 1,
          "tests": 2,
          "linting": 3,
          "ci": 4
        },
        "branch_priority": {
          "main": 1,
          "develop": 2,
          "feature/*": 3
        }
      },
      "notifications": {
        "telegram_channel": "@repo-alerts",
        "escalation_mentions": ["@dev-lead", "@oncall"]
      }
    }
  ],
  "global_limits": {
    "max_daily_fixes": 50,
    "max_concurrent_fixes": 5,
    "rate_limits": {
      "github_api_calls_per_hour": 4000,
      "claude_invocations_per_hour": 100
    },
    "resource_limits": {
      "max_workflow_memory_mb": 512,
      "max_log_retention_days": 30
    }
  }
}
```

## Project Structure

```
pr-check-agent/
├── src/
│   ├── __init__.py
│   ├── main.py              # LangGraph application entry point
│   ├── graphs/              # LangGraph workflow definitions
│   │   ├── __init__.py
│   │   ├── monitor_graph.py # Main monitoring workflow
│   │   ├── pr_graph.py      # Per-PR processing workflow
│   │   ├── fix_graph.py     # Fix attempt workflow
│   │   └── escalation_graph.py # Human escalation workflow
│   ├── nodes/               # LangGraph node implementations
│   │   ├── __init__.py
│   │   ├── scanner.py       # Repository scanning node
│   │   ├── monitor.py       # Check monitoring node
│   │   ├── analyzer.py      # Failure analysis node
│   │   ├── invoker.py       # Claude Code invocation node
│   │   ├── retry.py         # Retry control node
│   │   └── escalation.py    # Human escalation node
│   ├── state/               # State management
│   │   ├── __init__.py
│   │   ├── schemas.py       # State type definitions
│   │   └── persistence.py   # State persistence (Redis)
│   ├── tools/               # LangGraph tools
│   │   ├── __init__.py
│   │   ├── github_tool.py   # GitHub API tool
│   │   ├── claude_tool.py   # Claude Code CLI tool
│   │   └── telegram_tool.py # Telegram notification tool
│   └── utils/
│       ├── config.py        # Configuration management
│       ├── logging.py       # Structured logging with JSON output
│       ├── monitoring.py    # Custom workflow monitoring and metrics
│       ├── tracing.py       # Custom workflow tracing
│       ├── dashboard.py     # Built-in web dashboard
│       └── metrics.py       # Prometheus metrics collection
├── config/
│   ├── repos.json           # Repository configuration
│   └── logging.conf         # Logging configuration
├── tests/
│   ├── unit/
│   │   ├── test_nodes/
│   │   ├── test_tools/
│   │   └── test_utils/
│   ├── integration/
│   │   ├── test_workflows/
│   │   └── test_end_to_end/
│   └── fixtures/
│       ├── github_responses.json
│       ├── claude_outputs.json
│       └── sample_repos.json
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Container orchestration
├── Dockerfile              # Container definition
├── README.md               # User documentation
├── .github/
│   └── workflows/
│       ├── ci.yml          # CI pipeline
│       └── deploy.yml      # Deployment automation
├── scripts/
│   ├── setup.sh           # Environment setup script
│   ├── backup.sh          # Redis backup script
│   └── health-check.sh    # Health monitoring script
└── docs/
    ├── architecture.md    # Detailed architecture docs
    ├── deployment.md      # Deployment guide
    ├── troubleshooting.md # Common issues and solutions
    └── api.md            # Dashboard API documentation
```

## Installation and Setup

### Dependencies
```bash
pip install -r requirements.txt
```

### Required Python Packages
- `langgraph` - Core workflow framework
- `langchain` - LLM integration and tools
- `prometheus-client` - Custom metrics collection
- `grafana-client` - Dashboard automation (optional)
- `requests` - GitHub API interactions
- `python-dotenv` - Environment variable management  
- `pydantic` - Data validation and models
- `redis` - State persistence with `redis-py`
- `asyncio` - Async operations
- `aiohttp` - Async HTTP client
- `python-telegram-bot` - Telegram notifications
- `click` - CLI interface
- `uvloop` - High-performance event loop
- `fastapi` - Web dashboard backend
- `websockets` - Real-time dashboard updates
- `jinja2` - Template rendering for dashboard
- `pytest-asyncio` - Async testing support

### Docker Setup
```bash
docker-compose up -d
```

## Usage

### Running the Agent
```bash
# Standard execution
python src/main.py

# With custom observability
python src/main.py --trace --dashboard

# Development mode with workflow visualization  
python src/main.py --dev --visualize
```

### Command Line Options
```bash
python src/main.py \
  --config config/repos.json \
  --log-level INFO \
  --max-concurrent-workflows 5 \
  --trace \
  --dashboard \
  --metrics-port 8080 \
  --dry-run
```

## Development

### LangGraph Development
```bash
# Run with custom tracing
python src/main.py --trace --metrics-port 8080

# Visualize workflow graphs
langgraph draw src/graphs/monitor_graph.py --output monitor_graph.png

# Monitor workflows via custom dashboard
open http://localhost:8080/dashboard

# Export workflow traces
python -m src.utils.trace_export --workflow-id pr-123 --format json
```

### Testing
```bash
python -m pytest tests/
# Test specific workflows
python -m pytest tests/test_graphs/ -v
# Test with workflow simulation
python -m pytest tests/test_integration/ --workflow-sim
```

### Linting
```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/
```

## Architecture Notes

### LangGraph State Management
- **Built-in State**: LangGraph manages workflow state automatically
- **Redis Persistence**: Custom persistence layer for cross-restart continuity
- **State Schemas**: Strongly-typed state with Pydantic models
- **Checkpointing**: Automatic workflow checkpoints for recovery
- **State Migrations**: Version-controlled state schema evolution

### Workflow Coordination
- **Multi-Graph Architecture**: Separate graphs for different concerns
- **Cross-Graph Communication**: Message passing between workflows
- **Conditional Routing**: Dynamic workflow paths based on state
- **Parallel Execution**: Concurrent PR processing with resource limits
- **Workflow Timeouts**: Automatic termination of stuck workflows

### Human-in-the-Loop Integration
- **Interrupt Points**: Pause workflows for human review
- **Approval Gates**: Require human confirmation for critical actions
- **Interactive Responses**: Handle Telegram bot interactions within workflows
- **Context Preservation**: Maintain full workflow context during escalation
- **Resume Capabilities**: Continue workflows after human intervention

### Error Handling
- **Circuit Breakers**: Prevent cascading failures from external service outages
- **Graceful Degradation**: Continue monitoring when Claude Code is unavailable
- **Retry Logic**: Exponential backoff with jitter for all external calls
- **Dead Letter Queue**: Isolate persistently failing operations
- **Health Checks**: Monitor external service health and adjust behavior
- **Fallback Modes**: Reduced functionality during partial outages
- **Error Categorization**: Different handling for transient vs permanent errors
- **Alert Thresholds**: Configurable error rate thresholds for notifications

### Security
- **Secrets Management**: API keys in environment variables, never in code/logs
- **GitHub Token Permissions**: Minimal required scopes (repo, checks)
- **Rate Limiting**: Respect GitHub API limits with exponential backoff
- **Input Validation**: Sanitize all external inputs (GitHub data, Telegram messages)
- **Network Security**: HTTPS only, secure webhook endpoints
- **Access Control**: Dashboard authentication and authorization
- **Audit Logging**: Security-relevant events logged with correlation IDs
- **Secret Rotation**: Support for rotating API keys without downtime

### Monitoring
- Health check endpoint for deployment monitoring
- Metrics export for observability
- Structured logging for debugging

## Integration Points

### GitHub API
- Uses GitHub REST API v4 for PR and check data
- Webhooks support for real-time updates (optional)
- Handles pagination for large result sets

### LangGraph Tools Integration

#### Claude Code Tool (`src/tools/claude_tool.py`)
- **LangGraph Tool**: Native tool integration with automatic state updates
- **Structured I/O**: Pydantic models for inputs and outputs
- **Error Handling**: Built-in retry and error recovery
- **Custom Observability**: Built-in tracing and metrics collection
- **Resource Management**: Concurrent invocation limits

#### GitHub API Tool (`src/tools/github_tool.py`)
- **Unified Interface**: Single tool for all GitHub operations
- **Rate Limiting**: Built-in GitHub API rate limit handling
- **Webhook Support**: Real-time updates via webhook integration
- **Pagination**: Automatic handling of paginated responses

#### Telegram Tool (`src/tools/telegram_tool.py`)
- **Interactive Messages**: Rich formatting with action buttons
- **Workflow Integration**: Direct workflow control from Telegram
- **Context Awareness**: Full PR and failure context in notifications
- **Multi-Channel Support**: Different channels for different repositories

## Deployment

### Environment Setup
1. Set required environment variables
2. Configure repository monitoring in `config/repos.json`
3. Start Redis instance for state management
4. Deploy agent with process manager (systemd/supervisor)

### Production Considerations
- **Resource Management**: Configure appropriate memory and CPU limits
- **High Availability**: Deploy multiple instances with Redis clustering
- **Backup Strategy**: Regular Redis snapshots and configuration backups
- **Network Security**: Firewall rules and VPN access for sensitive endpoints
- **Log Rotation**: Implement log rotation to prevent disk space issues
- **Graceful Shutdown**: Proper workflow termination on restart/shutdown

### Scaling
- **Horizontal Scaling**: Multiple agent instances with Redis coordination
- **Repository Partitioning**: Distribute repositories across agent instances
- **Workflow Load Balancing**: Dynamic workflow distribution based on load
- **Resource Monitoring**: Auto-scaling based on workflow queue depth

### Custom Observability
- **Built-in Dashboard**: Web UI at `/dashboard` for workflow visualization
- **Health Checks**: `/health` endpoint with detailed system status
- **Prometheus Metrics**: `/metrics` endpoint with custom workflow metrics
- **Structured Logging**: JSON logs with correlation IDs and workflow context
- **Trace Export**: Export workflow execution traces for analysis
- **Real-time Monitoring**: WebSocket-based live workflow updates

### Custom Metrics
- Workflow execution times and success rates
- Fix attempt counts and success ratios per repository
- Escalation frequency and resolution times
- GitHub API usage and rate limit tracking
- Claude Code invocation patterns and performance
- Redis state size and operation latency