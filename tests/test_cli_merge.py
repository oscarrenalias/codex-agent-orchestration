"""Tests for command_merge in cli/commands/merge.py.

Covers:
- command_merge uses feature root branch for descendant beads
- command_merge resolves bead ID prefix
- subprocess.Popen invoked with list arg and no shell=True
- shlex.split correctly tokenises standard and quoted test commands
"""
from __future__ import annotations

import io
import shlex
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_takt.cli import command_merge
from agent_takt.console import ConsoleReporter
from agent_takt.models import BEAD_DONE
from agent_takt.storage import RepositoryStorage

RepositoryStorage._auto_commit = False

from helpers import OrchestratorTests as _OrchestratorBase  # noqa: E402


class TestCliMerge(_OrchestratorBase):

    def test_merge_uses_feature_root_branch_for_descendants(self) -> None:
        epic = self.storage.create_bead(title="Epic", agent_type="planner", description="root", status=BEAD_DONE, bead_type="epic")
        root = self.storage.create_bead(title="Feature root", agent_type="developer", description="feature", parent_id=epic.bead_id)
        child = self.storage.create_bead(
            title="Child task",
            agent_type="developer",
            description="subtask",
            parent_id=root.bead_id,
            dependencies=[root.bead_id],
        )
        root.execution_branch_name = "feature/b0001"
        root.branch_name = "feature/b0001"
        self.storage.save_bead(root)
        console = ConsoleReporter(stream=io.StringIO())
        with patch("agent_takt.cli.commands.merge.WorktreeManager.merge_branch") as merge_branch:
            exit_code = command_merge(Namespace(bead_id=child.bead_id, skip_rebase=True, skip_tests=True), self.storage, console)
        self.assertEqual(0, exit_code)
        merge_branch.assert_called_once_with("feature/b0001")

    def test_cli_merge_resolves_prefix(self) -> None:
        bead = self.storage.create_bead(title="Merge me", agent_type="developer", description="work")
        bead.execution_branch_name = "feature/b-test"
        self.storage.save_bead(bead)
        prefix = bead.bead_id[:4]
        console = ConsoleReporter(stream=io.StringIO())
        with patch("agent_takt.cli.commands.merge.WorktreeManager.merge_branch") as merge_branch:
            exit_code = command_merge(Namespace(bead_id=prefix, skip_rebase=True, skip_tests=True), self.storage, console)
        self.assertEqual(0, exit_code)
        merge_branch.assert_called_once_with("feature/b-test")

    def test_popen_invoked_with_list_no_shell(self) -> None:
        """subprocess.Popen must receive a list, never shell=True."""
        bead = self.storage.create_bead(title="Gate test", agent_type="developer", description="work")
        bead.execution_branch_name = "feature/b-gate"
        self.storage.save_bead(bead)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.returncode = 0

        mock_config = MagicMock()
        mock_config.common.test_command = "uv run pytest tests/ -n auto -q"
        mock_config.common.test_timeout_seconds = 120
        mock_config.scheduler.max_corrective_attempts = 5

        console = ConsoleReporter(stream=io.StringIO())
        with patch("agent_takt.cli.commands.merge.load_config", return_value=mock_config):
            with patch("agent_takt.cli.commands.merge.subprocess.Popen", return_value=mock_proc) as mock_popen:
                with patch("agent_takt.cli.commands.merge.WorktreeManager.merge_branch"):
                    exit_code = command_merge(
                        Namespace(bead_id=bead.bead_id, skip_rebase=True, skip_tests=False),
                        self.storage,
                        console,
                    )

        self.assertEqual(0, exit_code)
        mock_popen.assert_called_once()
        call_args, call_kwargs = mock_popen.call_args
        # First positional argument must be a list, not a string
        self.assertIsInstance(call_args[0], list)
        # shell=True must not appear
        self.assertNotIn("shell", call_kwargs)

    def test_standard_test_command_splits_to_expected_list(self) -> None:
        """'uv run pytest tests/ -n auto -q' must tokenise to the canonical list."""
        result = shlex.split("uv run pytest tests/ -n auto -q")
        self.assertEqual(["uv", "run", "pytest", "tests/", "-n", "auto", "-q"], result)

    def test_quoted_argument_splits_correctly(self) -> None:
        """shlex.split must strip quotes and keep the quoted string as one token."""
        result = shlex.split('uv run pytest -k "test_foo"')
        self.assertEqual(["uv", "run", "pytest", "-k", "test_foo"], result)


if __name__ == "__main__":
    unittest.main()
