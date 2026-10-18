"""Verify backup and rollback against temporary config directories."""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "deploy", Path(__file__).parents[1] / "scripts/deploy_codex_usage.py"
)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def component(path, version):
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(json.dumps({"domain": "codex_usage", "version": version}))
    (path / "module.py").write_text(version)
    return path


def test_install_and_rollback_preserve_storage(tmp_path):
    config = tmp_path / "config"
    target = component(config / "custom_components/codex_usage", "old")
    storage = config / ".storage"
    storage.mkdir()
    (storage / "entries").write_text("do not touch")
    source = component(tmp_path / "source", "new")
    backup = deploy.replace_component(config, source)
    assert (target / "module.py").read_text() == "new"
    assert (backup / "module.py").read_text() == "old"
    deploy.replace_component(config, backup)
    assert (target / "module.py").read_text() == "old"
    assert (storage / "entries").read_text() == "do not touch"


def test_failed_switch_restores_original(tmp_path, monkeypatch):
    config = tmp_path / "config"
    target = component(config / "custom_components/codex_usage", "old")
    source = component(tmp_path / "source", "new")
    rename = deploy.os.rename

    def fail_stage(src, dst):
        if ".codex-usage-stage-" in str(src):
            raise OSError("simulated switch failure")
        return rename(src, dst)

    monkeypatch.setattr(deploy.os, "rename", fail_stage)
    with pytest.raises(OSError):
        deploy.replace_component(config, source)
    assert (target / "module.py").read_text() == "old"
