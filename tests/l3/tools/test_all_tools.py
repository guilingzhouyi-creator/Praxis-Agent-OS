"""Tools — all _tool modules importability tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def test_archive_importable():
    import l3.tools._archive


def test_build_importable():
    import l3.tools._build


def test_code_importable():
    import l3.tools._code


def test_comm_importable():
    import l3.tools._comm


def test_config_importable():
    import l3.tools._config


def test_deps_importable():
    import l3.tools._deps


def test_env_importable():
    import l3.tools._env


def test_files_importable():
    import l3.tools._files


def test_git_importable():
    import l3.tools._git


def test_logging_importable():
    import l3.tools._logging


def test_lsp_importable():
    import l3.tools._lsp


def test_memory_importable():
    import l3.tools._memory


def test_package_importable():
    import l3.tools._package


def test_peer_importable():
    import l3.tools._peer


def test_search_importable():
    import l3.tools._search


def test_skills_importable():
    import l3.tools._skills


def test_subagent_importable():
    import l3.tools._subagent


def test_terminal_importable():
    import l3.tools._terminal


def test_web_importable():
    import l3.tools._web
