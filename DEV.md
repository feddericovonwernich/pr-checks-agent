# Development Setup

This guide helps you set up the PR Check Agent for local development.

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Redis (or use the dockerized version)

## Quick Start

### 1. Start Dependencies Only

```bash
# Start just Redis for development
docker-compose -f docker-compose-dev.yml up -d

# Or with metrics stack (Prometheus + Grafana)
docker-compose -f docker-compose-dev.yml --profile metrics up -d
```

### 2. Set up Environment

```bash
# Copy environment template
cp .env.example .env.local

# Edit .env.local with your API keys
export $(grep -v '^#' .env.local | xargs)
```

### 3. Run the Application Locally

```bash
# Development mode with debug logging
python src/main.py --dev --dashboard --log-level DEBUG

# Or with custom config
python src/main.py -c config/repos.local.json --dev
```

## Services

### Core Dependencies
- **Redis**: `localhost:6379` - State persistence and caching
- **Redis Commander**: `http://localhost:8081` - Redis web UI (admin/admin)

### Metrics Stack (Optional)
Enable with `--profile metrics`:
- **Prometheus**: `http://localhost:9090` - Metrics collection
- **Grafana**: `http://localhost:3000` - Metrics visualization (admin/admin)

### Application Endpoints
When running locally:
- **Health Check**: `http://localhost:8080/health`
- **Metrics**: `http://localhost:8080/metrics`  
- **Dashboard**: `http://localhost:8080/dashboard`

## Configuration

### Repository Configuration
Edit `config/repos.local.json` to add repositories to monitor:

```json
{
  "repositories": [
    {
      "owner": "your-username",
      "repo": "your-repo",
      "branch_filter": ["main", "develop", "feature/*", "fix/*"],
      "check_types": ["ci", "tests", "linting", "security"]
    }
  ]
}
```

### Environment Variables
Key variables in `.env.local`:

```bash
# Required
GITHUB_TOKEN=ghp_xxx
ANTHROPIC_API_KEY=sk-ant-xxx

# Optional
REDIS_URL=redis://localhost:6379/0
LOG_LEVEL=DEBUG
TELEGRAM_BOT_TOKEN=xxx  # For notifications
```

## Cleanup

```bash
# Stop and remove containers
docker-compose -f docker-compose-dev.yml down

# Remove volumes (WARNING: deletes data)
docker-compose -f docker-compose-dev.yml down -v
```

## Troubleshooting

### Redis Connection Issues
```bash
# Check Redis is running
docker-compose -f docker-compose-dev.yml ps

# View Redis logs
docker-compose -f docker-compose-dev.yml logs redis
```

### Application Issues
```bash
# Check health endpoint
curl http://localhost:8080/health | jq

# View application logs with debug
python src/main.py --dev --log-level DEBUG
```