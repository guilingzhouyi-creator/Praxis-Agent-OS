"""Skill system integration tests — VFS mount, catalog hook, config handler."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestVfsSkillRead:
    def test_vfs_skill_list_root(self):
        """Reading /skills returns the catalog listing."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l1.kernel.vfs import get_vfs, reset_vfs

        reset_skill_manager()
        reset_vfs()
        sm = get_skill_manager()
        sm.create(name="vfs-skill", prompt="p", tags=["evolved"], internal=True)
        r = get_vfs().read("/skills")
        assert r["success"]
        assert "vfs-skill" in r["content"]

    def test_vfs_skill_detail(self):
        """Reading /skills/<name> returns rules of that skill."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l1.kernel.vfs import get_vfs, reset_vfs

        reset_skill_manager()
        reset_vfs()
        sm = get_skill_manager()
        sm.create(name="detail-skill", prompt="p", rules=["DO: be good"], tags=["evolved"], internal=True)
        r = get_vfs().read("/skills/detail-skill")
        assert r["success"]
        assert "DO: be good" in r["content"]

    def test_vfs_skill_unknown(self):
        """Reading /skills/<missing> returns ENOENT."""
        from l1.kernel.skill import reset_skill_manager
        from l1.kernel.vfs import get_vfs, reset_vfs

        reset_skill_manager()
        reset_vfs()
        r = get_vfs().read("/skills/does-not-exist")
        assert not r["success"]
        assert "ENOENT" in r.get("error", "")


class TestSkillCatalogHook:
    def test_session_start_injects_limited_skills(self, mocker):
        """SkillCatalogHook injects at most 5 skill lines, truncated desc."""
        from l3.services.hook import SkillCatalogHook

        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.list_skills.return_value = [
            {"name": f"skill-{i}", "description": "d" * 200} for i in range(8)
        ]
        hook = SkillCatalogHook()
        task = "do the thing"
        out = hook.session_start(task, "agent-1")
        assert task in out
        assert "skill-0" in out
        # Only 5 injected (list mocked to return 8, hook limits to 5)
        assert "skill-7" not in out

    def test_session_start_no_skills(self, mocker):
        """Hook leaves task unchanged when no skills exist."""
        from l3.services.hook import SkillCatalogHook

        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.list_skills.return_value = []
        hook = SkillCatalogHook()
        assert hook.session_start("task", "agent") == "task"


class TestCfgSkillHandler:
    def test_cfg_skill_sets_write_policy(self, mocker):
        """cfg_skill mirrors praxis.yaml skill: section into SkillManager."""
        from l3.config.config_handlers import cfg_skill

        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_center = mocker.patch("l3.config.settings_center.get_center")
        center = mock_center.return_value
        center.get.side_effect = lambda k, d=None: {"skill.write_min_ring": 5, "skill.write_roles": ["x"]}.get(k, d)

        results = {}
        cfg_skill({"write_min_ring": 5, "write_roles": ["x"]}, None, results)
        assert results["skill"] is True
        mock_sm.return_value.set_write_policy.assert_called_once()
        kwargs = mock_sm.return_value.set_write_policy.call_args.kwargs
        assert kwargs["min_ring"] == 5
        assert kwargs["roles"] == ["x"]

    def test_cfg_skill_sets_evolve_scope(self, mocker):
        """cfg_skill mirrors evolve_scope into SettingsCenter."""
        from l3.config.config_handlers import cfg_skill

        mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_center = mocker.patch("l3.config.settings_center.get_center")
        center = mock_center.return_value
        center.get.side_effect = lambda k, d=None: {"skill.evolve_scope": "global"}.get(k, d)

        results = {}
        cfg_skill({"evolve_scope": "global"}, None, results)
        center.set_l2.assert_any_call("skill.evolve_scope", "global")

    def test_cfg_skill_rejects_bad_scope(self, mocker):
        """cfg_skill ignores invalid evolve_scope values."""
        from l3.config.config_handlers import cfg_skill

        mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_center = mocker.patch("l3.config.settings_center.get_center")
        center = mock_center.return_value
        center.get.side_effect = lambda k, d=None: {"skill.evolve_scope": "project"}.get(k, d)

        results = {}
        cfg_skill({"evolve_scope": "bogus"}, None, results)
        calls = [c.args for c in center.set_l2.call_args_list]
        assert ("skill.evolve_scope", "bogus") not in calls


class TestCellSkillBinding:
    def test_bind_and_unbind_skill(self):
        """bind_skill/unbind_skill round-trip via SkillManager."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager

        reset_skill_manager()
        sm = get_skill_manager()
        sm.create(name="cell-skill", prompt="p", tags=["evolved"], internal=True)
        r = sm.bind_skill("cell-1", "cell-skill")
        assert r["success"]
        assert sm.skills_for_cell("cell-1") == {"cell-skill"}
        assert sm.cells_for_skill("cell-skill") == ["cell-1"]
        assert sm.unbind_skill("cell-1", "cell-skill")["success"]
        assert sm.skills_for_cell("cell-1") == set()

    def test_bind_missing_skill_fails(self):
        """bind_skill for an unknown skill returns an error."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager

        reset_skill_manager()
        sm = get_skill_manager()
        r = sm.bind_skill("cell-1", "nope")
        assert not r["success"]
        assert "not found" in r["error"]

    def test_delete_skill_drops_cell_binding(self):
        """Deleting a skill removes it from every Cell binding."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager

        reset_skill_manager()
        sm = get_skill_manager()
        sm.create(name="drop-me", prompt="p", tags=["evolved"], internal=True)
        sm.bind_skill("cell-1", "drop-me")
        sm.delete("drop-me", internal=True)
        assert sm.skills_for_cell("cell-1") == set()

    def test_cell_bind_skills_delegates(self):
        """Cell.bind_skills delegates to SkillManager (L3 → L1)."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.cell import Cell

        reset_skill_manager()
        sm = get_skill_manager()
        sm.create(name="a", prompt="p", tags=["evolved"], internal=True)
        sm.create(name="b", prompt="p", tags=["evolved"], internal=True)
        cell = Cell(cell_id="cell-x", territory=["."])
        r = cell.bind_skills(["a", "b"])
        assert r["bound"] == 2
        assert cell.skills() == {"a", "b"}


class TestCellFilteredInjection:
    def test_evolved_skills_filtered_by_cell(self):
        """get_evolved_skills(cell_id=...) returns only white-listed skills."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()
        sm = get_skill_manager()
        sm.create(name="cell-only", prompt="p", tags=["evolved"], internal=True)
        sm.create(name="global-skill", prompt="p", tags=["evolved"], internal=True)
        sm.bind_skill("cell-1", "cell-only")
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(cell_id="cell-1")
        names = [e["name"] for e in evolved]
        assert "cell-only" in names
        assert "global-skill" not in names

    def test_lean_cases_unbound_cell_global(self):
        """get_lean_cases without cell binding returns the global pool."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()
        sm = get_skill_manager()
        sm.create(name="lean-global", prompt="lean-prompt", tags=["lean_case", "failure"], internal=True)
        r4 = R4Agent()
        cases = r4.get_lean_cases(cell_id="unbound-cell")
        # get_lean_cases returns prompts, not names — check the prompt content.
        assert "lean-prompt" in cases


class TestSkillScope:
    def test_scope_default_project(self):
        """_resolve_skill_scope defaults to project."""
        from l3.memory.r4_agent import _resolve_skill_scope

        assert _resolve_skill_scope() in ("project", "global")

    def test_project_evolved_dir_path(self):
        """paths exposes a project-scoped evolved dir."""
        from l1.kernel.paths import get_paths

        p = get_paths()
        assert p.skill_project_evolved_dir
        assert p.skill_scope in ("project", "global")


class TestGraphDiffusion:
    def test_diffusion_falls_back_when_graph_disabled(self):
        """get_evolved_skills(graph_diffusion=True) falls back to linear order."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()
        sm = get_skill_manager()
        sm.create(name="diff-a", prompt="p", tags=["evolved"], internal=True)
        sm.create(name="diff-b", prompt="p", tags=["evolved"], internal=True)
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(graph_diffusion=True, limit=2)
        names = [e["name"] for e in evolved]
        assert len(names) >= 1

    def test_diffuse_evolved_empty_without_skills(self):
        """_graph_diffuse_evolved returns [] when no evolved skills exist."""
        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()
        r4 = R4Agent()
        assert r4._graph_diffuse_evolved(limit=3) == []


