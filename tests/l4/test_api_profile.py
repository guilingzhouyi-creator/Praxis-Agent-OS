"""User profile API tests — handler-level contract over the side-channel."""

from __future__ import annotations

import pytest

from l3.services.user_profile import get_service, reset_service
from l4.api_handlers.api_handlers_profile import (
    handle_profile_clear,
    handle_profile_export,
    handle_profile_get,
    handle_profile_import,
    handle_profile_ingest,
    handle_profile_list,
    handle_profile_refine,
)


@pytest.fixture(autouse=True)
def _profile_on():
    reset_service()
    s = get_service()
    s.set_enabled(True)
    s.start()
    yield
    reset_service()


class TestProfileApi:
    def test_ingest_and_get(self):
        r = handle_profile_ingest({"kind": "preference", "value": "concise", "confidence": 0.8}, user_id="alice")
        assert r["success"]
        g = handle_profile_get({}, user_id="alice")
        assert g["success"]
        assert g["profile"]["count"] == 1
        assert g["profile"]["entries"][0]["value"] == "concise"

    def test_get_kinds_filter(self):
        handle_profile_ingest({"kind": "preference", "value": "x"}, user_id="a")
        handle_profile_ingest({"kind": "domain_focus", "value": "y"}, user_id="a")
        g = handle_profile_get({"kinds": "preference"}, user_id="a")
        assert g["profile"]["count"] == 1
        assert g["profile"]["kinds"] == ["preference"]

    def test_ingest_validation(self):
        assert not handle_profile_ingest({}, user_id="a")["success"]
        assert not handle_profile_ingest({"kind": "preference"}, user_id="a")["success"]
        assert not handle_profile_ingest({"kind": "nope", "value": 1}, user_id="a")["success"]
        assert not handle_profile_ingest({"kind": "preference", "value": 1, "confidence": "x"}, user_id="a")["success"]

    def test_requires_user_id(self):
        assert "user_id" in handle_profile_get({})["error"]
        assert "user_id" in handle_profile_ingest({"kind": "preference", "value": 1})["error"]

    def test_refine_via_api(self):
        for _ in range(6):
            handle_profile_ingest({"kind": "domain_focus", "value": "python"}, user_id="alice")
        r = handle_profile_refine({}, user_id="alice")
        assert r["success"] and r["refined"] == 1
        assert get_service().get_profile("alice", kinds=("trait",))["count"] == 1

    def test_export_import_clear(self):
        handle_profile_ingest({"kind": "preference", "value": "v"}, user_id="a")
        exp = handle_profile_export({}, user_id="a")
        assert exp["success"] and len(exp["payload"]["entries"]) == 1
        imp = handle_profile_import({"payload": exp["payload"]}, user_id="b")
        assert imp["success"] and imp["imported"] == 1
        assert handle_profile_list(None)["count"] >= 2
        assert handle_profile_clear({}, user_id="b")["removed"] == 1

    def test_import_validation(self):
        assert not handle_profile_import({}, user_id="a")["success"]
        assert not handle_profile_import({"payload": {"entries": "nope"}}, user_id="a")["success"]
