from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..config import load_config
from ..console import ConsoleReporter
from ..models import Bead
from ..planner import PlanningService
from ..scheduler import Scheduler
from ..storage import RepositoryStorage
from .parser import build_parser, _refresh_seconds
from .formatting import (
    LIST_PLAIN_COLUMNS,
    _plain_value,
    format_bead_list_plain,
    format_claims_plain,
)
from .commands.telemetry import (
    _filter_beads_by_days,
    _bead_wall_clock_seconds,
    _bead_turns,
    _bead_cost_usd,
    _percentile,
    aggregate_telemetry,
    _format_telemetry_table,
    command_telemetry,
)
from .services import (
    OPERATOR_STATUS_TRANSITIONS,
    validate_operator_status_update,
    apply_operator_status_update,
    make_services,
)
from .commands import command_bead, _validated_feature_root_id
from .commands.run import command_run, CliSchedulerReporter
from .commands.merge import command_merge


def command_plan(args: argparse.Namespace, planner: PlanningService, console: ConsoleReporter) -> int:
    spec_path = Path(args.spec_file)
    console.section("Planner")
    with console.spin(f"Reading and decomposing {spec_path.name}") as spinner:
        proposal = planner.propose(spec_path)
        top_title = proposal.feature.title if proposal.feature else "no feature root"
        spinner.success(f"Planned epic '{proposal.epic_title}' with feature root '{top_title}'")
    if args.write:
        with console.spin("Writing bead graph") as spinner:
            created = planner.write_plan(proposal)
            spinner.success(f"Wrote {len(created)} beads")
        created_beads = []
        for bead_id in created:
            bead = planner.storage.load_bead(bead_id)
            created_beads.append({
                "bead_id": bead.bead_id,
                "title": bead.title,
            })
        console.dump_json({"created": created_beads})
    else:
        console.dump_json({
            "epic_title": proposal.epic_title,
            "epic_description": proposal.epic_description,
            "linked_docs": proposal.linked_docs,
            "feature": asdict(proposal.feature) if proposal.feature else None,
        })
    return 0


def command_handoff(args: argparse.Namespace, storage: RepositoryStorage, console: ConsoleReporter) -> int:
    bead = storage.load_bead(storage.resolve_bead_id(args.bead_id))
    child_id = storage.allocate_child_bead_id(bead.bead_id, args.to)
    handoff = storage.create_bead(
        bead_id=child_id,
        title=f"{args.to.title()} handoff for {bead.title}",
        agent_type=args.to,
        description=args.summary,
        parent_id=bead.bead_id,
        dependencies=[bead.bead_id],
        linked_docs=bead.linked_docs,
        expected_files=bead.touched_files or bead.expected_files,
        expected_globs=bead.expected_globs,
        touched_files=bead.touched_files,
        conflict_risks=bead.conflict_risks,
    )
    console.success(f"Created handoff bead {handoff.bead_id}")
    return 0


def command_retry(args: argparse.Namespace, storage: RepositoryStorage, console: ConsoleReporter) -> int:
    bead = storage.load_bead(storage.resolve_bead_id(args.bead_id))
    bead.status = "ready"
    bead.block_reason = ""
    bead.lease = None
    storage.update_bead(bead, event="retried", summary="Bead requeued")
    console.success(f"Requeued bead {bead.bead_id}")
    return 0



def command_summary(args: argparse.Namespace, storage: RepositoryStorage, console: ConsoleReporter) -> int:
    feature_root_id = None
    if args.feature_root:
        try:
            feature_root_id = storage.resolve_bead_id(args.feature_root)
        except ValueError as exc:
            console.error(str(exc))
            return 1
    console.dump_json(storage.summary(feature_root_id=feature_root_id))
    return 0


def command_tui(args: argparse.Namespace, storage: RepositoryStorage, console: ConsoleReporter) -> int:
    from ..tui import run_tui

    feature_root_id = _validated_feature_root_id(storage, args.feature_root)
    if args.feature_root and feature_root_id is None:
        console.error(f"{args.feature_root} is not a valid feature root")
        return 1

    return run_tui(
        storage,
        feature_root_id=feature_root_id,
        refresh_seconds=args.refresh_seconds,
        max_workers=args.max_workers,
        stream=console.stream,
    )



