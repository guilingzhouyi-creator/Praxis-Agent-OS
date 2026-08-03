"""Card + Execution tests — card model/build/gate/registry/execution engine"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCardModel:
    """Card data model"""

    def test_card_create(self):
        from l3.card.models import Card, Phase, Step
        card = Card(intent="fix bug", domain="src")
        assert card.intent == "fix bug"
        assert card.domain == "src"

    def test_card_priority_default(self):
        from l3.card.models import Card
        card = Card(intent="test")
        assert card.priority == 5

    def test_card_all_steps(self):
        from l3.card.models import Card, Phase, Step
        card = Card(intent="t", phases=[
            Phase(name="build", steps=[Step(action="read", target="f.py")]),
        ])
        steps = card.all_steps()
        assert len(steps) == 1
        assert steps[0].action == "read"


class TestCardBuilder:
    """CardBuilder"""

    def test_build_default(self):
        from l3.card.card_builder import build_card
        card = build_card(task_id="t1", intent="implement login", domain="src/auth")
        assert card is not None
        # CardUnified uses summary.title instead of .intent
        assert "login" in card.summary.title

    def test_build_with_priority(self):
        from l3.card.card_builder import build_card
        card = build_card(task_id="t2", intent="fix urgent bug", domain=".",
                          priority=1)
        assert card.priority == 1


class TestCardGate:
    """CardGate"""

    def test_gate_evaluate(self):
        from l3.card.card_gate import evaluate as gate_eval
        r = gate_eval("test-card", intent="read file", domain=".")
        assert isinstance(r, dict)
        assert "auto_approve" in r or "action" in r or "score" in r

    def test_gate_stats(self):
        from l3.card.card_gate import stats as gate_stats
        r = gate_stats()
        assert isinstance(r, dict)


class TestCardRegistry:
    """CardRegistry"""

    def test_submit_card(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        reg = get_registry()
        cid = reg.submit("fix auth bug", domain="src/auth")
        assert cid is not None
        assert cid.startswith("card-")

    def test_get_card(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        reg = get_registry()
        cid = reg.submit("test card", domain=".")
        card = reg.get(cid)
        assert card is not None
        assert card.id == cid

    def test_list_cards(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        reg = get_registry()
        reg.submit("card one", domain=".")
        reg.submit("card two", domain=".")
        cards = reg.list()
        assert len(cards) >= 2

    def test_list_by_domain(self):
        from l3.card.card_registry import get_registry, reset_registry
        reset_registry()
        reg = get_registry()
        reg.submit("auth fix", domain="src/auth")
        reg.submit("docs update", domain="docs")
        cards = reg.list(domain="docs")
        assert len(cards) >= 1


class TestCardUnified:
    """Unified Card"""

    def test_register_card_type(self):
        from l3.card.card_unified import register_card_type, list_card_types
        register_card_type("custom_test", {
            "phases": ["analyze", "execute"],
            "default_prompts": {},
            "metadata_schema": {},
        })
        types = list_card_types()
        # list_card_types returns a list of dicts with "name" key
        assert any(t.get("name") == "custom_test" for t in types)

    def test_list_card_types(self):
        from l3.card.card_unified import list_card_types
        types = list_card_types()
        assert isinstance(types, list)
        assert len(types) >= 3


class TestExecutionPlan:
    """ExecutionPlan"""

    def test_plan_create(self):
        from l3.card.execution_plan import ExecutionPlan
        from l3.card.models import Card
        card = Card(intent="test plan", domain=".")
        plan = ExecutionPlan(card, agent_map={"reader": "agent-a"})
        assert plan is not None

    def test_plan_execute_basic(self):
        from l3.card.execution_plan import ExecutionPlan
        from l3.card.models import Card
        card = Card(intent="simple task", domain=".",
                    phases=[])
        plan = ExecutionPlan(card, {"reader": "agent-a"})
        r = plan.execute()
        assert isinstance(r, dict)
        assert "success" in r or "steps" in r


class TestExecutionVerify:
    """Execution verification"""

    def test_verify_basic(self):
        from l3.card.execution_verify import Verifier
        v = Verifier()
        r = v.check({"success": True, "data": "ok"}, goal="test goal")
        assert isinstance(r, dict)

    def test_verify_consistency(self):
        from l3.card.execution_verify import Verifier
        v = Verifier()
        r = v.consistency_check([{"success": True}], goal="test")
        assert isinstance(r, dict)


class TestExecutionEngine:
    """ExecutionEngine"""

    def test_engine_create(self):
        from l3.card.execution_engine import ExecutionEngine
        engine = ExecutionEngine()
        assert engine is not None

    def test_engine_execute_plan(self):
        from l3.card.execution_engine import ExecutionEngine, ExecutionResult
        from l3.card.execution_plan import ExecutionPlan
        from l3.card.models import Card
        engine = ExecutionEngine()
        card = Card(intent="engine test", domain=".", phases=[])
        plan = ExecutionPlan(card, {"reader": "agent-a"})
        r = engine.execute(plan)
        assert isinstance(r, ExecutionResult)
