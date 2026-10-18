# Deploy or roll back Codex Usage

Replace only integration code in persistent `/home/tony/home-assistant`; keep the
existing entry, entity registry, dashboards, and recorder database. Deployment
has **not** been executed. Merge/review approval comes first.

Use the Git method below for this review: it pins the exact reviewed revision and
provides a backup and rollback. Switching an existing HACS entry from upstream to
a same-domain fork has not been verified, so HACS is not the prescribed method.
If HACS manages the upstream integration, disable its automatic updates before
installing this fork, or an upstream update can replace the fix. Do not remove
the Home Assistant integration entry.

Prerequisites on the Docker host: Python 3.9+, Git, Docker access, write permission
to the config volume, and permission to restart Home Assistant. Run as the config
owner so file ownership remains readable by the container. The script checks
`docker inspect` to confirm that `--config` matches the writable `/config` mount.

After approval, copy the full reviewed commit SHA from the pull request into
`REVISION` below. Save the checkout for rollback:

```sh
git clone https://github.com/TonyBrobston/ha-codex-usage.git ~/ha-codex-usage-fork
cd ~/ha-codex-usage-fork
REVISION=FULL_REVIEWED_40_CHARACTER_COMMIT_SHA
git checkout --detach "$REVISION"
python3 scripts/deploy_codex_usage.py --revision "$REVISION" --restart
```

The script fetches exactly that SHA, stages its component, moves the existing
integration directory to a unique backup under
`/home/tony/home-assistant/.codex-usage-backups/`, replaces the component, and
restarts `home-automation-home-assistant-1` only when `--restart` is supplied.
Replacement failure restores the previous directory. Restart failure leaves the
backup available. No `.storage`, database, dashboard, or credential files outside
the component are copied or changed. Keep the printed backup path.

After restart:
- Check Settings → Devices & services for Codex Usage; complete reauth if prompted.
- Confirm plan, five-hour/weekly sensors, and calendars; absent windows can be
  unknown without making the whole integration unavailable.
- Confirm existing entity IDs and dashboard cards, then check historical charts.
- Check logs for success or sanitized errors. Do not share tokens or auth.json.

Rollback using the exact path printed during installation:

```sh
cd ~/ha-codex-usage-fork
python3 scripts/deploy_codex_usage.py \
  --rollback /home/tony/home-assistant/.codex-usage-backups/PRINTED_BACKUP/codex_usage \
  --restart
```

Rollback saves the displaced fork files as another backup and restores the old
integration files. Rotated credentials stay current in the existing config
entry; old credentials are not restored. Historical data and entity identities
stay in the unchanged persistent config volume. The old version may reproduce
the original authentication failure.