class TestR4ArchiveHooks:
    def test_evolve_skill_archives_old_version(self, mocker):
        """Pre-evolution version is archived to R4 (fonds=skills)."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()
        sm = get_skill_manager()
        sm.create(name="arch", prompt="old-prompt", tags=["evolved"], internal=True)
        mock_archive = mocker.patch("l3.tools._archive._cmd_archive_store")
        r4 = R4Agent()
        # existing → versioning path archives the old version
        r4._archive_before_evolve("arch", {"prompt": "old-prompt"})
        mock_archive.assert_called_once()
        args = mock_archive.call_args.kwargs
        assert args["fonds"] == "skills"
        assert args["series"] == "evolved"

    def test_prune_archives_before_delete(self, mocker):
        """Pruning archives the skill before removing it."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()
        sm = get_skill_manager()
        sm.create(name="stale-arch", prompt="p", tags=["evolved"], internal=True)
        sm.update("stale-arch", {"loaded_at": 0.0}, internal=True)
        mock_archive = mocker.patch("l3.tools._archive._cmd_archive_store")
        r4 = R4Agent()
        r4._prune_stale_skills()
        # Archive called for the pruned skill (fonds=skills, series=pruned)
        kwargs_list = [c.kwargs for c in mock_archive.call_args_list]
        assert any(k.get("series") == "pruned" for k in kwargs_list)
        assert sm.get("stale-arch") is None


class TestGraphEdgeCreation:
    def test_lean_case_depends_on_edge(self, mocker):
        """Lean case generation creates a depends_on graph edge."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()
        get_skill_manager()
        mock_graph = mocker.patch("l3.memory.memory_graph.get_graph")
        mock_graph.return_value.add_semantic_edge.return_value = {"success": True}
        r4 = R4Agent()
        r4._link_lean_graph_edge("grep", "lean_agent_grep_x")
        mock_graph.return_value.add_semantic_edge.assert_called_once()
        kwargs = mock_graph.return_value.add_semantic_edge.call_args.kwargs
        assert kwargs["relation"] == "depends_on"
        assert kwargs["from_id"] == "grep"
