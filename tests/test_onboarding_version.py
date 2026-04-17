"""Tests for agent_takt.onboarding.version.

Covers:
- write_version_file: creates .takt/version.json with takt_version and last_upgraded_at,
  idempotent (repeated calls overwrite the file)
- read_version_file: returns None for missing file, returns None for corrupt JSON,
  returns parsed dict for valid file
- _parse_version: numeric patch ordering (0.1.9 < 0.1.10); pre-release suffix
  stripped from last component (0.1.10a1 is treated as 0.1.10)
- check_version_drift: None when versions match; warning when repo version is older
  than installed; warning (missing-file variant) when file is absent
- scaffold_project integration: .takt/version.json written with correct keys,
  idempotent across repeated scaffold calls
- commit_scaffold integration: .takt/version.json is staged in the init commit
- command_upgrade non-dry-run: .takt/version.json is written before the commit
- command_upgrade --dry-run: .takt/version.json is NOT written
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_takt.onboarding.version import (
    VERSION_FILE,
    _parse_version,
    check_version_drift,
    read_version_file,
    write_version_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_git_repo(root: Path) -> None:
    """Initialise a bare git repo suitable for commit_scaffold tests."""
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "commit.gpgsign", "false"],
        check=True, capture_output=True,
    )


def _setup_scaffold_files(root: Path) -> None:
    """Write the minimal set of files that commit_scaffold stages."""
    (root / "templates" / "agents").mkdir(parents=True, exist_ok=True)
    (root / "templates" / "agents" / "developer.md").write_text("dev")
    (root / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "skills" / "skill.md").write_text("skill")
    (root / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "skills" / "skill.md").write_text("skill")
    (root / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "agents" / "spec-reviewer.md").write_text("agent")
    (root / "specs").mkdir(parents=True, exist_ok=True)
    (root / "specs" / "HOWTO.md").write_text("howto")
    (root / ".takt").mkdir(parents=True, exist_ok=True)
    (root / ".takt" / "config.yaml").write_text("fake: true")
    (root / ".takt" / "assets-manifest.json").write_text(
        '{"takt_version":"0.0.0","installed_at":"","assets":{}}'
    )
    (root / ".gitignore").write_text("node_modules/\n")


# ---------------------------------------------------------------------------
# write_version_file
# ---------------------------------------------------------------------------


class TestWriteVersionFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_version_json_at_expected_path(self):
        path = write_version_file(self.root)
        self.assertTrue(path.is_file())
        self.assertEqual(path, self.root / VERSION_FILE)

    def test_file_contains_takt_version_key(self):
        write_version_file(self.root)
        data = json.loads((self.root / VERSION_FILE).read_text(encoding="utf-8"))
        self.assertIn("takt_version", data)
        self.assertIsInstance(data["takt_version"], str)
        self.assertGreater(len(data["takt_version"]), 0)

    def test_file_contains_last_upgraded_at_key(self):
        write_version_file(self.root)
        data = json.loads((self.root / VERSION_FILE).read_text(encoding="utf-8"))
        self.assertIn("last_upgraded_at", data)
        self.assertIsInstance(data["last_upgraded_at"], str)

    def test_idempotent_overwrites_existing_file(self):
        """Writing twice must overwrite, not append; the file remains valid JSON."""
        write_version_file(self.root)
        first_content = (self.root / VERSION_FILE).read_text(encoding="utf-8")

        # Write again — should overwrite, not corrupt.
        write_version_file(self.root)
        second_content = (self.root / VERSION_FILE).read_text(encoding="utf-8")

        # Both reads must be valid JSON.
        json.loads(first_content)
        json.loads(second_content)
        # File still exists.
        self.assertTrue((self.root / VERSION_FILE).is_file())

    def test_creates_parent_directory_if_absent(self):
        """.takt/ directory is created automatically when missing."""
        root = self.root / "newproject"
        root.mkdir()
        write_version_file(root)
        self.assertTrue((root / VERSION_FILE).is_file())


# ---------------------------------------------------------------------------
# read_version_file
# ---------------------------------------------------------------------------


class TestReadVersionFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_returns_none_for_missing_file(self):
        result = read_version_file(self.root)
        self.assertIsNone(result)

    def test_returns_none_for_corrupt_json(self):
        path = self.root / VERSION_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")
        result = read_version_file(self.root)
        self.assertIsNone(result)

    def test_returns_dict_for_valid_file(self):
        data = {"takt_version": "0.1.5", "last_upgraded_at": "2026-01-01T00:00:00+00:00"}
        path = self.root / VERSION_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        result = read_version_file(self.root)
        self.assertIsNotNone(result)
        self.assertEqual("0.1.5", result["takt_version"])

    def test_returns_none_for_empty_file(self):
        path = self.root / VERSION_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        result = read_version_file(self.root)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _parse_version
# ---------------------------------------------------------------------------


class TestParseVersion(unittest.TestCase):
    def _ints(self, ver: str) -> tuple[int, ...]:
        ints, _ = _parse_version(ver)
        return ints

    def test_simple_version_parses(self):
        self.assertEqual((0, 1, 5), self._ints("0.1.5"))

    def test_patch_ordering_numeric_not_lexicographic(self):
        """0.1.9 < 0.1.10 (10 > 9 numerically, not "10" < "9" lexicographically)."""
        v9 = self._ints("0.1.9")
        v10 = self._ints("0.1.10")
        self.assertLess(v9, v10)

    def test_prerelease_suffix_stripped_from_last_component(self):
        """0.1.10a1 is treated as 0.1.10, not 0."""
        v_release = self._ints("0.1.10")
        v_pre = self._ints("0.1.10a1")
        self.assertEqual(v_release, v_pre)

    def test_prerelease_same_base_as_release(self):
        """A pre-release 0.1.10a1 sorts equal to full release 0.1.10."""
        v_pre, raw_pre = _parse_version("0.1.10a1")
        v_rel, raw_rel = _parse_version("0.1.10")
        self.assertEqual(v_pre, v_rel)
        self.assertNotEqual(raw_pre, raw_rel)

    def test_raw_string_preserved(self):
        _, raw = _parse_version("0.1.10a1")
        self.assertEqual("0.1.10a1", raw)


# ---------------------------------------------------------------------------
# check_version_drift
# ---------------------------------------------------------------------------


class TestCheckVersionDrift(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_version(self, version: str) -> None:
        path = self.root / VERSION_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"takt_version": version, "last_upgraded_at": "2026-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )

    def test_missing_file_returns_warning(self):
        result = check_version_drift(self.root)
        self.assertIsNotNone(result)
        self.assertIn("takt upgrade", result)

    def test_empty_takt_version_returns_warning(self):
        path = self.root / VERSION_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"takt_version": "", "last_upgraded_at": ""}), encoding="utf-8")
        result = check_version_drift(self.root)
        self.assertIsNotNone(result)

    def test_matching_versions_returns_none(self):
        """Repo version == installed version → no warning."""
        with patch("agent_takt.onboarding.version._pkg_version", return_value="1.2.3"):
            self._write_version("1.2.3")
            result = check_version_drift(self.root)
        self.assertIsNone(result)

    def test_repo_older_than_installed_returns_warning(self):
        """Repo version < installed version → warning naming both versions."""
        with patch("agent_takt.onboarding.version._pkg_version", return_value="1.2.3"):
            self._write_version("1.2.2")
            result = check_version_drift(self.root)
        self.assertIsNotNone(result)
        self.assertIn("1.2.2", result)
        self.assertIn("1.2.3", result)
        self.assertIn("takt upgrade", result)

    def test_repo_newer_than_installed_returns_none(self):
        """Repo version > installed → no warning (repo is ahead)."""
        with patch("agent_takt.onboarding.version._pkg_version", return_value="1.2.0"):
            self._write_version("1.2.3")
            result = check_version_drift(self.root)
        self.assertIsNone(result)

    def test_patch_version_ordering_numeric(self):
        """0.1.9 (repo) < 0.1.10 (installed) → warning."""
        with patch("agent_takt.onboarding.version._pkg_version", return_value="0.1.10"):
            self._write_version("0.1.9")
            result = check_version_drift(self.root)
        self.assertIsNotNone(result)

    def test_prerelease_tie_break_emits_warning(self):
        """Installed=0.1.10, repo=0.1.10a1 → same int-tuple but different raw → warning."""
        with patch("agent_takt.onboarding.version._pkg_version", return_value="0.1.10"):
            self._write_version("0.1.10a1")
            result = check_version_drift(self.root)
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# scaffold_project integration
# ---------------------------------------------------------------------------


class TestScaffoldVersionIntegration(unittest.TestCase):
    """Verify scaffold_project() writes .takt/version.json correctly."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _scaffold(self, overwrite: bool = False) -> None:
        from agent_takt.onboarding import InitAnswers, scaffold_project

        answers = InitAnswers(
            runner="claude",
            max_workers=1,
            language="Python",
            test_command="pytest",
            build_check_command="python -m py_compile",
        )
        with patch("agent_takt.memory._download_model", return_value=None):
            scaffold_project(self.root, answers, overwrite=overwrite, stream_out=io.StringIO())

    def test_scaffold_creates_version_json(self):
        self._scaffold()
        self.assertTrue((self.root / VERSION_FILE).is_file())

    def test_version_json_has_takt_version_key(self):
        self._scaffold()
        data = json.loads((self.root / VERSION_FILE).read_text(encoding="utf-8"))
        self.assertIn("takt_version", data)
        self.assertIsInstance(data["takt_version"], str)
        self.assertGreater(len(data["takt_version"]), 0)

    def test_version_json_has_last_upgraded_at_key(self):
        self._scaffold()
        data = json.loads((self.root / VERSION_FILE).read_text(encoding="utf-8"))
        self.assertIn("last_upgraded_at", data)

    def test_scaffold_idempotent_overwrites_version_file(self):
        """Running scaffold_project twice must overwrite version.json, not corrupt it."""
        self._scaffold()
        self._scaffold(overwrite=True)
        data = json.loads((self.root / VERSION_FILE).read_text(encoding="utf-8"))
        self.assertIn("takt_version", data)
        self.assertIn("last_upgraded_at", data)


