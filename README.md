# PR Check Agent

A **LangGraph-powered** automated agent that monitors GitHub pull requests, detects failed checks, and invokes Claude Code with failure information for analysis and fixes.

[![CI](https://github.com/feddericovonwernich/pr-checks-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/feddericovonwernich/pr-checks-agent/actions/workflows/ci.yml)
[![Deploy](https://github.com/feddericovonwernich/pr-checks-agent/actions/workflows/deploy.yml/badge.svg)](https://github.com/feddericovonwernich/pr-checks-agent/actions/workflows/deploy.yml)

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Redis (for state persistence)
- GitHub personal access token
- Anthropic API key (for Claude Code)
- Telegram bot token (for notifications)

### Installation

1. **Clone and setup:**
   ```bash
   git clone https://github.com/feddericovonwernich/pr-checks-agent.git
   cd pr-checks-agent
   chmod +x scripts/setup.sh
   ./scripts/setup.sh
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and settings
   ```

3. **Configure repositories:**
   ```bash
   # Edit config/repos.json with your repositories to monitor
   ```

4. **Run the agent:**
   ```bash
   source venv/bin/activate
   python src/main.py
   ```

### Docker Setup

```bash
# Copy environment file
cp .env.example .env
# Edit .env with your configuration

# Start with Docker Compose
docker-compose up -d
```

## 🏗️ Architecture

This agent uses **LangGraph** to implement sophisticated workflows for:

- **Repository Monitoring**: Continuous polling of GitHub PRs and check statuses
- **Failure Analysis**: Intelligent parsing of check failures and error logs  
- **Automated Fixes**: Claude Code integration with context-aware fix attempts
- **Human Escalation**: Telegram notifications when automated fixes fail
- **State Management**: Persistent workflow state across restarts

### Core Components

- **LangGraph Workflows**: Separate graphs for monitoring, PR processing, fix attempts, and escalation
- **Smart Retry Logic**: Configurable attempt limits with exponential backoff
- **Priority System**: Intelligent ordering based on check types and branch importance
- **Custom Observability**: Built-in metrics, tracing, and web dashboard

## 📊 Features

- ✅ **Multi-Repository Support**: Monitor multiple repositories simultaneously
- ✅ **Priority-Based Processing**: Handle critical checks (security, tests) first
- ✅ **Rate Limiting**: Respect GitHub API and Claude Code usage limits
- ✅ **Human-in-the-Loop**: Telegram escalation when automation fails
- ✅ **Custom Observability**: Prometheus metrics and real-time dashboard
- ✅ **Fault Tolerance**: Circuit breakers and graceful degradation
- ✅ **Secure**: Environment-based secrets, input validation, audit logging

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub personal access token | Required |
| `ANTHROPIC_API_KEY` | Claude Code API key | Required |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Required |
| `TELEGRAM_CHAT_ID` | Telegram chat/channel ID | Required |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `POLLING_INTERVAL` | Seconds between polling cycles | `300` |
| `MAX_FIX_ATTEMPTS` | Max Claude Code attempts per check | `3` |
| `ESCALATION_COOLDOWN` | Hours between repeated escalations | `24` |

### Repository Configuration

Edit `config/repos.json` to specify which repositories to monitor:

```json
{
  "repositories": [
    {
      "owner": "your-org",
      "repo": "your-repo",
      "branch_filter": ["main", "develop"],
      "check_types": ["ci", "tests", "linting"],
      "priorities": {
        "check_types": {
          "security": 1,
          "tests": 2,
          "linting": 3
        }
      }
    }
  ]
}
```

## 🏥 Monitoring & Health

### Health Checks
```bash
# Basic health check
./scripts/health-check.sh

# Detailed system information
./scripts/health-check.sh --detailed

# Via HTTP
curl http://localhost:8080/health
```

### Metrics & Dashboard
- **Prometheus metrics**: `http://localhost:8080/metrics`
- **Built-in dashboard**: `http://localhost:8080/dashboard`
- **Health endpoint**: `http://localhost:8080/health`

### Backup & Recovery
```bash
# Backup Redis state
./scripts/backup.sh

# Backups are stored in ./backups/ with automatic cleanup
```

## 🧪 Development

### Running Tests
```bash
# Install test dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

### Code Quality
```bash
# Linting and formatting with Ruff
ruff check src/ tests/
ruff format src/ tests/

# Type checking  
mypy src/
```

### LangGraph Development
```bash
# Visualize workflows
langgraph draw src/graphs/monitor_graph.py --output monitor_graph.png

# Run with tracing
python src/main.py --trace --dashboard
```

## 🚢 Deployment

### Production Considerations
- **High Availability**: Deploy multiple instances with Redis clustering
- **Resource Limits**: Configure appropriate memory and CPU constraints
- **Network Security**: Use VPN access for sensitive endpoints
- **Log Management**: Implement log rotation and centralized collection
- **Monitoring**: Set up alerting on health endpoints and metrics

### Scaling
- **Horizontal Scaling**: Multiple agent instances with Redis coordination
- **Repository Partitioning**: Distribute repositories across instances
- **Load Balancing**: Dynamic workflow distribution based on queue depth

## 📚 Documentation

- [`CLAUDE.md`](./CLAUDE.md) - Detailed technical documentation
- [`docs/architecture.md`](./docs/architecture.md) - Architecture deep dive
- [`docs/deployment.md`](./docs/deployment.md) - Production deployment guide
- [`docs/troubleshooting.md`](./docs/troubleshooting.md) - Common issues and solutions

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes and add tests
4. Run the test suite: `pytest tests/`
5. Commit your changes: `git commit -m 'Add amazing feature'`
6. Push to the branch: `git push origin feature/amazing-feature`
7. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **LangGraph** - Powerful workflow framework for AI agents
- **Claude Code** - AI-powered code analysis and fixing
- **GitHub API** - Repository and check status integration
- **Telegram Bot API** - Human escalation notifications