def command_init(args: argparse.Namespace, console: ConsoleReporter) -> int:
    from ..onboarding import InitAnswers, collect_init_answers, scaffold_project

    root = Path(args.root or ".").resolve()

    if not (root / ".git").exists():
        console.error(f"{root} is not a git repository. Run `git init` first.")
        return 1

    console.section("=== takt init ===")

    if getattr(args, "non_interactive", False):
        answers = InitAnswers(
            runner="claude",
            max_workers=1,
            language="Python",
            test_command="pytest",
            build_check_command="python -m py_compile",
        )
    else:
        answers = collect_init_answers()

    _RUNNER_INSTALL_HINTS: dict[str, str] = {
        "claude": "npm install -g @anthropic-ai/claude-code",
        "codex": "npm install -g @openai/codex",
    }
    binary = answers.runner
    if shutil.which(binary) is None:
        hint = _RUNNER_INSTALL_HINTS.get(binary, f"install the '{binary}' CLI tool")
        console.error(
            f"Runner binary '{binary}' not found in PATH.\n"
            f"Install it with: {hint}\n"
            f"Then re-run `takt init`."
        )
        return 1

    scaffold_project(root, answers, overwrite=getattr(args, "overwrite", False), console=console)
    return 0


def command_upgrade(args: argparse.Namespace, console: ConsoleReporter) -> int:
    """Upgrade takt-managed assets to the current bundled version.

    Reads ``.takt/assets-manifest.json``, compares each tracked file against
    the bundled catalog, and applies the upgrade decision table.  When
    ``--dry-run`` is set, the full plan is printed but no files are written.

    Decision table:

    * ``user_owned`` → skip, print ``[skipped — user-owned]``
    * new in bundle, absent from manifest → install, print ``[new]``
    * unmodified + bundle has newer version → overwrite, print ``[updated]``
    * unmodified + bundle matches disk → skip silently (``[up-to-date]`` in dry-run)
    * disk differs from manifest → skip, print ``[skipped — locally modified]``
    * missing from disk, still in bundle → restore, print ``[restored]``
    * in manifest, removed from bundle → rename to ``.disabled``, print
      ``[disabled — removed from bundle]``
    * on disk under bundled prefix, not in manifest or bundle → record in
      manifest as ``source: user``, ``user_owned: true``, print ``[tracked]``
    """
    import fnmatch

    from ..onboarding import (
        AssetDecision,
        _compute_bundled_catalog,
        _sha256_file,
        evaluate_upgrade_actions,
        read_assets_manifest,
        write_assets_manifest,
    )
    from ..console import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW

    root = Path(args.root or ".").resolve()
    dry_run: bool = getattr(args, "dry_run", False)

    if dry_run:
        console.section("=== takt upgrade --dry-run ===")
    else:
        console.section("=== takt upgrade ===")

    manifest = read_assets_manifest(root)
    decisions = evaluate_upgrade_actions(root, manifest)

    # Tallies for the end summary.
    counts: dict[str, int] = {
        "updated": 0,
        "new": 0,
        "restored": 0,
        "skipped_modified": 0,
        "skipped_user_owned": 0,
        "disabled": 0,
        "tracked": 0,
        "unchanged": 0,
    }
    modified_paths: list[str] = []

    # Work on a copy of the manifest assets so we can mutate it.
    updated_assets: dict[str, dict] = dict(manifest.get("assets", {}))

    bundled_catalog = _compute_bundled_catalog()

    for decision in sorted(decisions, key=lambda d: d.rel_path):
        rp = decision.rel_path
        action = decision.action

        if action == "new":
            counts["new"] += 1
            bundled_abs = bundled_catalog[rp]
            new_sha = decision.bundled_sha or _sha256_file(bundled_abs)
            if dry_run:
                console.emit(f"  {console._c(GREEN)}[new]{console._c(RESET)}        {rp}")
            else:
                dest = root / rp
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(bundled_abs), str(dest))
                updated_assets[rp] = {"sha256": new_sha, "source": "bundled", "user_owned": False}
                console.emit(f"  {console._c(GREEN)}[new]{console._c(RESET)}        {rp}")

        elif action == "update":
            counts["updated"] += 1
            bundled_abs = bundled_catalog[rp]
            new_sha = decision.bundled_sha or _sha256_file(bundled_abs)
            if dry_run:
                console.emit(f"  {console._c(CYAN)}[updated]{console._c(RESET)}    {rp}")
            else:
                dest = root / rp
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(bundled_abs), str(dest))
                updated_assets[rp]["sha256"] = new_sha
                console.emit(f"  {console._c(CYAN)}[updated]{console._c(RESET)}    {rp}")

        elif action == "unchanged":
            counts["unchanged"] += 1
            if dry_run:
                console.emit(f"  {console._c(DIM)}[up-to-date]{console._c(RESET)}  {rp}")
            # In non-dry-run mode, unchanged files are silently skipped.

        elif action == "restored":
            counts["restored"] += 1
            bundled_abs = bundled_catalog[rp]
            new_sha = decision.bundled_sha or _sha256_file(bundled_abs)
            if dry_run:
                console.emit(f"  {console._c(YELLOW)}[restored]{console._c(RESET)}   {rp}")
            else:
                dest = root / rp
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(bundled_abs), str(dest))
                updated_assets[rp]["sha256"] = new_sha
                console.emit(f"  {console._c(YELLOW)}[restored]{console._c(RESET)}   {rp}")

        elif action == "skipped_user_owned":
            counts["skipped_user_owned"] += 1
            console.emit(f"  {console._c(DIM)}[skipped — user-owned]{console._c(RESET)}  {rp}")

        elif action == "skipped_modified":
            counts["skipped_modified"] += 1
            modified_paths.append(rp)
            console.emit(f"  {console._c(YELLOW)}[skipped — locally modified]{console._c(RESET)}  {rp}")

        elif action == "disabled":
            counts["disabled"] += 1
            disk_file = root / rp
            disabled_path = disk_file.parent / (disk_file.name + ".disabled")
            if dry_run:
                console.emit(
                    f"  {console._c(DIM)}[disabled — removed from bundle]{console._c(RESET)}  {rp}"
                    f" → {disabled_path.name}"
                )
            else:
                if disk_file.is_file():
                    disk_file.rename(disabled_path)
                # Remove the original key; the .disabled file is user territory.
                updated_assets.pop(rp, None)
                console.emit(
                    f"  {console._c(DIM)}[disabled — removed from bundle]{console._c(RESET)}  {rp}"
                    f" → {disabled_path.name}"
                )

        elif action == "user_added":
            counts["tracked"] += 1
            if dry_run:
                console.emit(f"  {console._c(GREEN)}[tracked — user-owned]{console._c(RESET)}  {rp}")
            else:
                updated_assets[rp] = {
                    "sha256": decision.current_sha or "",
                    "source": "user",
                    "user_owned": True,
                }
                console.emit(f"  {console._c(GREEN)}[tracked — user-owned]{console._c(RESET)}  {rp}")

    # Write updated manifest unless this is a dry run.
    if not dry_run:
        import json as _json
        from importlib.metadata import version as _pkg_version
        from datetime import datetime, timezone

        new_manifest = {
            "takt_version": _pkg_version("agent-takt"),
            "installed_at": manifest.get("installed_at", datetime.now(tz=timezone.utc).isoformat()),
            "upgraded_at": datetime.now(tz=timezone.utc).isoformat(),
            "assets": updated_assets,
        }
        manifest_path = root / ".takt" / "assets-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(_json.dumps(new_manifest, indent=2), encoding="utf-8")

    # Config key merge — insert any new keys from the bundled default config
    # into the user's .takt/config.yaml without overwriting existing values.
    import yaml as _yaml

    from ..onboarding import merge_config_keys
    from .._assets import packaged_default_config

    config_path = root / ".takt" / "config.yaml"
    added_config_keys: list[str] = []
    if config_path.is_file():
        user_cfg = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        bundled_cfg = _yaml.safe_load(packaged_default_config().read_text(encoding="utf-8")) or {}
        merged_cfg, added_config_keys = merge_config_keys(user_cfg, bundled_cfg)
        if added_config_keys:
            console.emit("")
            console.emit(f"{console._c(BOLD)}Config additions:{console._c(RESET)}")
            for key in added_config_keys:
                console.emit(f"  {console._c(GREEN)}[added]{console._c(RESET)}  {key}")
            if not dry_run:
                config_path.write_text(_yaml.dump(merged_cfg, default_flow_style=False), encoding="utf-8")

    # Print summary.
    console.emit("")
    prefix = "[dry-run] " if dry_run else ""
    console.emit(
        f"{console._c(BOLD)}{prefix}Summary:{console._c(RESET)}"
        f"  updated={counts['updated']}"
        f"  new={counts['new']}"
        f"  restored={counts['restored']}"
        f"  disabled={counts['disabled']}"
        f"  tracked={counts['tracked']}"
        f"  skipped(modified)={counts['skipped_modified']}"
        f"  skipped(user-owned)={counts['skipped_user_owned']}"
        f"  config-keys-added={len(added_config_keys)}"
    )

    if modified_paths:
        console.emit("")
        console.emit(
            f"{console._c(YELLOW)}Files skipped due to local modifications"
            f" — review manually:{console._c(RESET)}"
        )
        for path in modified_paths:
            console.emit(f"  {path}")

    return 0


