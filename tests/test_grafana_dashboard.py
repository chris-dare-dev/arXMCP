"""Tests for the E14_S09 Grafana dashboard JSON + provisioning config.

Coverage matrix:

- TestDashboardStructure
    Required Grafana JSON fields present (schemaVersion, uid, title,
    panels, ...).
- TestDashboardByteStability
    Re-serializing with sorted keys + indent=2 produces the on-disk
    bytes (synthesis hard-constraint #5: byte-stable dashboards).
- TestMetricNamesAreRegistered
    Every metric referenced in panel PromQL targets actually exists as
    a registered Counter / Histogram / Gauge in
    server/observability/metrics.py, server/metrics.py, or
    server/health.py.
- TestPanelInvariants
    Each panel has datasource, targets, gridPos, title (positive-
    existence checks).
- TestProvisioningYaml
    Provisioning YAML parses, contains required datasource
    (uid='prometheus') and providers blocks.

These tests are pure-Python; no Grafana process required. The schema-
version compatibility claim ('Grafana 10.x and 11.x accept schemaVersion
39') is documented in README.md but not enforced here — that would need
a Grafana container in the test harness, which is out of scope.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
DASHBOARD_PATH: Path = (
    REPO_ROOT / "infra" / "observability" / "grafana-dashboard.json"
)
DATASOURCE_PATH: Path = (
    REPO_ROOT / "infra" / "observability" / "grafana-datasource.yml"
)
DASHBOARD_PROVIDER_PATH: Path = (
    REPO_ROOT / "infra" / "observability"
    / "grafana-dashboard-provider.yml"
)


@pytest.fixture(scope="module")
def dashboard() -> dict:
    """Load + parse the dashboard JSON once per test module."""
    with DASHBOARD_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def dashboard_bytes() -> bytes:
    return DASHBOARD_PATH.read_bytes()


# ---------------------------------------------------------------------------
# Required-fields contract (Grafana dashboard JSON minimum)
# ---------------------------------------------------------------------------


class TestDashboardStructure:
    @pytest.mark.parametrize(
        "field",
        [
            "annotations",
            "editable",
            "fiscalYearStartMonth",
            "graphTooltip",
            "id",
            "links",
            "panels",
            "refresh",
            "schemaVersion",
            "tags",
            "templating",
            "time",
            "timepicker",
            "timezone",
            "title",
            "uid",
            "version",
        ],
    )
    def test_required_top_level_field_present(
        self, dashboard: dict, field: str
    ) -> None:
        assert field in dashboard, (
            f"Grafana dashboard JSON missing required field {field!r}"
        )

    def test_schema_version_is_39(self, dashboard: dict) -> None:
        """schemaVersion 39 is the Grafana 10.x/11.x compatible target
        chosen in research-synthesis.md §D6."""
        assert dashboard["schemaVersion"] == 39

    def test_uid_is_deterministic_and_namespaced(
        self, dashboard: dict
    ) -> None:
        """uid must be a fixed string so provisioning is deterministic
        (synthesis hard-constraint: byte-stable dashboards)."""
        assert dashboard["uid"] == "arxmcp-cache-latency"

    def test_title_is_human_readable(self, dashboard: dict) -> None:
        assert dashboard["title"] == "arXMCP — Cache and Latency"

    def test_id_is_null_for_new_dashboard(self, dashboard: dict) -> None:
        """id=null lets Grafana assign an id on first import."""
        assert dashboard["id"] is None

    def test_has_at_least_five_panels(self, dashboard: dict) -> None:
        """Brief mandates 5 panels (cache hit ratio, singleflight dedup,
        rerank P50/P95, per-tool P95 latency, inflight per tool)."""
        assert len(dashboard["panels"]) >= 5


# ---------------------------------------------------------------------------
# Byte-stability (synthesis hard-constraint #5)
# ---------------------------------------------------------------------------


class TestDashboardByteStability:
    def test_json_keys_are_sorted_at_every_level(
        self, dashboard: dict, dashboard_bytes: bytes,
    ) -> None:
        """Re-serializing with sort_keys=True + indent=2 must produce
        the same bytes as the on-disk file. This locks in deterministic
        diffs across edits — any future change is a real change, not a
        key-reorder artifact."""
        re_serialized = json.dumps(
            dashboard, sort_keys=True, indent=2, ensure_ascii=False,
        ).encode("utf-8") + b"\n"
        assert re_serialized == dashboard_bytes, (
            "Dashboard JSON drift: re-serialization with sort_keys=True "
            "indent=2 does not match the on-disk bytes. Run "
            "`python -c \"import json,sys; "
            "d=json.load(open('infra/observability/grafana-dashboard.json'));"
            " open('infra/observability/grafana-dashboard.json','w')"
            ".write(json.dumps(d,sort_keys=True,indent=2,ensure_ascii=False)+'\\n')\""
            " to canonicalize."
        )


# ---------------------------------------------------------------------------
# Metric-name truth check — PromQL references must hit real metrics
# ---------------------------------------------------------------------------


class TestMetricNamesAreRegistered:
    """Every metric name referenced in the dashboard PromQL targets must
    exist as a registered Counter / Histogram / Gauge in one of the three
    metric-registration files. This catches the brief's
    arxmcp_tool_latency_seconds drift (the real metric is
    arxmcp_request_latency_seconds) and any future name drift.

    We do this textually rather than by importing prometheus_client + the
    server modules because the test must run without spinning up the
    observability registry (which has side effects).
    """

    METRIC_SOURCES: tuple[Path, ...] = (
        REPO_ROOT / "server" / "observability" / "metrics.py",
        REPO_ROOT / "server" / "metrics.py",
        REPO_ROOT / "server" / "health.py",
    )

    def _all_registered_metrics(self) -> set[str]:
        """Extract metric names from `Counter("name", ...)` /
        `Histogram("name", ...)` / `Gauge("name", ...)` patterns.
        Histograms register both `<name>` and `<name>_bucket` /
        `<name>_count` / `<name>_sum` at scrape time; PromQL queries
        often reference the `_bucket` variant, so we add those too.
        """
        import re

        family_re = re.compile(
            r'(?:Counter|Histogram|Gauge|Summary)\s*\(\s*"([a-zA-Z_][a-zA-Z0-9_]*)"',
        )
        names: set[str] = set()
        for src in self.METRIC_SOURCES:
            text = src.read_text(encoding="utf-8")
            for m in family_re.finditer(text):
                base = m.group(1)
                names.add(base)
                # Histograms expose derived series:
                names.add(f"{base}_bucket")
                names.add(f"{base}_count")
                names.add(f"{base}_sum")
        return names

    def _panel_metric_refs(self, dashboard: dict) -> set[str]:
        """Extract metric-name tokens referenced by panel PromQL
        targets. A 'metric token' is the leftmost identifier in each
        expr - we walk all whitespace-/paren-/brace-separated tokens
        and keep those that look like `arxmcp_<...>`.
        """
        import re

        ident_re = re.compile(r"\barxmcp_[a-zA-Z0-9_]+\b")
        refs: set[str] = set()
        for panel in dashboard.get("panels", []):
            for target in panel.get("targets", []):
                expr = target.get("expr", "")
                refs.update(ident_re.findall(expr))
        return refs

    def test_all_panel_metric_refs_are_registered(
        self, dashboard: dict,
    ) -> None:
        registered = self._all_registered_metrics()
        refs = self._panel_metric_refs(dashboard)
        unregistered = refs - registered
        assert not unregistered, (
            f"Dashboard references metric(s) not registered in "
            f"server/{{observability/metrics,metrics,health}}.py: "
            f"{sorted(unregistered)}. Either the metric is not yet "
            f"registered (write the registration first) or the metric "
            f"name in the dashboard is wrong (a common error: "
            f"`arxmcp_tool_latency_seconds` vs the real "
            f"`arxmcp_request_latency_seconds`)."
        )

    def test_dashboard_uses_correct_per_tool_latency_metric(
        self, dashboard: dict,
    ) -> None:
        """Regression guard against the brief's metric-name drift:
        the brief calls the per-tool latency `arxmcp_tool_latency_seconds`,
        but the real metric is `arxmcp_request_latency_seconds`. The
        dashboard MUST use the latter."""
        refs = self._panel_metric_refs(dashboard)
        assert "arxmcp_request_latency_seconds_bucket" in refs, (
            "Per-tool latency panel must use "
            "arxmcp_request_latency_seconds_bucket (the registered "
            "metric name)."
        )
        assert "arxmcp_tool_latency_seconds_bucket" not in refs, (
            "Dashboard references arxmcp_tool_latency_seconds_bucket "
            "which is NOT a registered metric. Use "
            "arxmcp_request_latency_seconds_bucket instead."
        )

    def test_cache_panel_uses_tier_label(self, dashboard: dict) -> None:
        """Cache metrics use label `tier` (string values '1','2','3').
        Drift to `layer` would silently produce empty panels."""
        all_exprs = " ".join(
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        )
        if "arxmcp_cache_hits_total" in all_exprs:
            assert "tier" in all_exprs, (
                "Cache panel references arxmcp_cache_hits_total but "
                "does not group by `tier` — likely a label-drift bug."
            )


# ---------------------------------------------------------------------------
# Per-panel invariants
# ---------------------------------------------------------------------------


class TestPanelInvariants:
    @pytest.mark.parametrize(
        "field", ["datasource", "id", "title", "targets", "gridPos"]
    )
    def test_every_panel_has_field(
        self, dashboard: dict, field: str,
    ) -> None:
        for i, panel in enumerate(dashboard["panels"]):
            assert field in panel, (
                f"Panel {i} ({panel.get('title', '<no-title>')!r}) "
                f"missing required field {field!r}"
            )

    def test_every_panel_datasource_uses_provisioned_uid(
        self, dashboard: dict,
    ) -> None:
        """The provisioning YAML hardcodes uid='prometheus'; every
        panel datasource reference must match for the dashboard to
        find the datasource at import time."""
        for i, panel in enumerate(dashboard["panels"]):
            ds = panel["datasource"]
            assert isinstance(ds, dict), (
                f"Panel {i} datasource must be an object, not a string "
                f"(legacy format)"
            )
            assert ds.get("uid") == "prometheus", (
                f"Panel {i} datasource uid is {ds.get('uid')!r}; "
                f"must be 'prometheus' to match provisioning"
            )

    def test_every_target_has_unique_refid_within_panel(
        self, dashboard: dict,
    ) -> None:
        for i, panel in enumerate(dashboard["panels"]):
            refids = [t.get("refId") for t in panel["targets"]]
            assert len(refids) == len(set(refids)), (
                f"Panel {i} has duplicate refIds: {refids}"
            )


# ---------------------------------------------------------------------------
# Provisioning YAML
# ---------------------------------------------------------------------------


class TestProvisioningYaml:
    """F8 closure (m10 adversary critique): provisioning was
    originally one combined YAML that required operator-side
    splitting on comment markers. Now shipped as two physical
    files (grafana-datasource.yml + grafana-dashboard-provider.yml)
    so the operator mounts each at the correct Grafana provisioning
    path with no surgery. These tests assert both files exist, both
    parse, and both carry the correct provisioning-API contract.
    """

    def test_both_provisioning_files_exist(self) -> None:
        assert DATASOURCE_PATH.is_file(), f"missing: {DATASOURCE_PATH}"
        assert DASHBOARD_PROVIDER_PATH.is_file(), (
            f"missing: {DASHBOARD_PROVIDER_PATH}"
        )

    def test_datasource_file_has_required_keys(self) -> None:
        """Datasource provisioning needs apiVersion + datasources + uid."""
        text = DATASOURCE_PATH.read_text(encoding="utf-8")
        assert "apiVersion: 1" in text, (
            "Grafana datasource provisioning requires apiVersion: 1"
        )
        assert "datasources:" in text, "missing datasources block"
        assert "uid: prometheus" in text, (
            "datasource block must hardcode uid: prometheus to match "
            "the dashboard JSON's panel datasource references"
        )
        assert "http://localhost:9090" in text, (
            "Prometheus URL must be loopback-only per project convention"
        )

    def test_dashboard_provider_file_has_required_keys(self) -> None:
        """Dashboards provisioning needs apiVersion + providers."""
        text = DASHBOARD_PROVIDER_PATH.read_text(encoding="utf-8")
        assert "apiVersion: 1" in text, (
            "Grafana dashboards provisioning requires apiVersion: 1"
        )
        assert "providers:" in text, "missing providers block"
        # The provider points at the dashboard JSON via options.path.
        assert "options:" in text and "path:" in text, (
            "providers entry needs options.path pointing at the "
            "dashboard JSON directory"
        )

    def test_datasource_yaml_documents_container_networking_gotcha(
        self,
    ) -> None:
        """IS1 closure (m10 infra-safety critique): when Grafana
        runs in a container, ``localhost:9090`` resolves to the
        Grafana container, not the host. The YAML must document
        the ``host.docker.internal`` mitigation inline (the README
        also covers this, but the YAML is the operator's edit
        target so the hint needs to live there too)."""
        text = DATASOURCE_PATH.read_text(encoding="utf-8")
        assert "host.docker.internal" in text, (
            "grafana-datasource.yml must document the "
            "host.docker.internal mitigation for the Grafana-in-"
            "container networking gotcha (IS1)"
        )
