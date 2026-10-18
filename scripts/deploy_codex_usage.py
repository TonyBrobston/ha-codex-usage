#!/usr/bin/env python3
"""Install a pinned integration revision into persistent HA config, or roll back."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = "https://github.com/TonyBrobston/ha-codex-usage.git"


def replace_component(config: Path, source: Path) -> Path:
    """Stage first, retain the previous directory, and restore it if switching fails."""
    target = config / "custom_components/codex_usage"
    if not target.is_dir() or target.is_symlink():
        raise RuntimeError("Expected an existing, non-symlink codex_usage integration")
    if not (source / "manifest.json").is_file():
        raise RuntimeError("Replacement has no manifest.json")
    if json.loads((source / "manifest.json").read_text())["domain"] != "codex_usage":
        raise RuntimeError("Replacement domain does not match")
    backup_root = config / ".codex-usage-backups"
    backup_root.mkdir(mode=0o700, exist_ok=True)
    backup = (
        Path(
            tempfile.mkdtemp(prefix=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-"), dir=backup_root)
        )
        / "codex_usage"
    )
    with tempfile.TemporaryDirectory(prefix=".codex-usage-stage-", dir=target.parent) as tmp:
        stage = Path(tmp) / "codex_usage"
        shutil.copytree(source, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        os.rename(target, backup)
        try:
            os.rename(stage, target)
        except OSError:
            os.rename(backup, target)
            raise
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/home/tony/home-assistant"))
    parser.add_argument("--container", default="home-automation-home-assistant-1")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--revision", help="Reviewed full 40-character commit SHA")
    action.add_argument(
        "--rollback", type=Path, help="Backup codex_usage directory printed at install"
    )
    parser.add_argument(
        "--restart", action="store_true", help="Restart Home Assistant after replacement"
    )
    args = parser.parse_args()
    config = args.config.resolve(strict=True)
    mounts = json.loads(
        subprocess.check_output(
            ["docker", "inspect", "--format", "{{json .Mounts}}", args.container], text=True
        )
    )
    if not any(
        m["Destination"] == "/config" and m.get("RW") and Path(m["Source"]).resolve() == config
        for m in mounts
    ):
        parser.error("--config must match the container's writable persistent /config mount")
    if args.revision and not re.fullmatch(r"[0-9a-fA-F]{40}", args.revision):
        parser.error("--revision must be a full commit SHA")
    with tempfile.TemporaryDirectory(prefix="codex-usage-source-") as tmp:
        if args.rollback:
            source = args.rollback.resolve(strict=True)
            if not source.is_relative_to(config / ".codex-usage-backups"):
                parser.error("--rollback must refer to a backup under this config directory")
        else:
            repo = Path(tmp) / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "fetch", "--depth=1", REPO, args.revision], check=True
            )
            subprocess.run(
                ["git", "-C", str(repo), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True
            )
            actual = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()
            if actual.lower() != args.revision.lower():
                raise RuntimeError("Fetched revision mismatch")
            source = repo / "custom_components/codex_usage"
        backup = replace_component(config, source)
    print(f"Previous integration saved at: {backup}")
    if args.restart:
        subprocess.run(["docker", "restart", args.container], check=True)
    else:
        print(f"Restart required: docker restart {args.container}")


if __name__ == "__main__":
    main()
