"""Custom monitoring and observability for PR Check Agent
Implements metrics collection, health checks, and web dashboard
"""

from datetime import datetime
from typing import Any, TypedDict

from aiohttp import web
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest


class RepositoryStats(TypedDict, total=False):
    """Type definition for repository statistics."""

    active_prs: int
    last_scan: datetime
    total_checks: int
    failed_checks: int
    fixes_attempted: int
    fixes_successful: int
    escalations: int
    errors: int


class MonitoringStats(TypedDict):
    """Type definition for monitoring statistics."""

    start_time: datetime
    repositories: dict[str, RepositoryStats]
    recent_events: list[dict[str, Any]]
    health_status: str


# Prometheus metrics
REGISTRY = CollectorRegistry()

# Counters
PR_SCANS_TOTAL = Counter(
    "pr_agent_scans_total", "Total number of repository scans", ["repository", "status"], registry=REGISTRY
)

CHECKS_MONITORED_TOTAL = Counter(
    "pr_agent_checks_monitored_total",
    "Total number of checks monitored",
    ["repository", "check_type", "status"],
    registry=REGISTRY,
)

FIX_ATTEMPTS_TOTAL = Counter(
    "pr_agent_fix_attempts_total", "Total number of fix attempts", ["repository", "check_type", "success"], registry=REGISTRY
)

ESCALATIONS_TOTAL = Counter(
    "pr_agent_escalations_total", "Total number of escalations sent", ["repository", "reason", "success"], registry=REGISTRY
)

# Histograms
FIX_DURATION_SECONDS = Histogram(
    "pr_agent_fix_duration_seconds", "Time spent on fix attempts", ["repository", "check_type"], registry=REGISTRY
)

GITHUB_API_DURATION_SECONDS = Histogram(
    "pr_agent_github_api_duration_seconds", "GitHub API call duration", ["operation", "status"], registry=REGISTRY
)

# Gauges
ACTIVE_PRS = Gauge("pr_agent_active_prs", "Number of active PRs being monitored", ["repository"], registry=REGISTRY)

WORKFLOW_ERRORS = Gauge("pr_agent_workflow_errors", "Number of consecutive workflow errors", ["repository"], registry=REGISTRY)


