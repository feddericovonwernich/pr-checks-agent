"""Tests for monitoring and observability utilities"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp.web import Application

from src.utils.monitoring import (
    MonitoringServer,
    get_monitoring_server,
    record_check_monitored,
    record_escalation,
    record_fix_attempt,
    record_github_api_call,
    record_scan,
    set_active_prs,
    set_workflow_errors,
    start_monitoring_server,
)


class TestPrometheusMetrics:
    """Test Prometheus metrics recording functions."""

    def test_record_scan_success(self):
        """Test recording successful repository scan."""
        with patch("src.utils.monitoring.PR_SCANS_TOTAL") as mock_counter:
            mock_labels = Mock()
            mock_counter.labels.return_value = mock_labels

            record_scan("test/repo", success=True)

            mock_counter.labels.assert_called_once_with(repository="test/repo", status="success")
            mock_labels.inc.assert_called_once()

    def test_record_scan_failure(self):
        """Test recording failed repository scan."""
        with patch("src.utils.monitoring.PR_SCANS_TOTAL") as mock_counter:
            mock_labels = Mock()
            mock_counter.labels.return_value = mock_labels

            record_scan("test/repo", success=False)

            mock_counter.labels.assert_called_once_with(repository="test/repo", status="error")
            mock_labels.inc.assert_called_once()

    def test_record_check_monitored(self):
        """Test recording check monitoring."""
        with patch("src.utils.monitoring.CHECKS_MONITORED_TOTAL") as mock_counter:
            mock_labels = Mock()
            mock_counter.labels.return_value = mock_labels

            record_check_monitored("test/repo", "ci", "failure")

            mock_counter.labels.assert_called_once_with(repository="test/repo", check_type="ci", status="failure")
            mock_labels.inc.assert_called_once()

    def test_record_fix_attempt_success(self):
        """Test recording successful fix attempt."""
        with (
            patch("src.utils.monitoring.FIX_ATTEMPTS_TOTAL") as mock_counter,
            patch("src.utils.monitoring.FIX_DURATION_SECONDS") as mock_histogram,
        ):
            mock_counter_labels = Mock()
            mock_counter.labels.return_value = mock_counter_labels
            mock_histogram_labels = Mock()
            mock_histogram.labels.return_value = mock_histogram_labels

            record_fix_attempt("test/repo", "tests", success=True, duration=45.7)

            # Verify counter was incremented
            mock_counter.labels.assert_called_once_with(repository="test/repo", check_type="tests", success="success")
            mock_counter_labels.inc.assert_called_once()

            # Verify histogram was updated
            mock_histogram.labels.assert_called_once_with(repository="test/repo", check_type="tests")
            mock_histogram_labels.observe.assert_called_once_with(45.7)

    def test_record_fix_attempt_failure(self):
        """Test recording failed fix attempt."""
        with (
            patch("src.utils.monitoring.FIX_ATTEMPTS_TOTAL") as mock_counter,
            patch("src.utils.monitoring.FIX_DURATION_SECONDS") as mock_histogram,
        ):
            mock_counter_labels = Mock()
            mock_counter.labels.return_value = mock_counter_labels
            mock_histogram_labels = Mock()
            mock_histogram.labels.return_value = mock_histogram_labels

            record_fix_attempt("test/repo", "ci", success=False, duration=12.3)

            mock_counter.labels.assert_called_once_with(repository="test/repo", check_type="ci", success="failure")
            mock_counter_labels.inc.assert_called_once()
            mock_histogram_labels.observe.assert_called_once_with(12.3)

    def test_record_escalation(self):
        """Test recording escalation."""
        with patch("src.utils.monitoring.ESCALATIONS_TOTAL") as mock_counter:
            mock_labels = Mock()
            mock_counter.labels.return_value = mock_labels

            record_escalation("test/repo", "max_attempts", success=True)

            mock_counter.labels.assert_called_once_with(repository="test/repo", reason="max_attempts", success="success")
            mock_labels.inc.assert_called_once()

    def test_record_github_api_call(self):
        """Test recording GitHub API call."""
        with patch("src.utils.monitoring.GITHUB_API_DURATION_SECONDS") as mock_histogram:
            mock_labels = Mock()
            mock_histogram.labels.return_value = mock_labels

            record_github_api_call("get_pr", success=True, duration=0.15)

            mock_histogram.labels.assert_called_once_with(operation="get_pr", status="success")
            mock_labels.observe.assert_called_once_with(0.15)

    def test_set_active_prs(self):
        """Test setting active PRs gauge."""
        with patch("src.utils.monitoring.ACTIVE_PRS") as mock_gauge:
            mock_labels = Mock()
            mock_gauge.labels.return_value = mock_labels

            set_active_prs("test/repo", 5)

            mock_gauge.labels.assert_called_once_with(repository="test/repo")
            mock_labels.set.assert_called_once_with(5)

    def test_set_workflow_errors(self):
        """Test setting workflow errors gauge."""
        with patch("src.utils.monitoring.WORKFLOW_ERRORS") as mock_gauge:
            mock_labels = Mock()
            mock_gauge.labels.return_value = mock_labels

            set_workflow_errors("test/repo", 2)

            mock_gauge.labels.assert_called_once_with(repository="test/repo")
            mock_labels.set.assert_called_once_with(2)


class TestMonitoringServer:
    """Test MonitoringServer class."""

    def test_monitoring_server_initialization(self):
        """Test MonitoringServer initialization."""
        server = MonitoringServer(port=9090, enable_dashboard=True)

        assert server.port == 9090
        assert server.enable_dashboard is True
        assert isinstance(server.app, Application)
        assert server.stats["start_time"] is not None
        assert server.stats["health_status"] == "healthy"
        assert server.stats["repositories"] == {}
        assert server.stats["recent_events"] == []

    def test_monitoring_server_default_initialization(self):
        """Test MonitoringServer initialization with defaults."""
        server = MonitoringServer()

        assert server.port == 8080
        assert server.enable_dashboard is False

    def test_setup_routes_basic(self):
        """Test setup_routes creates basic routes."""
        server = MonitoringServer(enable_dashboard=False)

        # Check that basic routes are present
        route_paths = [route._resource.canonical for route in server.app.router.routes()]

        assert "/health" in route_paths
        assert "/metrics" in route_paths
        assert "/api/stats" in route_paths
        assert "/api/repositories" in route_paths
        assert "/api/events" in route_paths

    def test_setup_routes_with_dashboard(self):
        """Test setup_routes creates dashboard routes when enabled."""
        server = MonitoringServer(enable_dashboard=True)

        route_paths = [route._resource.canonical for route in server.app.router.routes()]

        assert "/" in route_paths
        assert "/dashboard" in route_paths

    def test_update_repository_stats(self):
        """Test updating repository statistics."""
        server = MonitoringServer()

        # Update stats for a repository
        stats_update = {"active_prs": 3, "fixes_attempted": 5}
        server.update_repository_stats("test/repo", stats_update)

        # Verify stats were updated
        repo_stats = server.stats["repositories"]["test/repo"]
        assert repo_stats["active_prs"] == 3
        assert repo_stats["fixes_attempted"] == 5
        assert "last_updated" in repo_stats

    def test_update_repository_stats_merge(self):
        """Test updating repository stats merges with existing data."""
        server = MonitoringServer()

        # Initial update
        server.update_repository_stats("test/repo", {"active_prs": 2, "total_checks": 10})

        # Second update should merge
        server.update_repository_stats("test/repo", {"active_prs": 4, "failed_checks": 1})

        repo_stats = server.stats["repositories"]["test/repo"]
        assert repo_stats["active_prs"] == 4  # Updated
        assert repo_stats["total_checks"] == 10  # Preserved
        assert repo_stats["failed_checks"] == 1  # Added

    def test_add_event(self):
        """Test adding events to the event list."""
        server = MonitoringServer()

        server.add_event("scan", "Repository scanned successfully", repository="test/repo")

        events = server.stats["recent_events"]
        assert len(events) == 1

        event = events[0]
        assert event["type"] == "scan"
        assert event["message"] == "Repository scanned successfully"
        assert event["repository"] == "test/repo"
        assert "timestamp" in event

    def test_add_event_limit(self):
        """Test event list size limit."""
        server = MonitoringServer()

        # Add more than the limit (1000) events
        for i in range(1010):
            server.add_event("test", f"Event {i}")

        # Should only keep last 1000 events
        events = server.stats["recent_events"]
        assert len(events) == 1000

        # Should be the latest events
        assert events[0]["message"] == "Event 10"  # First kept event
        assert events[-1]["message"] == "Event 1009"  # Last event

    def test_set_health_status(self):
        """Test setting health status."""
        server = MonitoringServer()

        server.set_health_status("unhealthy")
        assert server.stats["health_status"] == "unhealthy"

        server.set_health_status("healthy")
        assert server.stats["health_status"] == "healthy"


class TestMonitoringServerEndpoints(AioHTTPTestCase):
    """Test MonitoringServer HTTP endpoints using aiohttp test utilities."""

    async def get_application(self):
        """Create application for testing."""
        server = MonitoringServer(port=8080, enable_dashboard=True)

        # Add some test data
        server.update_repository_stats("test/repo1", {"active_prs": 2, "fixes_attempted": 3})
        server.update_repository_stats("test/repo2", {"active_prs": 1, "failed_checks": 1})
        server.add_event("scan", "Test scan event", repository="test/repo1")
        server.add_event("error", "Test error event", error_type="timeout")

        return server.app

    async def test_health_check_healthy(self):
        """Test health check endpoint when healthy."""
        resp = await self.client.request("GET", "/health")

        assert resp.status == 200

        data = await resp.json()
        assert data["status"] == "healthy"
        assert data["version"] == "0.1.0"
        assert data["repositories_monitored"] == 2
        assert "timestamp" in data
        assert "uptime_seconds" in data

    async def test_health_check_unhealthy(self):
        """Test health check endpoint when unhealthy."""
        # Get the server instance and set unhealthy status
        server = MonitoringServer(port=8080, enable_dashboard=True)
        server.set_health_status("unhealthy")

        # Test using proper aiohttp testing approach
        from aiohttp.test_utils import TestClient, TestServer

        test_server = TestServer(server.app)
        async with TestClient(test_server) as client:
            resp = await client.get("/health")
            assert resp.status == 503

            data = await resp.json()
            assert data["status"] == "unhealthy"

    async def test_metrics_endpoint(self):
        """Test Prometheus metrics endpoint."""
        resp = await self.client.request("GET", "/metrics")

        assert resp.status == 200
        assert resp.content_type.startswith("text/plain")

        text = await resp.text()
        # Should contain some Prometheus metrics
        assert "pr_agent_" in text

    async def test_api_stats_endpoint(self):
        """Test API stats endpoint."""
        resp = await self.client.request("GET", "/api/stats")

        assert resp.status == 200

        data = await resp.json()
        assert "uptime_seconds" in data
        assert data["repositories_count"] == 2
        assert data["total_active_prs"] == 3  # 2 + 1 from test repos
        assert data["total_events"] == 2
        assert data["health_status"] == "healthy"

    async def test_api_repositories_endpoint(self):
        """Test API repositories endpoint."""
        resp = await self.client.request("GET", "/api/repositories")

        assert resp.status == 200

        data = await resp.json()
        assert "test/repo1" in data
        assert "test/repo2" in data
        assert data["test/repo1"]["active_prs"] == 2
        assert data["test/repo2"]["active_prs"] == 1

    async def test_api_recent_events_endpoint(self):
        """Test API recent events endpoint."""
        resp = await self.client.request("GET", "/api/events")

        assert resp.status == 200

        data = await resp.json()
        assert len(data) == 2

        # Events should be returned in order (last N events)
        event_types = [event["type"] for event in data]
        assert "scan" in event_types
        assert "error" in event_types

    async def test_api_recent_events_with_limit(self):
        """Test API recent events endpoint with limit parameter."""
        resp = await self.client.request("GET", "/api/events?limit=1")

        assert resp.status == 200

        data = await resp.json()
        assert len(data) == 1

    async def test_dashboard_index_enabled(self):
        """Test dashboard index when enabled."""
        resp = await self.client.request("GET", "/dashboard")

        assert resp.status == 200
        assert resp.content_type.startswith("text/html")

        text = await resp.text()
        assert "PR Check Agent Dashboard" in text
        assert "System Overview" in text
        assert "Repositories" in text
        assert "Recent Events" in text

    async def test_dashboard_root_redirect(self):
        """Test dashboard root path."""
        resp = await self.client.request("GET", "/")

        assert resp.status == 200
        assert resp.content_type.startswith("text/html")

    async def test_dashboard_disabled(self):
        """Test dashboard when disabled."""
        # Create server with dashboard disabled
        server = MonitoringServer(port=8080, enable_dashboard=False)

        # Test using proper aiohttp testing approach
        from aiohttp.test_utils import TestClient, TestServer

        test_server = TestServer(server.app)
        async with TestClient(test_server) as client:
            # This should return 404 since no /dashboard route is registered
            resp = await client.get("/dashboard")
            assert resp.status == 404


class TestMonitoringServerHtml:
    """Test MonitoringServer HTML generation methods."""

    def test_generate_dashboard_html_basic(self):
        """Test basic dashboard HTML generation."""
        server = MonitoringServer(enable_dashboard=True)
        server.add_event("test", "Test event")

        html = server._generate_dashboard_html()

        assert "<!DOCTYPE html>" in html
        assert "PR Check Agent Dashboard" in html
        assert "status-healthy" in html
        assert "Uptime" in html
        assert "Repositories" in html

    def test_format_repositories_html_empty(self):
        """Test repositories HTML formatting with no repositories."""
        server = MonitoringServer()

        html = server._format_repositories_html()
        assert "No repositories being monitored" in html

    def test_format_repositories_html_with_data(self):
        """Test repositories HTML formatting with repository data."""
        server = MonitoringServer()
        server.update_repository_stats("test/repo1", {"active_prs": 3})
        server.update_repository_stats("test/repo2", {"active_prs": 1})

        html = server._format_repositories_html()
        assert "test/repo1" in html
        assert "test/repo2" in html
        assert '<div class="stat-value">3</div>' in html
        assert '<div class="stat-value">1</div>' in html

    def test_format_events_html_empty(self):
        """Test events HTML formatting with no events."""
        server = MonitoringServer()

        html = server._format_events_html()
        assert "No recent events" in html

    def test_format_events_html_with_data(self):
        """Test events HTML formatting with event data."""
        server = MonitoringServer()
        server.add_event("scan", "Repository scanned")
        server.add_event("error", "Connection failed")

        html = server._format_events_html()
        assert "Repository scanned" in html
        assert "Connection failed" in html
        assert "[SCAN]" in html
        assert "[ERROR]" in html


class TestMonitoringServerLifecycle:
    """Test MonitoringServer lifecycle management."""

    @pytest.mark.asyncio
    @patch("src.utils.monitoring.web.AppRunner")
    @patch("src.utils.monitoring.web.TCPSite")
    async def test_start_monitoring_server(self, mock_tcp_site, mock_app_runner):
        """Test starting the monitoring server."""
        mock_runner = AsyncMock()
        mock_app_runner.return_value = mock_runner

        mock_site = AsyncMock()
        mock_tcp_site.return_value = mock_site

        server = MonitoringServer(port=9090, enable_dashboard=True)
        await server.start()

        # Verify runner was created and setup
        mock_app_runner.assert_called_once_with(server.app)
        mock_runner.setup.assert_called_once()

        # Verify site was created and started
        mock_tcp_site.assert_called_once_with(mock_runner, "0.0.0.0", 9090)  # noqa: S104
        mock_site.start.assert_called_once()


class TestGlobalMonitoringServer:
    """Test global monitoring server management."""

    def setup_method(self):
        """Reset global monitoring server before each test."""
        import src.utils.monitoring

        src.utils.monitoring._monitoring_server = None

    @pytest.mark.asyncio
    async def test_start_monitoring_server_global(self):
        """Test starting global monitoring server."""
        with patch("src.utils.monitoring.MonitoringServer") as mock_server_class:
            mock_server = AsyncMock()
            mock_server_class.return_value = mock_server

            result = await start_monitoring_server(port=9090, dashboard=True)

            mock_server_class.assert_called_once_with(port=9090, enable_dashboard=True)
            mock_server.start.assert_called_once()
            assert result is mock_server

    @pytest.mark.asyncio
    async def test_start_monitoring_server_singleton(self):
        """Test that global monitoring server is singleton."""
        with patch("src.utils.monitoring.MonitoringServer") as mock_server_class:
            mock_server = AsyncMock()
            mock_server_class.return_value = mock_server

            # Start server twice
            result1 = await start_monitoring_server(port=8080)
            result2 = await start_monitoring_server(port=9090)  # Different port should be ignored

            # Should only create one server instance
            mock_server_class.assert_called_once_with(port=8080, enable_dashboard=False)
            mock_server.start.assert_called_once()
            assert result1 is result2

    def test_get_monitoring_server_success(self):
        """Test getting monitoring server when it exists."""
        import src.utils.monitoring

        mock_server = Mock()
        src.utils.monitoring._monitoring_server = mock_server

        result = get_monitoring_server()
        assert result is mock_server

    def test_get_monitoring_server_not_started(self):
        """Test getting monitoring server when not started."""
        self.setup_method()  # Ensure server is None

        with pytest.raises(RuntimeError, match="Monitoring server not started"):
            get_monitoring_server()


class TestMonitoringIntegration:
    """Integration tests for monitoring functionality."""

    def test_metrics_recording_workflow(self):
        """Test complete metrics recording workflow."""
        # Test recording various metrics
        with (
            patch("src.utils.monitoring.PR_SCANS_TOTAL") as mock_scan_counter,
            patch("src.utils.monitoring.FIX_ATTEMPTS_TOTAL") as mock_fix_counter,
            patch("src.utils.monitoring.ESCALATIONS_TOTAL") as mock_esc_counter,
        ):
            # Setup mocks
            for mock_counter in [mock_scan_counter, mock_fix_counter, mock_esc_counter]:
                mock_labels = Mock()
                mock_counter.labels.return_value = mock_labels

            # Record metrics
            record_scan("test/repo", success=True)
            record_fix_attempt("test/repo", "ci", success=False, duration=30.0)
            record_escalation("test/repo", "max_attempts", success=True)

            # Verify all counters were incremented
            assert mock_scan_counter.labels.call_count == 1
            assert mock_fix_counter.labels.call_count == 1
            assert mock_esc_counter.labels.call_count == 1

    def test_monitoring_server_complete_workflow(self):
        """Test complete monitoring server workflow."""
        server = MonitoringServer(port=8080, enable_dashboard=True)

        # Step 1: Update repository stats
        server.update_repository_stats("test/repo1", {"active_prs": 2, "fixes_attempted": 5})
        server.update_repository_stats("test/repo2", {"active_prs": 3, "escalations": 1})

        # Step 2: Add events
        server.add_event("scan", "Scan completed", repository="test/repo1")
        server.add_event("fix_attempt", "Fix attempted", repository="test/repo1", success=True)
        server.add_event("escalation", "Issue escalated", repository="test/repo2")

        # Step 3: Verify aggregated stats
        total_prs = sum(repo.get("active_prs", 0) for repo in server.stats["repositories"].values())
        assert total_prs == 5

        total_events = len(server.stats["recent_events"])
        assert total_events == 3

        # Step 4: Test health status changes
        assert server.stats["health_status"] == "healthy"
        server.set_health_status("unhealthy")
        assert server.stats["health_status"] == "unhealthy"

        # Step 5: Test HTML generation
        html = server._generate_dashboard_html()
        assert "test/repo1" in html
        assert "test/repo2" in html
        assert "status-unhealthy" in html