# ---------------------------------------------------------------------------
# commit_scaffold includes .takt/version.json
# ---------------------------------------------------------------------------


class TestCommitScaffoldIncludesVersionFile(unittest.TestCase):
    """commit_scaffold must stage .takt/version.json in the initial commit."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make_git_repo(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_commit_includes_version_json(self):
        from agent_takt.console import ConsoleReporter
        from agent_takt.onboarding.scaffold import commit_scaffold

        _setup_scaffold_files(self.root)
        # Write version.json so it can be staged.
        write_version_file(self.root)

        console = ConsoleReporter(stream=io.StringIO())
        commit_scaffold(self.root, console)

        result = subprocess.run(
            ["git", "-C", str(self.root), "show", "--stat", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        self.assertIn(".takt/version.json", result.stdout)


# ---------------------------------------------------------------------------
# command_upgrade version file integration
# ---------------------------------------------------------------------------


class TestUpgradeVersionFileIntegration(unittest.TestCase):
    """command_upgrade (non-dry-run) writes .takt/version.json; dry-run does not."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".takt").mkdir(parents=True, exist_ok=True)
        _write_simple_manifest(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_upgrade(self, dry_run: bool = False) -> int:
        from agent_takt.cli import command_upgrade
        from agent_takt.console import ConsoleReporter

        args = Namespace(root=str(self.root), dry_run=dry_run)
        console = ConsoleReporter(stream=io.StringIO())

        with (
            patch("agent_takt.onboarding.evaluate_upgrade_actions", return_value=[]),
            patch("agent_takt.onboarding._compute_bundled_catalog", return_value={}),
            patch("agent_takt._assets.packaged_default_config") as mock_pdc,
            patch("agent_takt.cli.commands.init.commit_scaffold"),
            patch("agent_takt.onboarding.scaffold.commit_scaffold"),
        ):
            mock_pdc.return_value.read_text.return_value = ""
            return command_upgrade(args, console)

    def test_non_dry_run_writes_version_file(self):
        """A real (non-dry-run) upgrade must create .takt/version.json."""
        version_path = self.root / VERSION_FILE
        self.assertFalse(version_path.exists(), "Pre-condition: no version.json yet")

        self._run_upgrade(dry_run=False)

        self.assertTrue(version_path.is_file(), ".takt/version.json must be written on upgrade")

    def test_dry_run_does_not_write_version_file(self):
        """A dry-run upgrade must NOT create .takt/version.json."""
        version_path = self.root / VERSION_FILE
        self._run_upgrade(dry_run=True)
        self.assertFalse(version_path.exists(), ".takt/version.json must NOT be written during dry-run")


def _write_simple_manifest(root: Path) -> None:
    from importlib.metadata import version as _pkg_version
    from datetime import datetime, timezone

    manifest = {
        "takt_version": _pkg_version("agent-takt"),
        "installed_at": datetime.now(tz=timezone.utc).isoformat(),
        "assets": {},
    }
    mp = root / ".takt" / "assets-manifest.json"
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
