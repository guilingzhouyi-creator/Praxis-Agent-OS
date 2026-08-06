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
        monkeypatch.setattr(notify_mod, "send_notification",
                            lambda agent, message, channel="log": sent.append(agent))
        svc._link_notify(_make_report("c1", "REJECT", agent_id="agent-writer"))
        assert sent == ["agent-writer"]

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
