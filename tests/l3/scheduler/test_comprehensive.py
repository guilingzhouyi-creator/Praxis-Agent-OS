"""Scheduler 5-dimension comprehensive test — rate/time/scope/router/types coverage."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestTimeScheduler:
    def test_init(self):
        from l3.scheduler.scheduler_time import get_time_scheduler, reset_time_scheduler
        reset_time_scheduler()
        ts = get_time_scheduler()
        assert ts is not None

    def test_register_and_schedule(self):
        from l3.scheduler.scheduler_time import get_time_scheduler, reset_time_scheduler
        reset_time_scheduler()
        ts = get_time_scheduler()
        ts.register("agent-t1", priority=1)
        result = ts.schedule(["agent-t1"])
        assert isinstance(result, (str, type(None)))

    def test_tick(self):
        from l3.scheduler.scheduler_time import get_time_scheduler, reset_time_scheduler
        reset_time_scheduler()
        ts = get_time_scheduler()
        ts.register("agent-t2", priority=5)
        r = ts.tick("agent-t2", elapsed=1.0)
        assert isinstance(r, dict)

    def test_stats(self):
        from l3.scheduler.scheduler_time import get_time_scheduler, reset_time_scheduler
        reset_time_scheduler()
        ts = get_time_scheduler()
        s = ts.stats()
        assert isinstance(s, dict)


class TestL3Router:
    def test_init(self):
        from l3.scheduler.scheduler_router import L3Router
        router = L3Router()
        assert router is not None

    def test_register_agent(self):
        from l3.scheduler.scheduler_router import L3Router
        router = L3Router()
        router.register("test-agent", ["src", "docs"])

    def test_route(self):
        from l3.scheduler.scheduler_router import L3Router
        router = L3Router()
        router.register("route-agent", ["src/auth"])
        result = router.route(domain="src/auth", intent_tags=["fix"])
        assert result is not None or isinstance(result, (str, dict))

    def test_agents(self):
        from l3.scheduler.scheduler_router import L3Router
        router = L3Router()
        router.register("ag1", ["."])
        agents = router.agents()
        assert isinstance(agents, dict)


class TestRequestPool:
    def test_init(self):
        from l3.scheduler.scheduler_router import RequestPool
        pool = RequestPool(capacity=8)
        assert pool is not None

    def test_enqueue_dequeue(self):
        from l3.scheduler.scheduler_router import RequestPool
        from l3.scheduler.scheduler_types import Task
        pool = RequestPool(capacity=8)
        task = Task(id="r1", agent_id="agent-r", command="read_file")
        pool.enqueue(task)
        item = pool.dequeue()
        assert item is not None


class TestUnifiedScheduler:
    def test_get_scheduler(self):
        from l3.scheduler import get_scheduler, reset_scheduler
        reset_scheduler()
        s = get_scheduler()
        assert s is not None

    def test_stats(self):
        from l3.scheduler import get_scheduler, reset_scheduler
        reset_scheduler()
        s = get_scheduler()
        stats = s.stats()
        assert isinstance(stats, dict)


class TestSchedulerTypes:
    def test_task_dataclass(self):
        from l3.scheduler.scheduler_types import Task
        task = Task(id="t1", agent_id="agent-x", command="grep")
        assert task.command == "grep"
        assert task.agent_id == "agent-x"

    def test_agent_info(self):
        from l3.scheduler.scheduler_types import AgentInfo
        info = AgentInfo(id="a1", territory=["."])
        assert info.id == "a1"

    def test_time_slice(self):
        from l3.scheduler.scheduler_types import TimeSlice
        ts = TimeSlice(agent_id="a1", quantum=15.0)
        assert ts.agent_id == "a1"
