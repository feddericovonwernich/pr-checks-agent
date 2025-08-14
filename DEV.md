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

## Debug Logging

The PR Check Agent includes comprehensive debug logging to help troubleshoot analyzer behavior and pipeline failures.

### Analyzer Debug Logging

The analyzer node (`src/nodes/analyzer.py`) includes detailed debug logs for troubleshooting failure analysis:

#### 🔍 Context Building Logs
```bash
# View failure context building process
grep "🔍\|📦\|🔧\|⏰\|🔗" logs/pr-agent.log

# Example output:
# 🔍 Building failure context for CI Build
# 📦 Repository: owner/repo  
# 🔧 Available check_info keys: ['status', 'conclusion', 'details_url']
# ⏰ Started at: 2025-01-15T10:30:00Z
# 🔗 Details URL: https://api.github.com/repos/owner/repo/check-runs/123
```

#### 🤖 LLM Interaction Logs
```bash
# View Claude LLM analysis process
grep "🤖\|📤\|📥\|✅\|❌" logs/pr-agent.log

# Example output:
# 🤖 Sending failure to LLM for analysis...
# 📤 LLM Analysis Input:
#   - Check Name: CI Build
#   - Failure Context Length: 1247 chars
# 📥 LLM Analysis Result: {"success": true, "fixable": true}
# ✅ Analysis successful for CI Build:
#   🔧 Fixable: True
#   📋 Analysis: Build failure due to missing dependency...
#   🎯 Suggested Actions (3):
#     1. Add missing dependency to requirements.txt
#     2. Update package versions
#     3. Run tests to verify fix
```

#### 📞 GitHub API Debug Logs
```bash
# View GitHub API interactions
grep "📞\|📝\|💥\|🆔" logs/pr-agent.log

# Example output:
# 🆔 Extracted check run ID: 123456789
# 📞 Fetching detailed logs for check run ID: 123456789
# 📝 Retrieved 15 log entries
# ✅ Added detailed logs to context (15 entries)
```

#### 🤔 Decision Making Logs
```bash
# View fixability decisions
grep "🤔\|📊\|🎯\|🚫" logs/pr-agent.log

# Example output:
# 🤔 Evaluating whether to attempt fixes for 2 analysis results
# 📊 Fix evaluation results:
#   🔧 Fixable issues: 1
#   🚫 Unfixable issues: 1
# ✅ Decision: attempt_fixes (found 1 fixable issues)
# 🎯 Fixable #1: CI Build - Build failure due to missing dependency...
```

### Log Filtering Commands

Use these commands to debug specific aspects:

```bash
# All analyzer activity
grep "🔍\|🤖\|📊\|✅\|❌" logs/pr-agent.log

# Error analysis only
grep "💥\|❌\|🚫" logs/pr-agent.log

# Successful analysis only  
grep "✅\|🎯" logs/pr-agent.log

# GitHub API calls
grep "🔗\|📞\|📝" logs/pr-agent.log

# LLM interactions
grep "🤖\|📤\|📥" logs/pr-agent.log

# Decision making
grep "🤔\|📊\|⏳" logs/pr-agent.log
```

### Debug Log Levels

Set appropriate log levels for different scenarios:

```bash
# Full debug output (includes all analyzer debug logs)
export LOG_LEVEL=DEBUG
python src/main.py --dev

# Info level (shows analysis results but not detailed debug)
export LOG_LEVEL=INFO  
python src/main.py --dev

# Error level only (shows only failures)
export LOG_LEVEL=ERROR
python src/main.py --dev
```

### Troubleshooting Analyzer Issues

**Problem: Analyzer not detecting failures**
```bash
# Check if failures are being detected
grep "Analyzing failure" logs/pr-agent.log

# Verify GitHub API connectivity
grep "📞\|🔗" logs/pr-agent.log
```

**Problem: LLM analysis failing**
```bash
# Check LLM requests and responses
grep "🤖\|📤\|📥" logs/pr-agent.log

# Look for API errors
grep "❌.*LLM" logs/pr-agent.log
```

**Problem: Issues not being classified as fixable**
```bash
# View analysis results and decisions
grep "🔧\|📊\|🤔" logs/pr-agent.log

# Check confidence scores and suggested actions
grep "📊.*Confidence\|🎯.*Suggested" logs/pr-agent.log
```

**Problem: Context building failures**
```bash
# Check GitHub API log fetching
grep "💥.*logs\|❌.*fetch" logs/pr-agent.log

# Verify check run ID extraction
grep "🆔.*check run ID" logs/pr-agent.log
```