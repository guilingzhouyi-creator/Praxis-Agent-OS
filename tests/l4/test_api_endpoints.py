"""api_endpoints manifest tests — version stripping, 7-work-domain classification,
generic registration, and naming-style validation.

Covers the P1/P2 unified-prefix work:
  - _strip_version / _infer_domain (versioned endpoints classify correctly)
  - _infer_group / DOMAIN_GROUPS (7 work domains)
  - register_domain / register_group / register_endpoint (generic extension points)
  - get_endpoints(group=...) filtering
  - validate() naming-style enforcement (snake_case / trailing-slash)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestVersionStripping:
    def test_strip_v2_prefix(self):
        from l4.api.api_endpoints import _strip_version
        assert _strip_version("/api/v2/providers") == "/api/providers"
        assert _strip_version("/api/v2/stats/query") == "/api/stats/query"

    def test_strip_v1_prefix(self):
        from l4.api.api_endpoints import _strip_version
        assert _strip_version("/api/v1/commands") == "/api/commands"

    def test_unversioned_passthrough(self):
        from l4.api.api_endpoints import _strip_version
        assert _strip_version("/api/skills") == "/api/skills"

    def test_infer_domain_versioned_endpoints(self):
        """Versioned endpoints classify identically to their unversioned siblings."""
        from l4.api.api_endpoints import _infer_domain
        assert _infer_domain("/api/v2/providers") == "provider"
        assert _infer_domain("/api/v2/stats/query") == "stats"
        assert _infer_domain("/api/v2/discussion/{id}") == "discussion"
        assert _infer_domain("/api/v2/skills") == "skill"

    def test_infer_domain_unversioned(self):
        from l4.api.api_endpoints import _infer_domain
        assert _infer_domain("/api/memory/graph") == "memory"
        assert _infer_domain("/api/unknown/thing") == "misc"


class TestWorkDomainGroups:
    def test_infer_group_mapping(self):
        from l4.api.api_endpoints import _infer_group
        assert _infer_group("skill") == "tools"
        assert _infer_group("card") == "card-cell"
        assert _infer_group("provider") == "bus-services"
        assert _infer_group("memory") == "memory"
        assert _infer_group("session") == "sessions"
        assert _infer_group("security") == "kernel"
        assert _infer_group("system") == "shell"
        assert _infer_group("unknown-domain") == "misc"

    def test_domain_groups_catalogue(self):
        from l4.api.api_endpoints import DOMAIN_GROUPS
        for g in ("shell", "kernel", "memory", "sessions", "tools",
                  "card-cell", "bus-services", "misc"):
            assert g in DOMAIN_GROUPS

    def test_manifest_group_property(self):
        """ApiEndpoint.group derives from domain (not a stored field)."""
        from l4.api.api_endpoints import (
            DOMAIN_GROUPS,
            ApiEndpoint,
            ENDPOINT_MANIFEST,
        )
        ep = ApiEndpoint("GET", "/api/v2/skills", domain="skill")
        assert ep.group == "tools"
        # Every manifest entry has a known group
        unknown = {e.group for e in ENDPOINT_MANIFEST if e.group not in DOMAIN_GROUPS}
        assert unknown == set(), f"unknown groups: {unknown}"


class TestGenericRegistration:
    def test_register_domain(self):
        from l4.api.api_endpoints import register_domain, _infer_group
        r = register_domain("workflow", "tools")
        assert r["success"]
        assert _infer_group("workflow") == "tools"

    def test_register_group(self):
        from l4.api.api_endpoints import register_group
        r = register_group("edge")
        assert r["success"]
        assert "edge" in r["groups"]

    def test_register_endpoint_infers_group(self):
        from l4.api.api_endpoints import register_endpoint
        ep = register_endpoint("POST", "/api/v2/workflow/run", "mod.h", "desc",
                               domain="workflow")
        assert ep.domain == "workflow"
        assert ep.group == "tools"

    def test_register_endpoint_auto_domain(self):
        from l4.api.api_endpoints import register_endpoint
        ep = register_endpoint("GET", "/api/v2/cron/list", "mod.h", "desc")
        assert ep.domain == "cron"

    def test_get_endpoints_by_group(self):
        from l4.api.api_endpoints import get_endpoints
        tools = get_endpoints(group="tools")
        assert len(tools) > 0
        assert all(e.group == "tools" for e in tools)


class TestManifestValidation:
    def test_validate_ok_structure(self):
        from l4.api.api_endpoints import validate
        v = validate()
        assert "ok" in v
        assert "issues" in v
        assert "total" in v
        assert v["total"] > 0

    def test_validate_no_snake_case(self):
        """After the unified-prefix migration no snake_case path segments remain
        ({param} placeholder names are exempt — they mirror handler kwargs)."""
        from l4.api.api_endpoints import validate
        v = validate()
        snake = [i for i in v["issues"] if "snake_case" in i]
        assert not snake, f"unexpected snake_case violations: {snake}"

    def test_validate_no_trailing_slash(self):
        """Trailing-slash parameter style is fully migrated to {param}."""
        from l4.api.api_endpoints import validate
        v = validate()
        slash = [i for i in v["issues"] if "trailing-slash" in i]
        assert not slash, f"unexpected trailing-slash violations: {slash}"
