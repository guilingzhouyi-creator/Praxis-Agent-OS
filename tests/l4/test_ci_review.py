"""CiReviewService tests — trigger, gates, report, events, linkages."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace


class _FakeCIService:
    """Fake L4 CIService: deterministic pipeline status."""

    def __init__(self, status="passed", steps=None, error=""):
        self._status = status
        self._steps = steps or [{"action": "ruff", "exit_code": 0}]
        self._error = error
        self.calls = []

    def run_pipeline(self, name="", steps=None, agent_id="", timeout=0.0, card_id=""):
        self.calls.append({"name": name, "steps": steps, "card_id": card_id})
        return {"success": True, "run_id": "run-1", "name": name, "status": "running",
                "step_count": len(steps or [])}

    def get_status(self, run_id):
        return {"success": True, "run_id": run_id, "status": self._status,
                "steps": self._steps, "error": self._error}


def _make_service(tmp_path, monkeypatch, settings=None):
    """Build a CiReviewService isolated to tmp_path with fake settings."""
    from l4.ci_review import CiReviewService

    svc = CiReviewService(persist_path=str(tmp_path / "ci_reviews.jsonl"))
    fake = dict(settings or {})
    monkeypatch.setattr(svc, "_setting", lambda key, default=None: fake.get(key, default))
    return svc, fake


def _make_report(card_id="card-1", verdict="PASS", agent_id="agent-writer"):
    from l4.ci_review import CardCiReport

    report = CardCiReport(card_id=card_id, run_id="run-1", state="completed",
                          verdict=verdict, agent_id=agent_id)
    report.completed_at = time.time()
    return report


class TestCore:
    def test_importable(self):
        from l4.ci_review import CiReviewService, get_service, reset_service
        assert callable(get_service)
        assert callable(reset_service)
        assert CiReviewService("ci") is not None

    def test_card_registry_listener_api(self, monkeypatch):
        from l3.card.card_registry import get_registry
        from l4.ci_review import CiReviewService

        svc = CiReviewService(persist_path="")
        reg = get_registry()
        reg.register_completion_listener(svc._on_card_completed)
        try:
            assert svc._on_card_completed in reg._completion_listeners
        finally:
            reg.unregister_completion_listener(svc._on_card_completed)
        assert svc._on_card_completed not in reg._completion_listeners

    def test_trigger_on_card_complete(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        reports = []
        monkeypatch.setattr(svc, "_do_review",
                            lambda cid, state, result: reports.append(cid))
        svc._on_card_completed("card-1", "completed", {"agent_id": "a1"})
        time.sleep(0.3)  # daemon thread scheduling
        assert reports == ["card-1"]

    def test_dedup_same_card_state(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        count = []
        monkeypatch.setattr(svc, "_do_review",
                            lambda cid, state, result: count.append(cid))
        svc._on_card_completed("card-1", "completed", {})
        svc._on_card_completed("card-1", "completed", {})
        time.sleep(0.3)
        assert len(count) == 1  # dedup within TTL window

    def test_runtime_toggle_disables_trigger(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.enabled"] = False
        count = []
        monkeypatch.setattr(svc, "_do_review",
                            lambda cid, state, result: count.append(cid))
        svc._on_card_completed("card-1", "completed", {})
        time.sleep(0.3)
        assert count == []


class TestGates:
    def test_build_steps_ruff_mypy_only_py(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        steps = svc._build_steps(["src/a.py", "README.md"])
        actions = [s["action"] for s in steps]
        assert "ruff" in actions and "mypy" in actions
        assert "src/a.py" in steps[0]["cmd"]
        assert "README.md" not in steps[0]["cmd"]

    def test_build_steps_pytest_skipped_without_tests(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        steps = svc._build_steps(["src/a.py"])
        assert all(s["action"] != "pytest" for s in steps)  # no test_ module match

    def test_path_quoting(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        steps = svc._build_steps(["src/weird name.py", "src/a;b.py"])
        cmd = steps[0]["cmd"]
        # shlex.quote wraps every path in single quotes so shell metachars
        # cannot be spliced raw into the command line.
        assert "'src/weird name.py'" in cmd
        assert "'src/a;b.py'" in cmd
        assert "src/a;b.py'" not in cmd.replace("'src/a;b.py'", "")  # no unquoted occurrence

    def test_gates_config_subset(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.gates"] = ["ruff"]
        steps = svc._build_steps(["src/a.py"])
        assert [s["action"] for s in steps] == ["ruff"]

    def test_no_files_returns_empty_steps(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        assert svc._build_steps([]) == []


class TestReport:
    def test_report_pass_verdict(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        captured = {}
        monkeypatch.setattr(svc, "_collect_changes", lambda cid, r: ["src/a.py"])
        monkeypatch.setattr(svc, "_run_and_wait", lambda cid, steps, r: (
            [{"action": "ruff", "exit_code": 0, "status": "passed"}], ""))
        monkeypatch.setattr(svc, "_persist_report",
                            lambda r: captured.update(verdict=r.verdict, error=r.error))
        monkeypatch.setattr(svc, "_dispatch_linkages", lambda r: None)
        svc._do_review("card-1", "completed", {"agent_id": "a1"})
        assert captured["verdict"] == "PASS"
        assert captured["error"] == ""

    def test_report_failed_verdict(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        monkeypatch.setattr(svc, "_collect_changes", lambda cid, r: ["src/a.py"])
        monkeypatch.setattr(svc, "_run_and_wait", lambda cid, steps, r: (
            [{"action": "ruff", "exit_code": 1, "status": "failed"}], "ruff failed"))
        captured = {}
        monkeypatch.setattr(svc, "_persist_report",
                            lambda r: captured.update(verdict=r.verdict, error=r.error))
        monkeypatch.setattr(svc, "_dispatch_linkages", lambda r: None)
        svc._do_review("card-1", "completed", {"agent_id": "a1"})
        assert captured["verdict"] == "NEEDS_CHANGES"
        assert captured["error"] == "ruff failed"

    def test_no_gates_skipped(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        captured = {}
        monkeypatch.setattr(svc, "_collect_changes", lambda cid, r: [])
        monkeypatch.setattr(svc, "_persist_report", lambda r: captured.update(r.to_dict()))
        monkeypatch.setattr(svc, "_dispatch_linkages", lambda r: None)
        svc._do_review("card-1", "completed", {})
        assert captured["verdict"] == "SKIPPED"

    def test_llm_review_optional(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.llm_review"] = True
        called = []
        monkeypatch.setattr(svc, "_collect_changes", lambda cid, r: ["src/a.py"])
        monkeypatch.setattr(svc, "_run_and_wait", lambda cid, steps, r: (
            [{"action": "ruff", "exit_code": 0, "status": "passed"}], ""))
        monkeypatch.setattr(svc, "_llm_review", lambda r: called.append(1) or {"verdict": "REJECT"})
        captured = {}
        monkeypatch.setattr(svc, "_persist_report",
                            lambda r: captured.update(verdict=r.verdict, review=r.review))
        monkeypatch.setattr(svc, "_dispatch_linkages", lambda r: None)
        svc._do_review("card-1", "completed", {"agent_id": "a1"})
        assert called == [1]
        assert captured["verdict"] == "REJECT"  # LLM downgrade

    def test_llm_review_disabled(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)  # llm_review default False
        called = []
        monkeypatch.setattr(svc, "_collect_changes", lambda cid, r: ["src/a.py"])
        monkeypatch.setattr(svc, "_run_and_wait", lambda cid, steps, r: (
            [{"action": "ruff", "exit_code": 0, "status": "passed"}], ""))
        monkeypatch.setattr(svc, "_llm_review", lambda r: called.append(1))
        captured = {}
        monkeypatch.setattr(svc, "_persist_report",
                            lambda r: captured.update(verdict=r.verdict, review=r.review))
        monkeypatch.setattr(svc, "_dispatch_linkages", lambda r: None)
        svc._do_review("card-1", "completed", {})
        assert called == []
        assert captured["verdict"] == "PASS"

    def test_run_and_wait_uses_fake_pipeline(self, tmp_path, monkeypatch):
        from l4 import ci as ci_module
        from l4 import ci_review

        svc, _ = _make_service(tmp_path, monkeypatch)
        fake = _FakeCIService(status="passed")
        monkeypatch.setattr(ci_module, "get_service", lambda: fake)
        monkeypatch.setattr(ci_review, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
        gates, error = svc._run_and_wait("card-1", [{"action": "ruff", "cmd": "x"}], {})
        assert error == ""
        assert gates[0]["exit_code"] == 0
        assert fake.calls[0]["card_id"] == "card-1"


class TestPersistenceEvents:
    def test_persist_jsonl(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        monkeypatch.setattr(svc, "_emit_events", lambda r: None)
        svc._persist_report(_make_report("card-9", "PASS"))
        lines = (tmp_path / "ci_reviews.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["card_id"] == "card-9"
        assert payload["verdict"] == "PASS"

    def test_r4_archive_fonds(self, tmp_path, monkeypatch):
        import l3.tools._archive as archive_mod

        svc, _ = _make_service(tmp_path, monkeypatch)
        calls = []

        def fake_store(fonds, series, content, tags=""):
            calls.append({"fonds": fonds, "series": series})
            return {"success": True, "archive_ref": f"{fonds}:{series}:1"}

        monkeypatch.setattr(archive_mod, "_cmd_archive_store", fake_store)
        monkeypatch.setattr(svc, "_emit_events", lambda r: None)
        report = _make_report("card-9", "PASS")
        svc._persist_report(report)
        assert calls and calls[0]["fonds"] == "ci"
        assert calls[0]["series"] == "reviews"
        assert report.archive_ref == "ci:reviews:1"

    def test_events_emitted(self, tmp_path, monkeypatch):
        import l1.kernel as kernel
        import l3.bus.monitor_bus as monitor_bus

        svc, _ = _make_service(tmp_path, monkeypatch)
        bus_events, monitor_events = [], []

        class _FakeEventBus:
            def emit_event(self, *a, **k):
                bus_events.append(a)

        class _FakeMonitorBus:
            def emit(self, ev):
                monitor_events.append(ev)

        monkeypatch.setattr(kernel, "get_event_bus", lambda: _FakeEventBus())
        monkeypatch.setattr(monitor_bus, "get_bus", lambda: _FakeMonitorBus())
        svc._emit_events(_make_report("card-9", "PASS"))
        assert any(e[0] == "ci.review.completed" for e in bus_events)
        assert monitor_events and monitor_events[0].type == "ci.card.review"

    def test_query_and_stats(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        monkeypatch.setattr(svc, "_emit_events", lambda r: None)
        svc._persist_report(_make_report("card-a", "PASS"))
        svc._persist_report(_make_report("card-b", "NEEDS_CHANGES"))
        q = svc.query(status="PASS")
        assert q["count"] == 1 and q["reports"][0]["card_id"] == "card-a"
        assert svc.stats()["total"] == 2


class TestLinkages:
    def test_dispatch_approval_escalation(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.escalate_reject"] = True
        calls = []
        monkeypatch.setattr(svc, "_link_approval", lambda r: calls.append(r.verdict))
        svc._dispatch_linkages(_make_report("c1", "REJECT"))
        assert calls == ["REJECT"]

    def test_dispatch_approval_off_by_default(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        calls = []
        monkeypatch.setattr(svc, "_link_approval", lambda r: calls.append(r.verdict))
        svc._dispatch_linkages(_make_report("c1", "REJECT"))
        assert calls == []

    def test_dispatch_convention_route(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.route_convention"] = True
        calls = []
        monkeypatch.setattr(svc, "_link_convention", lambda r: calls.append(r.verdict))
        svc._dispatch_linkages(_make_report("c1", "NEEDS_CHANGES"))
        assert calls == ["NEEDS_CHANGES"]

    def test_reputation_llm_only(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.reputation"] = True
        calls = []
        monkeypatch.setattr(svc, "_link_reputation", lambda r: calls.append(r.verdict))
        report = _make_report("c1", "PASS")
        report.review = {"verdict": "PASS"}  # LLM review present
        svc._dispatch_linkages(report)
        assert calls == ["PASS"]
        calls.clear()
        machine_only = _make_report("c2", "PASS")  # no LLM review
        svc._dispatch_linkages(machine_only)
        assert calls == []  # machine gates never touch reputation

    def test_dispatch_lean_trace_optional(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.lean_trace"] = True
        calls = []
        monkeypatch.setattr(svc, "_link_lean_trace", lambda r: calls.append(r.verdict))
        svc._dispatch_linkages(_make_report("c1", "NEEDS_CHANGES"))
        assert calls == ["NEEDS_CHANGES"]
        calls.clear()
        svc._dispatch_linkages(_make_report("c2", "PASS"))
        assert calls == []

    def test_dispatch_notify_on_reject(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.notify.enabled"] = True
        calls = []
        monkeypatch.setattr(svc, "_link_notify", lambda r: calls.append(r.verdict))
        svc._dispatch_linkages(_make_report("c1", "REJECT"))
        assert calls == ["REJECT"]
        calls.clear()
        svc._dispatch_linkages(_make_report("c2", "PASS"))
        assert calls == []

    def test_link_approval_calls_gate(self, tmp_path, monkeypatch):
        import l3.card.approval_gate as approval_mod

        svc, _ = _make_service(tmp_path, monkeypatch)
        requests = []

        class _FakeGate:
            def request(self, tool_name, agent_id, args, reason=""):
                requests.append({"tool": tool_name, "agent": agent_id, "args": args})

        monkeypatch.setattr(approval_mod, "get_gate", lambda: _FakeGate())
        svc._link_approval(_make_report("c1", "REJECT", agent_id="agent-writer"))
        assert requests and requests[0]["tool"] == "ci.review"
        assert requests[0]["args"]["card_id"] == "c1"

    def test_link_notify_calls_service(self, tmp_path, monkeypatch):
        import l4.notify as notify_mod

        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.notify.channel"] = "log"
        sent = []

        class _FakeNotify:
            def send(self, channel, to, subject, body):
                sent.append({"channel": channel, "to": to})

        monkeypatch.setattr(notify_mod, "get_service", lambda: _FakeNotify())
        svc._link_notify(_make_report("c1", "REJECT", agent_id="agent-writer"))
        assert sent and sent[0]["channel"] == "log"
        assert sent[0]["to"] == "agent-writer"

    def test_linkage_failure_nonblocking(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.escalate_reject"] = True
        fake["ci.review.notify.enabled"] = True

        def boom(report):
            raise RuntimeError("consumer down")

        monkeypatch.setattr(svc, "_link_approval", boom)
        notified = []
        monkeypatch.setattr(svc, "_link_notify", lambda r: notified.append(r.verdict))
        svc._dispatch_linkages(_make_report("c1", "REJECT"))  # must not raise
        assert notified == ["REJECT"]  # other consumers still ran

    def test_concurrency_cap_exists(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        assert svc._semaphore._value == 2  # CI_REVIEW_MAX_CONCURRENT


class _FakeCenter:
    """Fake SettingsCenter with default ci.* values."""

    DEFAULTS = {
        "ci.review.enabled": True,
        "ci.review.auto_trigger": True,
        "ci.review.llm_review": False,
        "ci.review.gates": ["ruff"],
        "ci.control.api.writable": True,
        "ci.control.shell.writable": True,
    }

    def __init__(self):
        self.d = dict(self.DEFAULTS)

    def get(self, key, default=None):
        return self.d.get(key, default)

    def set(self, key, value):
        self.d[key] = value


class _FakeControlSvc:
    """Fake CiReviewService exposing the control-plane + scope surfaces."""

    def __init__(self, center):
        self._center = center

    def _surface_writable(self, surface):
        return bool(self._center.get(f"ci.control.{surface}.writable", True))

    def _effective(self, suffix, agent_id="", cell_id="", default=None):
        for scope_key in (f"ci.review.agent.{agent_id}.{suffix}" if agent_id else "",
                          f"ci.review.cell.{cell_id}.{suffix}" if cell_id else ""):
            if scope_key and scope_key in self._center.d:
                return self._center.d[scope_key]
        return self._center.get(f"ci.review.{suffix}", default)


class TestControlPlane:
    """Fine-grained switch control: sub-keys + per-surface write permission."""

    def _install(self, monkeypatch):
        from l3.config import settings_center as sc_mod
        from l4 import ci_review as cr_mod

        center = _FakeCenter()
        svc = _FakeControlSvc(center)
        monkeypatch.setattr(sc_mod, "get_center", lambda: center)
        monkeypatch.setattr(cr_mod, "get_service", lambda: svc)
        return center, svc

    def test_api_get_config(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_get

        self._install(monkeypatch)
        r = handle_ci_config_get({})
        assert r["success"] is True
        assert r["settings"]["ci.review.enabled"] is True
        assert r["control"] == {"api": {"writable": True}, "shell": {"writable": True}}

    def test_api_put_subkey(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_set

        center, _ = self._install(monkeypatch)
        r = handle_ci_config_set({"key": "ci.review.llm_review", "value": True})
        assert r["success"] is True
        assert center.d["ci.review.llm_review"] is True

    def test_api_put_batch(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_set

        center, _ = self._install(monkeypatch)
        r = handle_ci_config_set({"enabled": False, "auto_trigger": False})
        assert r["success"] is True
        assert center.d["ci.review.enabled"] is False
        assert center.d["ci.review.auto_trigger"] is False

    def test_api_put_reject_outside_whitelist(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_set

        center, _ = self._install(monkeypatch)
        r = handle_ci_config_set({"key": "ci.control.api.writable", "value": False})
        assert r["success"] is False
        # v3: control-plane keys are whitelisted but need admin confirmation.
        assert "admin" in r["error"]
        assert center.d["ci.control.api.writable"] is True  # unchanged

    def test_api_write_disabled_read_still_ok(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import (
            handle_ci_config_get,
            handle_ci_config_set,
        )

        center, _ = self._install(monkeypatch)
        center.d["ci.control.api.writable"] = False
        r_set = handle_ci_config_set({"enabled": False})
        assert r_set["success"] is False
        assert "writes disabled" in r_set["error"]
        r_get = handle_ci_config_get({})
        assert r_get["success"] is True  # reads never gated

    def test_shell_set_subkey(self, monkeypatch):
        from l2.l2_shell.commands.ci import _cmd_ci

        center, _ = self._install(monkeypatch)
        r = _cmd_ci(["set", "llm_review", "true"])
        assert r["success"] is True
        assert center.d["ci.review.llm_review"] is True

    def test_shell_write_disabled_read_still_ok(self, monkeypatch):
        from l2.l2_shell.commands.ci import _cmd_ci

        center, _ = self._install(monkeypatch)
        center.d["ci.control.shell.writable"] = False
        r_set = _cmd_ci(["set", "enabled", "false"])
        assert r_set["success"] is False
        assert "writes disabled" in r_set["error"]
        r_toggle = _cmd_ci(["toggle"])
        assert r_toggle["success"] is False
        r_config = _cmd_ci(["config"])
        assert r_config["success"] is True  # reads never gated

    def test_shell_set_reject_outside_whitelist(self, monkeypatch):
        from l2.l2_shell.commands.ci import _cmd_ci

        center, _ = self._install(monkeypatch)
        r = _cmd_ci(["set", "ci.control.shell.writable", "false"])
        assert r["success"] is False
        assert center.d["ci.control.shell.writable"] is True  # unchanged

    def test_shell_toggle_switches_master(self, monkeypatch):
        from l2.l2_shell.commands.ci import _cmd_ci

        center, _ = self._install(monkeypatch)
        r = _cmd_ci(["toggle"])
        assert r["success"] is True and r["enabled"] is False
        assert center.d["ci.review.enabled"] is False


class TestScopeApi:
    """v3 scoped writes via API: cell/agent scope + admin-gated control keys."""

    def _install(self, monkeypatch):
        from l3.config import settings_center as sc_mod
        from l4 import ci_review as cr_mod

        center = _FakeCenter()
        svc = _FakeControlSvc(center)
        monkeypatch.setattr(sc_mod, "get_center", lambda: center)
        monkeypatch.setattr(cr_mod, "get_service", lambda: svc)
        return center, svc

    def test_scope_put_cell(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_set

        center, _ = self._install(monkeypatch)
        r = handle_ci_config_set({"key": "enabled", "value": False,
                                  "scope": {"cell": "cell-sp1"}})
        assert r["success"] is True
        assert center.d["ci.review.cell.cell-sp1.enabled"] is False

    def test_scope_put_agent(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_set

        center, _ = self._install(monkeypatch)
        r = handle_ci_config_set({"key": "llm_review", "value": True,
                                  "scope": {"agent": "agent-writer"}})
        assert r["success"] is True
        assert center.d["ci.review.agent.agent-writer.llm_review"] is True

    def test_scope_get_effective(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_get

        center, _ = self._install(monkeypatch)
        center.d["ci.review.cell.cell-sp1.enabled"] = False
        r = handle_ci_config_get({"cell_id": "cell-sp1"})
        assert r["success"] is True
        assert r["effective"]["enabled"] is False
        assert r["settings"]["ci.review.enabled"] is True  # global unchanged

    def test_scope_key_injection_rejected(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_set

        center, _ = self._install(monkeypatch)
        r = handle_ci_config_set({"key": "enabled", "value": False,
                                  "scope": {"cell": "a.b"}})
        assert r["success"] is False
        assert "not writable" in r["error"]
        assert "ci.review.cell.a.b.enabled" not in center.d

    def test_control_key_requires_admin(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_set

        center, _ = self._install(monkeypatch)
        r = handle_ci_config_set({"key": "ci.control.shell.writable", "value": False})
        assert r["success"] is False
        assert "admin" in r["error"]
        assert center.d["ci.control.shell.writable"] is True  # unchanged

    def test_control_key_admin_ok(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_set

        center, _ = self._install(monkeypatch)
        r = handle_ci_config_set({"key": "ci.control.shell.writable",
                                  "value": False, "admin": True})
        assert r["success"] is True
        assert center.d["ci.control.shell.writable"] is False

    def test_control_key_skips_surface_gate(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_config_set

        center, _ = self._install(monkeypatch)
        center.d["ci.control.api.writable"] = False
        r = handle_ci_config_set({"key": "ci.control.api.writable",
                                  "value": True, "admin": True})
        assert r["success"] is True  # recoverable despite the api gate being off
        assert center.d["ci.control.api.writable"] is True


class TestScopeResolution:
    """v3 scoped resolution (agent > cell > global) + trigger gating."""

    def test_effective_agent_overrides_cell(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.enabled"] = True
        fake["ci.review.cell.cell-sp1.enabled"] = False
        fake["ci.review.agent.agent-writer.enabled"] = True
        assert svc._effective("enabled", "agent-writer", "cell-sp1") is True

    def test_effective_cell_overrides_global(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.enabled"] = True
        fake["ci.review.cell.cell-sp1.enabled"] = False
        assert svc._effective("enabled", "", "cell-sp1") is False

    def test_effective_falls_back_global(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.enabled"] = False
        assert svc._effective("enabled", "agent-x", "cell-x", True) is False

    def test_trigger_respects_agent_scope(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.enabled"] = True
        fake["ci.review.agent.agent-writer.enabled"] = False
        triggered = []
        monkeypatch.setattr(svc, "_do_review",
                            lambda cid, state, result: triggered.append(cid))
        svc._on_card_completed("card-1", "completed",
                               {"agent_id": "agent-writer", "cell_id": "cell-sp1"})
        svc._on_card_completed("card-2", "completed",
                               {"agent_id": "agent-reader", "cell_id": "cell-sp1"})
        time.sleep(0.3)
        assert triggered == ["card-2"]

    def test_trigger_respects_cell_scope(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.enabled"] = True
        fake["ci.review.cell.cell-sp1.enabled"] = False
        triggered = []
        monkeypatch.setattr(svc, "_do_review",
                            lambda cid, state, result: triggered.append(cid))
        svc._on_card_completed("card-1", "completed", {"cell_id": "cell-sp1"})
        svc._on_card_completed("card-2", "completed", {"cell_id": "cell-sp2"})
        time.sleep(0.3)
        assert triggered == ["card-2"]


class TestV4Matcher:
    """v4 per-gate path matchers (include/exclude globs, backward compatible)."""

    def test_matcher_no_config_backward_compat(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        steps = svc._build_steps(["src/a.py", "src/l1/kernel/params/b.py"])
        actions = [s["action"] for s in steps]
        assert actions == ["ruff", "mypy"]
        assert "params/b.py" in steps[0]["cmd"]  # no matcher = all py files

    def test_matcher_include_only(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.matchers"] = {"ruff": {"include": ["src/**"], "exclude": []}}
        steps = svc._build_steps(["src/a.py", "src/l1/kernel/params/b.py", "tools/c.py"])
        ruff = [s for s in steps if s["action"] == "ruff"][0]["cmd"]
        assert "src/a.py" in ruff and "params/b.py" in ruff  # src/** recursive
        assert "tools/c.py" not in ruff

    def test_matcher_exclude_wins(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.matchers"] = {
            "mypy": {"include": ["src/**"], "exclude": ["src/l1/**"]}}
        steps = svc._build_steps(["src/a.py", "src/l1/kernel/params/b.py"])
        mypy = [s for s in steps if s["action"] == "mypy"]
        assert mypy, "mypy step should exist (src/a.py matches include)"
        assert "src/a.py" in mypy[0]["cmd"]
        assert "params/b.py" not in mypy[0]["cmd"]  # excluded

    def test_matcher_no_match_skips_gate(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.matchers"] = {"ruff": {"include": ["docs/**"], "exclude": []}}
        steps = svc._build_steps(["src/a.py"])
        assert all(s["action"] != "ruff" for s in steps)


class TestV4AutotestContext:
    """v4 AutoTest L2 cache consumption as report context."""

    def _install_cache(self, monkeypatch, entries):
        import l3.cell as cell_mod

        class _FakeCache:
            def keys(self):
                return list(entries.keys())

            def lookup(self, key):
                return entries.get(key)

        class _FakeCell:
            def __init__(self, cache):
                self.cache = cache

        monkeypatch.setattr(cell_mod, "get_cell",
                            lambda cid: _FakeCell(_FakeCache()) if cid else None)
        return entries

    def test_autotest_context_attached(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.consume_auto_test_cache"] = True
        entries = {
            "auto_test:abc": SimpleNamespace(
                timestamp=200.0,
                value={"passed": True, "failures": [], "at": 200.0},
                summary="PASS [agent]"),
        }
        self._install_cache(monkeypatch, entries)
        ctx = svc._collect_autotest_context("cell-sp1")
        assert ctx["passed"] is True and ctx["failures"] == 0

    def test_autotest_context_miss_ignored(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.consume_auto_test_cache"] = True
        self._install_cache(monkeypatch, {})  # no auto_test entries
        assert svc._collect_autotest_context("cell-sp1") == {}

    def test_autotest_context_disabled(self, tmp_path, monkeypatch):
        svc, fake = _make_service(tmp_path, monkeypatch)
        fake["ci.review.consume_auto_test_cache"] = False
        self._install_cache(monkeypatch, {"auto_test:abc": object()})
        assert svc._collect_autotest_context("cell-sp1") == {}


class TestV4Rerun:
    """v4 manual re-run endpoint + service method."""

    def test_rerun_with_history(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        report = _make_report("card-1", "NEEDS_CHANGES", agent_id="agent-writer")
        report.changed_files = ["src/a.py"]
        monkeypatch.setattr(svc, "_emit_events", lambda r: None)
        svc._persist_report(report)
        processed = []
        monkeypatch.setattr(svc, "_process",
                            lambda cid, state, result: processed.append((cid, result)))
        r = svc.rerun("card-1")
        assert r["success"] is True and r["queued"] is True
        time.sleep(0.3)
        assert processed and processed[0][0] == "card-1"
        assert processed[0][1]["changes"] == ["src/a.py"]  # reuses changed files

    def test_rerun_without_history(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        r = svc.rerun("card-ghost")
        assert r["success"] is False
        assert "no CI review history" in r["error"]

    def test_rerun_api_write_gate(self, monkeypatch):
        from l4.api_handlers.api_handlers_ci import handle_ci_review_rerun

        class _FakeRerunSvc:
            def __init__(self, center):
                self._center = center

            def _surface_writable(self, surface):
                return bool(self._center.get(f"ci.control.{surface}.writable", True))

            def rerun(self, card_id):
                return {"success": True, "card_id": card_id, "queued": True}

        import l3.config.settings_center as sc_mod
        import l4.ci_review as cr_mod

        center = _FakeCenter()
        svc = _FakeRerunSvc(center)
        monkeypatch.setattr(sc_mod, "get_center", lambda: center)
        monkeypatch.setattr(cr_mod, "get_service", lambda: svc)
        center.d["ci.control.api.writable"] = False
        r = handle_ci_review_rerun({"card_id": "card-1"}, card_id="card-1")
        assert r["success"] is False
        assert "writes disabled" in r["error"]


class TestV4Webhook:
    """v4 webhook notification on review completion."""

    def _install(self, tmp_path, monkeypatch, settings=None):
        import l4.notify as notify_mod

        class _FakeNotify:
            def __init__(self):
                self.calls = []

            def send(self, channel, to, subject, body):
                self.calls.append({"channel": channel, "to": to,
                                   "subject": subject, "body": body})
                return {"success": True}

        fake_notify = _FakeNotify()
        monkeypatch.setattr(notify_mod, "get_service", lambda: fake_notify)
        svc, fake = _make_service(tmp_path, monkeypatch, settings)
        return svc, fake, fake_notify

    def test_webhook_on_failed(self, tmp_path, monkeypatch):
        svc, fake, notify = self._install(tmp_path, monkeypatch, {
            "ci.review.notify.webhook_url": "http://ci.example/hook",
            "ci.review.notify.webhook_events": ["failed", "rejected"],
        })
        report = _make_report("card-1", "NEEDS_CHANGES", agent_id="agent-writer")
        report.completed_at = time.time()
        svc._link_notify(report)
        assert notify.calls[-1]["channel"] == "webhook"
        assert notify.calls[-1]["to"] == "http://ci.example/hook"
        body = json.loads(notify.calls[-1]["body"])
        assert body["card_id"] == "card-1"
        assert body["verdict"] == "NEEDS_CHANGES"
        assert body["agent_id"] == "agent-writer"

    def test_webhook_not_configured(self, tmp_path, monkeypatch):
        svc, fake, notify = self._install(tmp_path, monkeypatch, {})  # no webhook_url
        report = _make_report("card-1", "REJECT", agent_id="agent-writer")
        svc._link_notify(report)
        assert notify.calls[-1]["channel"] == "log"  # fallback channel

    def test_webhook_event_filter(self, tmp_path, monkeypatch):
        svc, fake, notify = self._install(tmp_path, monkeypatch, {
            "ci.review.notify.webhook_url": "http://ci.example/hook",
            "ci.review.notify.webhook_events": ["failed", "rejected"],
        })
        report = _make_report("card-1", "PASS", agent_id="agent-writer")
        svc._link_notify(report)
        assert notify.calls[-1]["channel"] == "log"  # passed not in default events


def _boom(*args, **kwargs):
    """Helper that always raises — used with monkeypatch.setattr."""
    raise RuntimeError("boom")


class TestV5ErrorBus:
    """v5 ErrorBus capture wiring + structured error codes."""

    def _capture_fake(self, monkeypatch):
        """Monkeypatch the module-bound ``capture`` name in l4.ci_review."""
        import l4.ci_review as cr_mod

        captured = []
        monkeypatch.setattr(cr_mod, "capture", lambda *a, **k: captured.append((a, k)))
        return captured

    def test_trigger_register_failure_captured(self, tmp_path, monkeypatch):
        import l3.card.card_registry as reg_mod

        svc, _ = _make_service(tmp_path, monkeypatch)
        captured = self._capture_fake(monkeypatch)
        monkeypatch.setattr(reg_mod, "get_registry", _boom)
        r = svc.register_card_trigger()
        assert r["success"] is False
        assert captured and captured[0][1]["error_code"] == "E_CI_REVIEW_TRIGGER"

    def test_run_exception_captured(self, tmp_path, monkeypatch):
        svc, _ = _make_service(tmp_path, monkeypatch)
        captured = self._capture_fake(monkeypatch)
        monkeypatch.setattr(svc, "_do_review", _boom)
        svc._process("card-1", "completed", {})  # synchronous call for determinism
        assert captured and captured[0][1]["error_code"] == "E_CI_REVIEW_RUN"
        assert captured[0][1]["task_id"] == "card-1"

    def test_archive_failure_captured_report_still_generated(self, tmp_path, monkeypatch):
        import l3.tools._archive as archive_mod

        svc, _ = _make_service(tmp_path, monkeypatch)
        captured = self._capture_fake(monkeypatch)
        monkeypatch.setattr(archive_mod, "_cmd_archive_store",
                            _boom)
        monkeypatch.setattr(svc, "_emit_events", lambda r: None)
        svc._persist_report(_make_report("card-9", "PASS"))
        assert captured and captured[0][1]["error_code"] == "E_CI_REVIEW_ARCHIVE"
        assert svc._reports["card-9"].verdict == "PASS"  # report still persisted

    def test_setting_failure_captured_fallback_default(self, tmp_path, monkeypatch):
        import l3.config.settings_center as sc_mod
        from l4.ci_review import CiReviewService

        svc = CiReviewService(persist_path=str(tmp_path / "x.jsonl"))
        captured = self._capture_fake(monkeypatch)
        monkeypatch.setattr(sc_mod, "get_center", _boom)
        val = svc._setting("ci.review.enabled", True)
        assert val is True  # falls back to default
        assert captured and captured[0][1]["error_code"] == "E_CI_REVIEW_SETTING"

    def test_linkage_failure_captured(self, tmp_path, monkeypatch):
        import l4.notify as notify_mod

        svc, _ = _make_service(tmp_path, monkeypatch)
        captured = self._capture_fake(monkeypatch)
        monkeypatch.setattr(notify_mod, "get_service", _boom)
        svc._link_notify(_make_report("c1", "REJECT", agent_id="a1"))
        assert captured and captured[0][1]["error_code"] == "E_CI_REVIEW_LINKAGE"
        assert captured[0][1]["context"] == {"linkage": "notify"}

    def test_api_handler_structured_error(self, monkeypatch):
        import l4.ci_review as cr_mod
        from l4.api_handlers.api_handlers_ci import handle_ci_review_get

        monkeypatch.setattr(cr_mod, "get_service", _boom)
        out = handle_ci_review_get({"card_id": "x"}, card_id="x")
        assert out["success"] is False
        assert out["error_code"] == "E_CI_REVIEW_API"