class MonitoringServer:
    """HTTP server for metrics, health checks, and dashboard."""

    def __init__(self, port: int = 8080, enable_dashboard: bool = False):
        self.port = port
        self.enable_dashboard = enable_dashboard
        self.app = web.Application()
        self.setup_routes()

        # In-memory stats for dashboard
        self.stats: MonitoringStats = {
            "start_time": datetime.now(),
            "repositories": {},
            "recent_events": [],
            "health_status": "healthy",
        }

    def setup_routes(self) -> None:
        """Setup HTTP routes."""
        # Health check endpoint
        self.app.router.add_get("/health", self.health_check)

        # Prometheus metrics endpoint
        self.app.router.add_get("/metrics", self.metrics_endpoint)

        # API endpoints
        self.app.router.add_get("/api/stats", self.api_stats)
        self.app.router.add_get("/api/repositories", self.api_repositories)
        self.app.router.add_get("/api/events", self.api_recent_events)

        if self.enable_dashboard:
            # Dashboard web interface
            self.app.router.add_get("/", self.dashboard_index)
            self.app.router.add_get("/dashboard", self.dashboard_index)
            self.app.router.add_static("/static", path="static", name="static")

    async def health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        health_data = {
            "status": self.stats["health_status"],
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": (datetime.now() - self.stats["start_time"]).total_seconds(),
            "version": "0.1.0",
            "repositories_monitored": len(self.stats["repositories"]),
            "recent_errors": len([event for event in self.stats["recent_events"][-10:] if event.get("type") == "error"]),
        }

        status_code = 200 if health_data["status"] == "healthy" else 503

        return web.json_response(health_data, status=status_code)

    async def metrics_endpoint(self, request: web.Request) -> web.Response:
        """Prometheus metrics endpoint."""
        metrics_output = generate_latest(REGISTRY).decode("utf-8")

        return web.Response(text=metrics_output, content_type=CONTENT_TYPE_LATEST)

    async def api_stats(self, request: web.Request) -> web.Response:
        """API endpoint for general statistics."""
        stats_data = {
            "uptime_seconds": (datetime.now() - self.stats["start_time"]).total_seconds(),
            "repositories_count": len(self.stats["repositories"]),
            "total_active_prs": sum(repo_stats.get("active_prs", 0) for repo_stats in self.stats["repositories"].values()),
            "total_events": len(self.stats["recent_events"]),
            "health_status": self.stats["health_status"],
        }

        return web.json_response(stats_data)

    async def api_repositories(self, request: web.Request) -> web.Response:
        """API endpoint for repository information."""
        return web.json_response(self.stats["repositories"])

    async def api_recent_events(self, request: web.Request) -> web.Response:
        """API endpoint for recent events."""
        limit = int(request.query.get("limit", "50"))
        events = self.stats["recent_events"][-limit:]

        return web.json_response(events)

    async def dashboard_index(self, request: web.Request) -> web.Response:
        """Dashboard web interface."""
        if not self.enable_dashboard:
            return web.Response(text="Dashboard not enabled", status=404)

        # Simple HTML dashboard
        html_content = self._generate_dashboard_html()

        return web.Response(text=html_content, content_type="text/html")

    def _generate_dashboard_html(self) -> str:
        """Generate simple HTML dashboard."""
        uptime = datetime.now() - self.stats["start_time"]

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>PR Check Agent Dashboard</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .card {{ background: white; padding: 20px; margin: 10px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .header {{ background: #2196F3; color: white; padding: 20px; border-radius: 8px; text-align: center; }}
                .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
                .stat {{ text-align: center; padding: 15px; background: #e3f2fd; border-radius: 8px; }}
                .stat-value {{ font-size: 2em; font-weight: bold; color: #1976d2; }}
                .stat-label {{ font-size: 0.9em; color: #666; margin-top: 5px; }}
                .status-healthy {{ color: #4caf50; }}
                .status-unhealthy {{ color: #f44336; }}
                .refresh-btn {{ background: #4caf50; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }}
                .event-list {{ max-height: 300px; overflow-y: auto; }}
                .event {{ padding: 10px; margin: 5px 0; background: #f9f9f9; border-radius: 4px; font-family: monospace; font-size: 0.9em; }}
            </style>
            <script>
                function refreshData() {{
                    location.reload();
                }}
                setInterval(refreshData, 30000); // Auto-refresh every 30 seconds
            </script>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 PR Check Agent Dashboard</h1>
                    <p>Status: <span class="status-{self.stats["health_status"]}">{self.stats["health_status"].upper()}</span></p>
                    <button class="refresh-btn" onclick="refreshData()">Refresh</button>
                </div>
                
                <div class="card">
                    <h2>System Overview</h2>
                    <div class="stats-grid">
                        <div class="stat">
                            <div class="stat-value">{str(uptime).split(".")[0]}</div>
                            <div class="stat-label">Uptime</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">{len(self.stats["repositories"])}</div>
                            <div class="stat-label">Repositories</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">{sum(repo.get("active_prs", 0) for repo in self.stats["repositories"].values())}</div>
                            <div class="stat-label">Active PRs</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">{len(self.stats["recent_events"])}</div>
                            <div class="stat-label">Total Events</div>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Repositories</h2>
                    {self._format_repositories_html()}
                </div>
                
                <div class="card">
                    <h2>Recent Events</h2>
                    <div class="event-list">
                        {self._format_events_html()}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    def _format_repositories_html(self) -> str:
        """Format repositories data for HTML display."""
        if not self.stats["repositories"]:
            return "<p>No repositories being monitored.</p>"

        html = '<div class="stats-grid">'

        for repo_name, repo_data in self.stats["repositories"].items():
            html += f"""
            <div class="stat">
                <div class="stat-value">{repo_data.get("active_prs", 0)}</div>
                <div class="stat-label">{repo_name}<br>Active PRs</div>
            </div>
            """

        html += "</div>"
        return html

    def _format_events_html(self) -> str:
        """Format recent events for HTML display."""
        if not self.stats["recent_events"]:
            return "<p>No recent events.</p>"

        html = ""
        for event in reversed(self.stats["recent_events"][-20:]):  # Show last 20 events
            timestamp = event.get("timestamp", "")
            event_type = event.get("type", "unknown")
            message = event.get("message", "")

            html += f"""
            <div class="event">
                <strong>{timestamp}</strong> [{event_type.upper()}] {message}
            </div>
            """

        return html

    def update_repository_stats(self, repository: str, stats: dict[str, Any]) -> None:
        """Update statistics for a repository."""
        self.stats["repositories"][repository] = {
            **self.stats["repositories"].get(repository, {}),
            **stats,
            "last_updated": datetime.now().isoformat(),
        }

    def add_event(self, event_type: str, message: str, **metadata: Any) -> None:
        """Add an event to the recent events list."""
        event = {"timestamp": datetime.now().isoformat(), "type": event_type, "message": message, **metadata}

        self.stats["recent_events"].append(event)

        # Keep only last 1000 events
        if len(self.stats["recent_events"]) > 1000:
            self.stats["recent_events"] = self.stats["recent_events"][-1000:]

    def set_health_status(self, status: str) -> None:
        """Set overall health status."""
        self.stats["health_status"] = status

    async def start(self) -> None:
        """Start the monitoring server."""
        runner = web.AppRunner(self.app)
        await runner.setup()

        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()

        logger.info(f"Monitoring server started on port {self.port}")
        if self.enable_dashboard:
            logger.info(f"Dashboard available at http://localhost:{self.port}/dashboard")


# Global monitoring server instance
_monitoring_server = None


async def start_monitoring_server(port: int = 8080, dashboard: bool = False) -> MonitoringServer:
    """Start the global monitoring server."""
    global _monitoring_server

    if _monitoring_server is None:
        _monitoring_server = MonitoringServer(port=port, enable_dashboard=dashboard)
        await _monitoring_server.start()

    return _monitoring_server


def get_monitoring_server() -> MonitoringServer:
    """Get the global monitoring server instance."""
    global _monitoring_server

    if _monitoring_server is None:
        raise RuntimeError("Monitoring server not started")

    return _monitoring_server


# Metric recording functions


def record_scan(repository: str, success: bool) -> None:
    """Record a repository scan."""
    status = "success" if success else "error"
    PR_SCANS_TOTAL.labels(repository=repository, status=status).inc()


def record_check_monitored(repository: str, check_type: str, status: str) -> None:
    """Record a check being monitored."""
    CHECKS_MONITORED_TOTAL.labels(repository=repository, check_type=check_type, status=status).inc()


def record_fix_attempt(repository: str, check_type: str, success: bool, duration: float) -> None:
    """Record a fix attempt."""
    success_label = "success" if success else "failure"
    FIX_ATTEMPTS_TOTAL.labels(repository=repository, check_type=check_type, success=success_label).inc()

    FIX_DURATION_SECONDS.labels(repository=repository, check_type=check_type).observe(duration)


def record_escalation(repository: str, reason: str, success: bool) -> None:
    """Record an escalation."""
    success_label = "success" if success else "failure"
    ESCALATIONS_TOTAL.labels(repository=repository, reason=reason, success=success_label).inc()


def record_github_api_call(operation: str, success: bool, duration: float) -> None:
    """Record a GitHub API call."""
    status = "success" if success else "error"
    GITHUB_API_DURATION_SECONDS.labels(operation=operation, status=status).observe(duration)


def set_active_prs(repository: str, count: int) -> None:
    """Set the number of active PRs for a repository."""
    ACTIVE_PRS.labels(repository=repository).set(count)


def set_workflow_errors(repository: str, count: int) -> None:
    """Set the number of consecutive workflow errors."""
    WORKFLOW_ERRORS.labels(repository=repository).set(count)
