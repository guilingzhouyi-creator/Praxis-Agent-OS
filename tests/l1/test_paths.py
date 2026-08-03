"""Tests for platform-aware deployment path resolution."""

from __future__ import annotations

from pathlib import Path

import l1.kernel.paths as paths


def test_cli_project_preserves_workspace_config_path() -> None:
    resolved = paths.PraxisPaths(paths.DeployMode.CLI_PROJECT)

    assert resolved.data_dir == ".praxis"
    assert resolved.config_file == "config/praxis.yaml"


def test_windows_package_mode_uses_appdata_for_data_and_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "IS_MAC", False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    resolved = paths.PraxisPaths(paths.DeployMode.PIP_PACKAGE)

    expected_dir = str(tmp_path / "praxis")
    assert resolved.data_dir == expected_dir
    assert resolved.config_dir == expected_dir
    assert resolved.config_file == str(Path(expected_dir) / "praxis.yaml")


def test_pip_mode_config_file_respects_data_directory_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PRAXIS_DATA_DIR", str(tmp_path))

    resolved = paths.PraxisPaths(paths.DeployMode.PIP_PACKAGE)

    assert resolved.data_dir == str(tmp_path)
    assert resolved.config_file == str(tmp_path / "praxis.yaml")