def command_asset(args: argparse.Namespace, console: ConsoleReporter) -> int:
    """Manage asset ownership entries in ``.takt/assets-manifest.json``.

    Dispatches to ``mark-owned``, ``unmark-owned``, and ``list``
    sub-subcommands.
    """
    import fnmatch
    import json as _json

    from ..onboarding import (
        _sha256_file,
        evaluate_upgrade_actions,
        read_assets_manifest,
    )
    from ..console import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW

    root = Path(args.root or ".").resolve()
    manifest = read_assets_manifest(root)
    assets: dict[str, dict] = manifest.get("assets", {})
    subcommand = args.asset_command

    if subcommand in ("mark-owned", "unmark-owned"):
        glob_pattern: str = args.glob
        target_value = subcommand == "mark-owned"
        matched = [
            rp for rp in assets
            if fnmatch.fnmatch(rp, glob_pattern)
        ]
        if not matched:
            console.warn(f"No manifest entries matched pattern: {glob_pattern!r}")
            return 0
        updated = 0
        for rp in matched:
            entry = assets[rp]
            # User-added files (source: user) must remain user_owned: true;
            # unmark-owned must not clear that flag or they would be disabled
            # on the next upgrade run.
            if not target_value and entry.get("source") == "user":
                console.warn(f"  {rp}  →  skipped (user-added files always remain user-owned)")
                continue
            entry["user_owned"] = target_value
            verb = "marked as user-owned" if target_value else "unmarked (upgrade-managed)"
            console.emit(f"  {rp}  →  {verb}")
            updated += 1

        manifest["assets"] = assets
        manifest_path = root / ".takt" / "assets-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(_json.dumps(manifest, indent=2), encoding="utf-8")
        console.success(f"{updated} asset(s) updated in manifest.")
        return 0

    if subcommand == "list":
        decisions = evaluate_upgrade_actions(root, manifest)
        if not decisions:
            console.emit("No assets tracked in manifest.")
            return 0

        # Column widths.
        path_w = max((len(d.rel_path) for d in decisions), default=40)
        header = f"{'PATH':<{path_w}}  {'STATUS':<18}  {'SOURCE':<10}  OWNED"
        console.emit(console._c(BOLD) + header + console._c(RESET))
        console.emit("-" * len(header))

        _action_labels: dict[str, str] = {
            "update": "update available",
            "unchanged": "up-to-date",
            "new": "new",
            "restored": "missing (will restore)",
            "skipped_user_owned": "user-owned",
            "skipped_modified": "locally modified",
            "disabled": "removed from bundle",
            "user_added": "user-added",
        }
        _action_colors: dict[str, str] = {
            "update": CYAN,
            "unchanged": DIM,
            "new": GREEN,
            "restored": YELLOW,
            "skipped_user_owned": DIM,
            "skipped_modified": YELLOW,
            "disabled": DIM,
            "user_added": GREEN,
        }

        for decision in sorted(decisions, key=lambda d: d.rel_path):
            label = _action_labels.get(decision.action, decision.action)
            color = _action_colors.get(decision.action, RESET)
            source = assets.get(decision.rel_path, {}).get("source", "—")
            owned = "yes" if decision.user_owned else "no"
            colored_label = console._c(color) + f"{label:<18}" + console._c(RESET)
            console.emit(
                f"{decision.rel_path:<{path_w}}  {colored_label}  {source:<10}  {owned}"
            )
        return 0

    console.error(f"Unknown asset subcommand: {subcommand!r}")
    return 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.root or ".").resolve()
    console = ConsoleReporter()

    # Commands that do not need an existing .takt/ storage directory
    if args.command == "init":
        return command_init(args, console)
    if args.command == "upgrade":
        return command_upgrade(args, console)
    if args.command == "asset":
        return command_asset(args, console)

    storage, scheduler, planner = make_services(root, runner_backend=args.runner)

    if args.command == "plan":
        return command_plan(args, planner, console)
    if args.command == "run":
        return command_run(args, scheduler, console)
    if args.command == "bead":
        return command_bead(args, storage, console)
    if args.command == "handoff":
        return command_handoff(args, storage, console)
    if args.command == "retry":
        return command_retry(args, storage, console)
    if args.command == "merge":
        return command_merge(args, storage, console)
    if args.command == "summary":
        return command_summary(args, storage, console)
    if args.command == "tui":
        return command_tui(args, storage, console)
    if args.command == "telemetry":
        return command_telemetry(args, storage, console)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
