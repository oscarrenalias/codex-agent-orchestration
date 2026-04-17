"""Tests for command_summary version-drift warning behavior.

Covers:
- No warning emitted when repo version matches installed version
- Warning emitted before JSON counts when .takt/version.json is absent
- Warning emitted before JSON counts when repo version is older than installed
- Return code is 0 in all cases (drift is informational, not fatal)
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_takt.cli import command_summary
from agent_takt.console import ConsoleReporter
from agent_takt.onboarding.version import VERSION_FILE
from agent_takt.storage import RepositoryStorage

RepositoryStorage._auto_commit = False

from helpers import OrchestratorTests as _OrchestratorBase  # noqa: E402


class CliSummaryVersionDriftTests(_OrchestratorBase):
    """Tests for the drift-warning behavior in command_summary."""

    def _run_summary(self) -> tuple[int, str]:
        """Run command_summary with no feature root; return (exit_code, output)."""
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_summary(Namespace(feature_root=None), self.storage, console)
        return exit_code, stream.getvalue()

    # ------------------------------------------------------------------
    # No warning when versions match
    # ------------------------------------------------------------------

    def test_no_warning_when_versions_match(self):
        """Versions match → stream contains only the JSON payload, no warning line."""
        # OrchestratorTests.setUp already calls write_version_file(self.root) which
        # records the currently-installed version. check_version_drift will compare
        # that against _pkg_version("agent-takt") and find no drift.
        exit_code, output = self._run_summary()

        self.assertEqual(0, exit_code)
        # Output must be parseable as JSON (no warning prefix).
        payload = json.loads(output)
        self.assertIn("counts", payload)

    def test_no_warning_does_not_include_bang_prefix(self):
        """When there is no drift, the output should not contain '! '."""
        _, output = self._run_summary()
        self.assertNotIn("! ", output)

    # ------------------------------------------------------------------
    # Warning when version file is absent
    # ------------------------------------------------------------------

    def test_warning_when_version_file_absent(self):
        """No version.json → warning text is emitted before the JSON counts."""
        version_path = self.root / VERSION_FILE
        version_path.unlink()

        exit_code, output = self._run_summary()

        self.assertEqual(0, exit_code)
        lines = output.splitlines()
        # Find the warning line (starts with "! ") and the JSON start line ("{").
        warning_indices = [i for i, line in enumerate(lines) if line.startswith("! ")]
        json_start_indices = [i for i, line in enumerate(lines) if line.strip() == "{"]
        self.assertGreater(len(warning_indices), 0, "Expected a warning line in output")
        self.assertGreater(len(json_start_indices), 0, "Expected JSON in output")
        self.assertLess(warning_indices[0], json_start_indices[0], "Warning must precede JSON")

    def test_warning_absent_mentions_upgrade(self):
        """Missing-file warning should mention 'takt upgrade'."""
        version_path = self.root / VERSION_FILE
        version_path.unlink()

        _, output = self._run_summary()

        self.assertIn("takt upgrade", output)

    def test_return_code_zero_when_version_file_absent(self):
        """Drift detection is informational — exit code must be 0."""
        version_path = self.root / VERSION_FILE
        version_path.unlink()

        exit_code, _ = self._run_summary()
        self.assertEqual(0, exit_code)

    # ------------------------------------------------------------------
    # Warning when repo version is older than installed
    # ------------------------------------------------------------------

    def test_warning_when_repo_version_older_than_installed(self):
        """Repo=0.0.1, installed=1.0.0 → warning appears before JSON counts."""
        version_path = self.root / VERSION_FILE
        version_path.write_text(
            json.dumps({"takt_version": "0.0.1", "last_upgraded_at": "2020-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )

        with patch("agent_takt.onboarding.version._pkg_version", return_value="1.0.0"):
            exit_code, output = self._run_summary()

        self.assertEqual(0, exit_code)
        lines = output.splitlines()
        warning_indices = [i for i, line in enumerate(lines) if line.startswith("! ")]
        json_start_indices = [i for i, line in enumerate(lines) if line.strip() == "{"]
        self.assertGreater(len(warning_indices), 0, "Expected a warning line in output")
        self.assertGreater(len(json_start_indices), 0, "Expected JSON in output")
        self.assertLess(warning_indices[0], json_start_indices[0], "Warning must precede JSON")

    def test_warning_names_both_versions(self):
        """Drift warning must include both the repo version and the installed version."""
        version_path = self.root / VERSION_FILE
        version_path.write_text(
            json.dumps({"takt_version": "0.0.1", "last_upgraded_at": "2020-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )

        with patch("agent_takt.onboarding.version._pkg_version", return_value="1.0.0"):
            _, output = self._run_summary()

        self.assertIn("0.0.1", output)
        self.assertIn("1.0.0", output)

    def test_return_code_zero_when_repo_is_stale(self):
        """Drift warning does not make command_summary fail."""
        version_path = self.root / VERSION_FILE
        version_path.write_text(
            json.dumps({"takt_version": "0.0.1", "last_upgraded_at": "2020-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )

        with patch("agent_takt.onboarding.version._pkg_version", return_value="1.0.0"):
            exit_code, _ = self._run_summary()

        self.assertEqual(0, exit_code)

    def test_json_payload_still_valid_when_drift_warning_emitted(self):
        """Even with a warning prefix, the JSON counts block must still parse correctly."""
        version_path = self.root / VERSION_FILE
        version_path.write_text(
            json.dumps({"takt_version": "0.0.1", "last_upgraded_at": "2020-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )

        with patch("agent_takt.onboarding.version._pkg_version", return_value="1.0.0"):
            _, output = self._run_summary()

        # The JSON block must be extractable from the output.
        lines = output.splitlines()
        json_start = next(i for i, line in enumerate(lines) if line.strip() == "{")
        json_text = "\n".join(lines[json_start:])
        payload = json.loads(json_text)
        self.assertIn("counts", payload)


if __name__ == "__main__":
    unittest.main()
