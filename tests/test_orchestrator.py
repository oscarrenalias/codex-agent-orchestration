from __future__ import annotations

import json
import io
import shutil
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

from agent_takt.cli import (
    build_parser,
    command_handoff,
    command_plan,
    command_retry,
    command_summary,
    command_tui,
)
from agent_takt.config import OrchestratorConfig, SchedulerConfig
from agent_takt.console import ConsoleReporter
from agent_takt.gitutils import GitError
from agent_takt.graph import MAX_TITLE_LENGTH, render_bead_graph
from agent_takt.models import (
    BEAD_BLOCKED,
    BEAD_DONE,
    BEAD_HANDED_OFF,
    BEAD_IN_PROGRESS,
    BEAD_OPEN,
    BEAD_READY,
    Bead,
    ExecutionRecord,
    HandoffSummary,
    PlanChild,
    PlanProposal,
)
from agent_takt.planner import PlanningService
from agent_takt.prompts import (
    BUILT_IN_AGENT_TYPES,
    build_planner_prompt,
    build_worker_prompt,
    guardrail_template_path,
    load_guardrail_template,
    render_agent_output_requirements,
    render_context_snippets,
)
from agent_takt.runner import AGENT_OUTPUT_SCHEMA, PLANNER_OUTPUT_SCHEMA
from agent_takt.storage import RepositoryStorage
from agent_takt.tui import (
    FILTER_ACTIONABLE,
    FILTER_ALL,
    FILTER_DEFAULT,
    FILTER_DEFERRED,
    FILTER_DONE,
    TuiRuntimeState,
    build_tree_rows,
    collect_tree_rows,
    format_detail_panel,
    format_footer,
    render_tree_panel,
    run_tui,
    resolve_selected_bead,
    resolve_selected_index,
    supported_filter_modes,
)

# Suppress git commits for the general test session.  BeadAutoCommitTests
# re-enables this flag in its own setUp/tearDown to exercise real commit paths.
RepositoryStorage._auto_commit = False

from helpers import FakeRunner, OrchestratorTests as _OrchestratorBase  # noqa: E402


class OrchestratorTests(_OrchestratorBase):

    def test_planner_writes_epic_and_children(self) -> None:
        spec_path = self.root / "spec.md"
        spec_path.write_text("Feature spec\n", encoding="utf-8")
        proposal = PlanProposal(
            epic_title="Epic",
            epic_description="Parent task",
            linked_docs=["spec.md"],
            feature=PlanChild(
                title="Feature root",
                agent_type="developer",
                description="shared execution root",
                acceptance_criteria=["works"],
                children=[
                    PlanChild(
                        title="Implement",
                        agent_type="developer",
                        description="build",
                        acceptance_criteria=["works"],
                        dependencies=[],
                        expected_files=["src/agent_takt/scheduler.py"],
                        children=[
                            PlanChild(
                                title="Review",
                                agent_type="review",
                                description="check",
                                acceptance_criteria=["approved"],
                                dependencies=["Implement"],
                                expected_globs=["src/agent_takt/*.py"],
                            )
                        ],
                    )
                ],
            ),
        )
        planner = PlanningService(self.storage, FakeRunner(proposal=proposal))
        created = planner.write_plan(planner.propose(spec_path))
        self.assertEqual(4, len(created))
        epic = self.storage.load_bead(created[0])
        feature = self.storage.load_bead(created[1])
        implement = self.storage.load_bead(created[2])
        review = self.storage.load_bead(created[3])
        self.assertEqual(BEAD_DONE, epic.status)
        self.assertIsNone(epic.feature_root_id)
        self.assertEqual(BEAD_DONE, feature.status)
        self.assertEqual("feature", feature.bead_type)
        self.assertEqual(feature.bead_id, feature.feature_root_id)
        self.assertEqual(feature.bead_id, implement.parent_id)
        self.assertEqual(feature.bead_id, implement.feature_root_id)
        self.assertEqual(feature.bead_id, review.feature_root_id)
        self.assertEqual(implement.bead_id, review.parent_id)
        self.assertEqual([implement.bead_id], review.dependencies)
        self.assertEqual(["src/agent_takt/scheduler.py"], implement.expected_files)
        self.assertEqual(["src/agent_takt/*.py"], review.expected_globs)

    def test_planner_writes_shared_followups_at_feature_root_with_multi_bead_dependencies(self) -> None:
        spec_path = self.root / "spec.md"
        spec_path.write_text("Feature spec\n", encoding="utf-8")
        proposal = PlanProposal(
            epic_title="Epic",
            epic_description="Parent task",
            linked_docs=["spec.md"],
            feature=PlanChild(
                title="Feature root",
                agent_type="developer",
                description="shared execution root",
                acceptance_criteria=["works"],
                children=[
                    PlanChild(
                        title="Implement A",
                        agent_type="developer",
                        description="first focused change",
                        acceptance_criteria=["works"],
                        expected_files=["src/a.py"],
                    ),
                    PlanChild(
                        title="Implement B",
                        agent_type="developer",
                        description="second focused change",
                        acceptance_criteria=["works"],
                        dependencies=["Implement A"],
                        expected_files=["src/b.py"],
                    ),
                    PlanChild(
                        title="Shared tester",
                        agent_type="tester",
                        description="validate combined changes",
                        acceptance_criteria=["approved"],
                        dependencies=["Implement A", "Implement B"],
                    ),
                    PlanChild(
                        title="Shared docs",
                        agent_type="documentation",
                        description="document combined changes",
                        acceptance_criteria=["docs updated"],
                        dependencies=["Implement A", "Implement B"],
                    ),
                    PlanChild(
                        title="Shared review",
                        agent_type="review",
                        description="review combined changes",
                        acceptance_criteria=["approved"],
                        dependencies=["Implement A", "Implement B", "Shared tester", "Shared docs"],
                    ),
                ],
            ),
        )

        planner = PlanningService(self.storage, FakeRunner(proposal=proposal))
        created = planner.write_plan(planner.propose(spec_path))

        self.assertEqual(7, len(created))
        feature = self.storage.load_bead(created[1])
        implement_a = self.storage.load_bead(created[2])
        implement_b = self.storage.load_bead(created[3])
        shared_test = self.storage.load_bead(created[4])
        shared_docs = self.storage.load_bead(created[5])
        shared_review = self.storage.load_bead(created[6])
        self.assertEqual(feature.bead_id, implement_a.parent_id)
        self.assertEqual(feature.bead_id, implement_b.parent_id)
        self.assertEqual(feature.bead_id, shared_test.parent_id)
        self.assertEqual(feature.bead_id, shared_docs.parent_id)
        self.assertEqual(feature.bead_id, shared_review.parent_id)
        self.assertEqual([implement_a.bead_id], implement_b.dependencies)
        self.assertEqual([implement_a.bead_id, implement_b.bead_id], shared_test.dependencies)
        self.assertEqual([implement_a.bead_id, implement_b.bead_id], shared_docs.dependencies)
        self.assertEqual(
            [implement_a.bead_id, implement_b.bead_id, shared_test.bead_id, shared_docs.bead_id],
            shared_review.dependencies,
        )

    def test_write_plan_rejects_invalid_agent_type(self) -> None:
        spec_path = self.root / "spec.md"
        spec_path.write_text("Feature spec\n", encoding="utf-8")
        proposal = PlanProposal(
            epic_title="Epic",
            epic_description="Parent task",
            feature=PlanChild(
                title="Feature root",
                agent_type="developer",
                description="shared execution root",
                acceptance_criteria=[],
                children=[
                    PlanChild(
                        title="Bad bead",
                        agent_type="docs",
                        description="invalid agent type",
                        acceptance_criteria=[],
                    )
                ],
            ),
        )
        planner = PlanningService(self.storage, FakeRunner(proposal=proposal))
        with self.assertRaises(ValueError) as ctx:
            planner.write_plan(planner.propose(spec_path))
        self.assertIn("docs", str(ctx.exception))
        self.assertIn("Bad bead", str(ctx.exception))

    def test_build_planner_prompt_requires_small_developer_beads_and_shared_followups(self) -> None:
        prompt = build_planner_prompt("Ship the feature")
        self.assertIn("one focused change", prompt)
        self.assertIn("roughly 10 minutes of implementation work", prompt)
        self.assertIn(
            "Split broader logical units into smaller dependent developer beads instead of assigning one bead to absorb multiple distinct changes.",
            prompt,
        )
        self.assertIn("touch more than 2-3 functions", prompt)
        self.assertIn("break it into smaller dependent beads with explicit ordering", prompt)
        self.assertIn(
            "coalesce tester, documentation, and review work into shared follow-up beads rather than duplicating that work in each implementation bead.",
            prompt,
        )
        self.assertIn(
            "Those shared follow-up beads should depend on the full related implementation set they validate, document, or review so the follow-up happens after the combined change is ready.",
            prompt,
        )

    def test_render_bead_graph_outputs_labels_edges_icons_and_orphans(self) -> None:
        dependency = self.storage.create_bead(
            title="Dependency bead",
            agent_type="planner",
            description="upstream dependency",
            status=BEAD_DONE,
            bead_id="B-graph-dep",
        )
        # Create B-missing so dependency validation passes, but exclude it from
        # the list passed to render_bead_graph to test that missing-node edges
        # are not rendered.
        self.storage.create_bead(
            title="Missing bead",
            agent_type="developer",
            description="bead that will be omitted from graph input",
            bead_id="B-missing",
        )
        main = self.storage.create_bead(
            title="X" * (MAX_TITLE_LENGTH + 8),
            agent_type="developer",
            description="main task",
            parent_id=dependency.bead_id,
            dependencies=[dependency.bead_id, "B-missing"],
            status=BEAD_IN_PROGRESS,
            bead_id="B-graph-main",
        )
        corrective = self.storage.create_bead(
            title='Corrective "fix"\nfollowup',
            agent_type="developer",
            description="corrective task",
            parent_id=main.bead_id,
            status=BEAD_BLOCKED,
            bead_id="B-graph-main-corrective",
        )
        orphan = self.storage.create_bead(
            title="Standalone",
            agent_type="review",
            description="orphan node",
            status=BEAD_READY,
            bead_id="B-graph-orphan",
        )

        graph = render_bead_graph([dependency, main, corrective, orphan], SchedulerConfig())

        truncated_title = f'{"X" * (MAX_TITLE_LENGTH - 3)}...'
        self.assertTrue(graph.startswith("graph TD\n"))
        self.assertIn('B_graph_dep["B-graph-dep: Dependency bead [planner] ✓"]', graph)
        self.assertIn(
            f'B_graph_main["B-graph-main: {truncated_title} [developer] ..."]',
            graph,
        )
        self.assertIn(
            'B_graph_main_corrective["B-graph-main-corrective: Corrective \\"fix\\" followup [developer] !"]',
            graph,
        )
        self.assertIn('B_graph_orphan["B-graph-orphan: Standalone [review] ○"]', graph)
        self.assertIn("B_graph_dep --> B_graph_main", graph)
        self.assertIn("B_graph_main_corrective -.-> B_graph_main", graph)
        self.assertNotIn("B_missing --> B_graph_main", graph)
        self.assertIn("B_graph_orphan", graph)

    def test_build_parser_accepts_tui_options_and_defaults(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["tui", "--feature-root", "B0030"])

        self.assertEqual("tui", args.command)
        self.assertEqual("B0030", args.feature_root)
        self.assertEqual(3, args.refresh_seconds)

    def test_build_parser_rejects_tui_refresh_seconds_below_one(self) -> None:
        parser = build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(["tui", "--refresh-seconds", "0"])

    def test_command_plan_write_outputs_created_bead_details(self) -> None:
        spec_path = self.root / "spec.md"
        spec_path.write_text("Feature spec\n", encoding="utf-8")
        proposal = PlanProposal(
            epic_title="Epic",
            epic_description="Parent task",
            linked_docs=["spec.md"],
            feature=PlanChild(
                title="Feature root",
                agent_type="planner",
                description="shared execution root",
                acceptance_criteria=["works"],
                children=[
                    PlanChild(
                        title="Implement",
                        agent_type="developer",
                        description="build",
                        acceptance_criteria=["works"],
                    )
                ],
            ),
        )
        planner = PlanningService(self.storage, FakeRunner(proposal=proposal))
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_plan(Namespace(spec_file=str(spec_path), write=True), planner, console)
        self.assertEqual(0, exit_code)
        output = stream.getvalue()
        import re
        self.assertRegex(output, r'"bead_id": "B-[0-9a-f]{8}"')
        self.assertIn('"title": "Epic"', output)
        self.assertNotIn('"description"', output)

    def test_summary_counts_and_lists_are_sorted_and_limited(self) -> None:
        ready_ids = []
        for idx in range(7):
            bead = self.storage.create_bead(
                title=f"Ready {idx}",
                agent_type="developer",
                description="ready work",
                status=BEAD_READY,
            )
            ready_ids.append(bead.bead_id)

        blocked_ids = []
        for idx in range(6):
            blocked = self.storage.create_bead(
                title=f"Blocked {idx}",
                agent_type="tester",
                description="blocked work",
                status=BEAD_BLOCKED,
            )
            blocked_ids.append(blocked.bead_id)
            if idx == 0:
                blocked.handoff_summary = HandoffSummary(block_reason="Needs dependency fix")
            else:
                blocked.block_reason = f"blocked-{idx}"
            self.storage.save_bead(blocked)

        self.storage.create_bead(title="Open", agent_type="planner", description="open", status=BEAD_OPEN)
        self.storage.create_bead(title="In progress", agent_type="developer", description="running", status=BEAD_IN_PROGRESS)
        self.storage.create_bead(title="Done", agent_type="review", description="finished", status=BEAD_DONE)
        self.storage.create_bead(title="Handed off", agent_type="documentation", description="handoff", status=BEAD_HANDED_OFF)

        summary = self.storage.summary()
        self.assertEqual(
            [BEAD_OPEN, BEAD_READY, BEAD_IN_PROGRESS, BEAD_BLOCKED, BEAD_DONE, BEAD_HANDED_OFF],
            list(summary["counts"].keys()),
        )
        self.assertEqual(1, summary["counts"][BEAD_OPEN])
        self.assertEqual(7, summary["counts"][BEAD_READY])
        self.assertEqual(1, summary["counts"][BEAD_IN_PROGRESS])
        self.assertEqual(6, summary["counts"][BEAD_BLOCKED])
        self.assertEqual(1, summary["counts"][BEAD_DONE])
        self.assertEqual(1, summary["counts"][BEAD_HANDED_OFF])

        self.assertEqual(5, len(summary["next_up"]))
        self.assertEqual(ready_ids[:5], [item["bead_id"] for item in summary["next_up"]])
        self.assertTrue(all(item["status"] == BEAD_READY for item in summary["next_up"]))

        self.assertEqual(5, len(summary["attention"]))
        self.assertEqual(
            blocked_ids[:5],
            [item["bead_id"] for item in summary["attention"]],
        )
        self.assertTrue(all(item["status"] == BEAD_BLOCKED for item in summary["attention"]))
        self.assertEqual("Needs dependency fix", summary["attention"][0]["block_reason"])

    def test_summary_can_filter_to_feature_root_tree(self) -> None:
        epic = self.storage.create_bead(title="Epic", agent_type="planner", description="root", status=BEAD_DONE, bead_type="epic")
        root_a = self.storage.create_bead(title="Feature A", agent_type="developer", description="A", parent_id=epic.bead_id, status=BEAD_DONE)
        root_b = self.storage.create_bead(title="Feature B", agent_type="developer", description="B", parent_id=epic.bead_id, status=BEAD_DONE)
        child_a1 = self.storage.create_bead(
            title="Feature A task 1",
            agent_type="developer",
            description="A1",
            parent_id=root_a.bead_id,
            dependencies=[root_a.bead_id],
            status=BEAD_READY,
        )
        child_a2 = self.storage.create_bead(
            title="Feature A task 2",
            agent_type="tester",
            description="A2",
            parent_id=root_a.bead_id,
            dependencies=[root_a.bead_id],
            status=BEAD_BLOCKED,
        )
        self.storage.create_bead(
            title="Feature B task 1",
            agent_type="developer",
            description="B1",
            parent_id=root_b.bead_id,
            dependencies=[root_b.bead_id],
            status=BEAD_READY,
        )

        summary = self.storage.summary(feature_root_id=root_a.bead_id)
        self.assertEqual(1, summary["counts"][BEAD_DONE])  # root_a
        self.assertEqual(1, summary["counts"][BEAD_READY])  # child_a1
        self.assertEqual(1, summary["counts"][BEAD_BLOCKED])  # child_a2
        self.assertEqual(0, summary["counts"][BEAD_OPEN])
        self.assertEqual(0, summary["counts"][BEAD_IN_PROGRESS])
        self.assertEqual(0, summary["counts"][BEAD_HANDED_OFF])
        self.assertEqual([child_a1.bead_id], [item["bead_id"] for item in summary["next_up"]])
        self.assertEqual([child_a2.bead_id], [item["bead_id"] for item in summary["attention"]])

        missing = self.storage.summary(feature_root_id="B9999")
        self.assertEqual(
            {
                BEAD_OPEN: 0,
                BEAD_READY: 0,
                BEAD_IN_PROGRESS: 0,
                BEAD_BLOCKED: 0,
                BEAD_DONE: 0,
                BEAD_HANDED_OFF: 0,
            },
            missing["counts"],
        )
        self.assertEqual([], missing["next_up"])
        self.assertEqual([], missing["attention"])

    def test_command_summary_outputs_json(self) -> None:
        self.storage.create_bead(title="Ready", agent_type="developer", description="work", status=BEAD_READY)
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)

        exit_code = command_summary(Namespace(feature_root=None), self.storage, console)

        self.assertEqual(0, exit_code)
        payload = json.loads(stream.getvalue())
        self.assertEqual(["counts", "next_up", "attention"], list(payload.keys()))
        self.assertEqual(
            [BEAD_OPEN, BEAD_READY, BEAD_IN_PROGRESS, BEAD_BLOCKED, BEAD_DONE, BEAD_HANDED_OFF],
            list(payload["counts"].keys()),
        )
        self.assertEqual(1, payload["counts"][BEAD_READY])
        self.assertEqual(1, len(payload["next_up"]))
        self.assertEqual([], payload["attention"])

    def test_command_summary_filters_by_feature_root_and_handles_unknown_root(self) -> None:
        epic = self.storage.create_bead(title="Epic", agent_type="planner", description="root", status=BEAD_DONE, bead_type="epic")
        root_a = self.storage.create_bead(title="Feature A", agent_type="developer", description="A", parent_id=epic.bead_id, status=BEAD_DONE)
        root_b = self.storage.create_bead(title="Feature B", agent_type="developer", description="B", parent_id=epic.bead_id, status=BEAD_DONE)
        child_a = self.storage.create_bead(
            title="Feature A task",
            agent_type="developer",
            description="A1",
            parent_id=root_a.bead_id,
            dependencies=[root_a.bead_id],
            status=BEAD_READY,
        )
        self.storage.create_bead(
            title="Feature B task",
            agent_type="developer",
            description="B1",
            parent_id=root_b.bead_id,
            dependencies=[root_b.bead_id],
            status=BEAD_READY,
        )

        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_summary(Namespace(feature_root=root_a.bead_id), self.storage, console)
        self.assertEqual(0, exit_code)
        filtered_payload = json.loads(stream.getvalue())
        self.assertEqual(1, filtered_payload["counts"][BEAD_DONE])  # root_a only
        self.assertEqual(1, filtered_payload["counts"][BEAD_READY])  # child_a only
        self.assertEqual([child_a.bead_id], [item["bead_id"] for item in filtered_payload["next_up"]])

        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_summary(Namespace(feature_root="B-nonexist"), self.storage, console)
        self.assertEqual(1, exit_code)

    def test_command_summary_ignores_non_feature_root_scope(self) -> None:
        epic = self.storage.create_bead(title="Epic", agent_type="planner", description="root", status=BEAD_DONE, bead_type="epic")
        root = self.storage.create_bead(title="Feature A", agent_type="developer", description="A", parent_id=epic.bead_id, status=BEAD_DONE)
        child = self.storage.create_bead(
            title="Feature A task",
            agent_type="developer",
            description="A1",
            parent_id=root.bead_id,
            dependencies=[root.bead_id],
            status=BEAD_READY,
        )

        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_summary(Namespace(feature_root=child.bead_id), self.storage, console)

        self.assertEqual(0, exit_code)
        payload = json.loads(stream.getvalue())
        self.assertEqual(0, payload["counts"][BEAD_DONE])
        self.assertEqual(0, payload["counts"][BEAD_READY])
        self.assertEqual([], payload["next_up"])
        self.assertEqual([], payload["attention"])

    def test_command_tui_reports_missing_render_dependency_without_mutating_state(self) -> None:
        bead = self.storage.create_bead(title="Ready", agent_type="developer", description="work", status=BEAD_READY)
        original = self.storage.load_bead(bead.bead_id).to_dict()
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)

        with patch("agent_takt.tui.load_textual_runtime", side_effect=RuntimeError("missing textual")):
            exit_code = command_tui(Namespace(feature_root=None, refresh_seconds=3, max_workers=1), self.storage, console)

        self.assertEqual(1, exit_code)
        self.assertIn("missing textual", stream.getvalue())
        self.assertEqual(original, self.storage.load_bead(bead.bead_id).to_dict())

    def test_command_tui_forwards_feature_root_refresh_and_console_stream(self) -> None:
        epic = self.storage.create_bead(title="Epic", agent_type="planner", description="root", status=BEAD_DONE, bead_type="epic")
        root = self.storage.create_bead(title="Feature A", agent_type="developer", description="A", parent_id=epic.bead_id, status=BEAD_DONE)
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)

        with patch("agent_takt.tui.run_tui", return_value=0) as run_tui:
            exit_code = command_tui(Namespace(feature_root=root.bead_id, refresh_seconds=9, max_workers=1), self.storage, console)

        self.assertEqual(0, exit_code)
        run_tui.assert_called_once_with(
            self.storage,
            feature_root_id=root.bead_id,
            refresh_seconds=9,
            max_workers=1,
            stream=stream,
        )

    def test_command_tui_rejects_unknown_feature_root(self) -> None:
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)

        with patch("agent_takt.tui.run_tui") as run_tui:
            exit_code = command_tui(Namespace(feature_root="B9999", refresh_seconds=3, max_workers=1), self.storage, console)

        self.assertEqual(1, exit_code)
        self.assertIn("B9999 is not a valid feature root", stream.getvalue())
        run_tui.assert_not_called()

    def test_command_tui_rejects_non_feature_root_scope(self) -> None:
        epic = self.storage.create_bead(title="Epic", agent_type="planner", description="root", status=BEAD_DONE, bead_type="epic")
        root = self.storage.create_bead(title="Feature A", agent_type="developer", description="A", parent_id=epic.bead_id, status=BEAD_DONE)
        child = self.storage.create_bead(
            title="Feature A task",
            agent_type="developer",
            description="A1",
            parent_id=root.bead_id,
            dependencies=[root.bead_id],
            status=BEAD_READY,
        )
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)

        with patch("agent_takt.tui.run_tui") as run_tui:
            exit_code = command_tui(Namespace(feature_root=child.bead_id, refresh_seconds=3, max_workers=1), self.storage, console)

        self.assertEqual(1, exit_code)
        self.assertIn(f"{child.bead_id} is not a valid feature root", stream.getvalue())
        run_tui.assert_not_called()

    def test_worker_prompt_includes_shared_feature_execution_context(self) -> None:
        bead = self.storage.create_bead(title="Implement", agent_type="developer", description="do work")
        prompt = build_worker_prompt(bead, [], self.root)
        self.assertIn('"feature_root_id"', prompt)
        self.assertIn('"execution_branch_name"', prompt)
        self.assertIn("shared feature worktree", prompt)
        self.assertIn("Agent guardrails:", prompt)
        self.assertIn(str(guardrail_template_path("developer", root=self.root)), prompt)
        self.assertIn("Primary responsibility: Implement only the assigned bead", prompt)

    def test_worker_prompt_loads_matching_guardrail_template_for_review(self) -> None:
        bead = self.storage.create_bead(title="Review", agent_type="review", description="inspect changes")
        bead.changed_files = ["src/agent_takt/scheduler.py"]
        prompt = build_worker_prompt(bead, [], self.root)
        self.assertIn(str(guardrail_template_path("review", root=self.root)), prompt)
        self.assertIn("Primary responsibility: Inspect code, tests, docs, and acceptance criteria", prompt)
        self.assertIn("return a blocked result with block_reason and next_agent", prompt)
        self.assertIn("always set `verdict` to `approved` or `needs_changes`", prompt)
        self.assertIn("Always set `findings_count`", prompt)
        self.assertIn("Set `requires_followup` explicitly", prompt)
        self.assertIn('"changed_files"', prompt)

    def test_worker_prompt_requires_structured_verdict_output_for_tester(self) -> None:
        bead = self.storage.create_bead(title="Tester", agent_type="tester", description="run checks")
        prompt = build_worker_prompt(bead, [], self.root)
        self.assertIn("always set `verdict` to `approved` or `needs_changes`", prompt)
        self.assertIn("Always set `findings_count`", prompt)
        self.assertIn("Set `requires_followup` explicitly", prompt)
        self.assertIn("include a concrete `block_reason`", prompt)

    def test_non_review_test_agents_get_baseline_structured_output_requirements(self) -> None:
        requirements = render_agent_output_requirements("developer")
        self.assertIn("always set `verdict` to `approved` or `needs_changes`", requirements)
        self.assertIn("Always set `findings_count`", requirements)
        self.assertIn("Set `requires_followup` explicitly", requirements)
        self.assertIn("Use `approved` when this bead is complete without follow-up", requirements)
        self.assertNotIn("For this agent type, set `findings_count` to the number of unresolved findings", requirements)

    def test_load_guardrail_template_returns_path_and_trimmed_contents_for_each_builtin_agent(self) -> None:
        for agent_type in BUILT_IN_AGENT_TYPES:
            with self.subTest(agent_type=agent_type):
                path, template_text = load_guardrail_template(agent_type, root=self.root)
                self.assertEqual(guardrail_template_path(agent_type, root=self.root), path)
                self.assertTrue(template_text.startswith(f"# {agent_type.capitalize()} Guardrails"))
                self.assertFalse(template_text.endswith("\n"))

    def test_review_and_tester_templates_require_structured_verdict_fields(self) -> None:
        for agent_type in ("review", "tester"):
            with self.subTest(agent_type=agent_type):
                _, template_text = load_guardrail_template(agent_type, root=self.root)
                self.assertIn("`verdict`, `findings_count`, and `requires_followup`", template_text)

    def test_worker_prompt_references_every_builtin_template_file(self) -> None:
        for agent_type in BUILT_IN_AGENT_TYPES:
            with self.subTest(agent_type=agent_type):
                bead = self.storage.create_bead(title=f"{agent_type} bead", agent_type=agent_type, description="scoped work")
                prompt = build_worker_prompt(bead, [], self.root)
                self.assertIn(f"Template: {guardrail_template_path(agent_type, root=self.root)}", prompt)

    def test_worker_prompt_uses_templates_from_provided_root(self) -> None:
        alt_root = self.root / "alt-root"
        for agent_type in BUILT_IN_AGENT_TYPES:
            template_path = alt_root / "templates" / "agents" / f"{agent_type}.md"
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_text(f"# {agent_type.capitalize()} Guardrails\n\nRoot marker: alt-root\n", encoding="utf-8")

        bead = self.storage.create_bead(title="Implement", agent_type="developer", description="do work")
        prompt = build_worker_prompt(bead, [], alt_root)
        self.assertIn(f"Template: {guardrail_template_path('developer', root=alt_root)}", prompt)
        self.assertIn("Root marker: alt-root", prompt)

    def test_linked_context_paths_falls_back_to_unique_basename_match(self) -> None:
        context_file = self.root / "simple-claims-plain-command.md"
        context_file.write_text("plain claims spec\n", encoding="utf-8")
        bead = self.storage.create_bead(
            title="Implement plain claims output",
            agent_type="developer",
            description="do work",
            linked_docs=["specs/simple-claims-plain-command.md"],
        )

        context_paths = self.storage.linked_context_paths(bead)

        self.assertIn(context_file.resolve(), [path.resolve() for path in context_paths])

    def test_linked_context_paths_skips_ambiguous_basename_matches(self) -> None:
        first = self.root / "docs" / "simple-claims-plain-command.md"
        second = self.root / "specs" / "simple-claims-plain-command.md"
        first.parent.mkdir(parents=True, exist_ok=True)
        second.parent.mkdir(parents=True, exist_ok=True)
        first.write_text("one\n", encoding="utf-8")
        second.write_text("two\n", encoding="utf-8")
        bead = self.storage.create_bead(
            title="Implement plain claims output",
            agent_type="developer",
            description="do work",
            linked_docs=["missing/simple-claims-plain-command.md"],
        )

        context_paths = self.storage.linked_context_paths(bead)

        resolved_context_paths = [path.resolve() for path in context_paths]
        self.assertNotIn(first.resolve(), resolved_context_paths)
        self.assertNotIn(second.resolve(), resolved_context_paths)

    def test_worker_prompt_raises_clear_error_when_guardrail_template_missing(self) -> None:
        template_path = guardrail_template_path("developer", root=self.root)
        original_text = template_path.read_text(encoding="utf-8")
        template_path.unlink()

        def restore_template() -> None:
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_text(original_text, encoding="utf-8")

        self.addCleanup(restore_template)

        bead = self.storage.create_bead(title="Implement", agent_type="developer", description="do work")
        with self.assertRaisesRegex(FileNotFoundError, "Missing guardrail template for built-in agent 'developer'"):
            build_worker_prompt(bead, [], self.root)

    def _make_execution_record(self, index: int) -> ExecutionRecord:
        return ExecutionRecord(
            timestamp=f"2026-01-{index:02d}T00:00:00+00:00",
            event=f"event_{index}",
            agent_type="developer",
            summary=f"Summary {index}",
            details={"index": index},
        )

    def test_worker_prompt_includes_all_history_when_at_or_below_cap(self) -> None:
        bead = self.storage.create_bead(title="Implement", agent_type="developer", description="do work")
        for i in range(1, 6):
            bead.execution_history.append(self._make_execution_record(i))
        prompt = build_worker_prompt(bead, [], self.root)
        payload = json.loads(prompt.split("Assigned bead:\n")[1].split("\n\nAvailable repository context")[0])
        self.assertEqual(5, len(payload["execution_history"]))
        self.assertEqual("event_1", payload["execution_history"][0]["event"])
        self.assertEqual("event_5", payload["execution_history"][4]["event"])

    def test_worker_prompt_truncates_execution_history_to_last_five(self) -> None:
        bead = self.storage.create_bead(title="Implement", agent_type="developer", description="do work")
        for i in range(1, 9):
            bead.execution_history.append(self._make_execution_record(i))
        prompt = build_worker_prompt(bead, [], self.root)
        payload = json.loads(prompt.split("Assigned bead:\n")[1].split("\n\nAvailable repository context")[0])
        self.assertEqual(5, len(payload["execution_history"]))
        events = [e["event"] for e in payload["execution_history"]]
        self.assertEqual(["event_4", "event_5", "event_6", "event_7", "event_8"], events)

    def test_worker_prompt_omits_early_history_entries_when_truncated(self) -> None:
        bead = self.storage.create_bead(title="Implement", agent_type="developer", description="do work")
        for i in range(1, 9):
            bead.execution_history.append(self._make_execution_record(i))
        prompt = build_worker_prompt(bead, [], self.root)
        payload = json.loads(prompt.split("Assigned bead:\n")[1].split("\n\nAvailable repository context")[0])
        early_events = {e["event"] for e in payload["execution_history"]}
        for omitted in ["event_1", "event_2", "event_3"]:
            self.assertNotIn(omitted, early_events)

    def test_worker_prompt_single_history_entry_included_verbatim(self) -> None:
        bead = self.storage.create_bead(title="Implement", agent_type="developer", description="do work")
        # create_bead adds one "created" record; verify it is passed through unchanged
        self.assertEqual(1, len(bead.execution_history))
        prompt = build_worker_prompt(bead, [], self.root)
        payload = json.loads(prompt.split("Assigned bead:\n")[1].split("\n\nAvailable repository context")[0])
        self.assertEqual(1, len(payload["execution_history"]))
        self.assertEqual("created", payload["execution_history"][0]["event"])

    def test_render_context_snippets_handles_paths_outside_worktree_root(self) -> None:
        repo_file = self.root / "specs" / "example.md"
        repo_file.parent.mkdir(parents=True, exist_ok=True)
        repo_file.write_text("spec\n", encoding="utf-8")
        worktree_root = self.root / ".takt" / "worktrees" / "B0002"
        worktree_root.mkdir(parents=True, exist_ok=True)
        rendered = render_context_snippets([repo_file], worktree_root)
        self.assertIn("example.md", rendered)

    def test_agent_output_schema_requires_all_new_bead_fields(self) -> None:
        required = AGENT_OUTPUT_SCHEMA["properties"]["new_beads"]["items"]["required"]
        self.assertEqual(
            ["title", "agent_type", "description", "acceptance_criteria", "dependencies", "linked_docs", "expected_files", "expected_globs"],
            required,
        )

    def test_agent_output_schema_requires_every_top_level_property(self) -> None:
        # Structured handoff fields (design_decisions, test_coverage_notes, known_limitations)
        # are intentionally optional (have defaults), so they appear in properties but not required.
        optional_fields = {"design_decisions", "test_coverage_notes", "known_limitations"}
        required_properties = [
            k for k in AGENT_OUTPUT_SCHEMA["properties"].keys()
            if k not in optional_fields
        ]
        self.assertEqual(required_properties, AGENT_OUTPUT_SCHEMA["required"])

    def test_agent_output_schema_new_beads_agent_type_has_valid_enum(self) -> None:
        agent_type_schema = AGENT_OUTPUT_SCHEMA["properties"]["new_beads"]["items"]["properties"]["agent_type"]
        self.assertIn("enum", agent_type_schema)
        self.assertEqual(
            sorted(agent_type_schema["enum"]),
            ["developer", "documentation", "planner", "review", "tester"],
        )

    def test_planner_output_schema_plan_child_agent_type_has_valid_enum(self) -> None:
        agent_type_schema = PLANNER_OUTPUT_SCHEMA["$defs"]["plan_child"]["properties"]["agent_type"]
        self.assertIn("enum", agent_type_schema)
        self.assertEqual(
            sorted(agent_type_schema["enum"]),
            ["developer", "documentation", "planner", "review", "tester"],
        )

    def test_tui_supports_default_grouped_and_terminal_filters(self) -> None:
        statuses = [
            BEAD_OPEN,
            BEAD_READY,
            BEAD_IN_PROGRESS,
            BEAD_BLOCKED,
            BEAD_HANDED_OFF,
            BEAD_DONE,
        ]
        for index, status in enumerate(statuses, start=1):
            self.storage.create_bead(
                bead_id=f"B{index:04d}",
                title=status,
                agent_type="developer",
                description=status,
                status=status,
            )

        default_rows = collect_tree_rows(self.storage, filter_mode=FILTER_DEFAULT)
        self.assertEqual(
            [BEAD_OPEN, BEAD_READY, BEAD_IN_PROGRESS, BEAD_BLOCKED, BEAD_HANDED_OFF],
            [row.bead.status for row in default_rows],
        )
        self.assertEqual([BEAD_OPEN, BEAD_READY], [row.bead.status for row in collect_tree_rows(self.storage, filter_mode=FILTER_ACTIONABLE)])
        self.assertEqual([BEAD_HANDED_OFF], [row.bead.status for row in collect_tree_rows(self.storage, filter_mode=FILTER_DEFERRED)])
        self.assertEqual([BEAD_DONE], [row.bead.status for row in collect_tree_rows(self.storage, filter_mode=FILTER_DONE)])
        self.assertEqual(statuses, [row.bead.status for row in collect_tree_rows(self.storage, filter_mode=FILTER_ALL)])
        self.assertIn(BEAD_DONE, supported_filter_modes())

    def test_tui_feature_root_filter_keeps_root_when_status_filter_hides_it(self) -> None:
        root = self.storage.create_bead(
            bead_id="B0001",
            title="Feature Root",
            agent_type="developer",
            description="root",
            status=BEAD_DONE,
        )
        self.storage.create_bead(
            bead_id="B0001-test",
            title="Child",
            agent_type="developer",
            description="child",
            parent_id=root.bead_id,
            status=BEAD_READY,
        )

        rows = collect_tree_rows(self.storage, filter_mode=FILTER_DEFAULT, feature_root_id=root.bead_id)

        self.assertEqual(["B0001", "B0001-test"], [row.bead_id for row in rows])
        self.assertEqual([0, 1], [row.depth for row in rows])
        self.assertEqual([BEAD_DONE, BEAD_READY], [row.bead.status for row in rows])

    def test_tui_tree_rows_are_deterministic_and_indent_descendants(self) -> None:
        root_b = Bead(bead_id="B0002", title="Root B", agent_type="developer", description="b")
        child_b2 = Bead(
            bead_id="B0002-2",
            title="Child B2",
            agent_type="developer",
            description="b2",
            parent_id="B0002",
        )
        root_a = Bead(bead_id="B0001", title="Root A", agent_type="developer", description="a")
        child_a2 = Bead(
            bead_id="B0001-2",
            title="Child A2",
            agent_type="developer",
            description="a2",
            parent_id="B0001",
        )
        child_a1 = Bead(
            bead_id="B0001-1",
            title="Child A1",
            agent_type="developer",
            description="a1",
            parent_id="B0001",
        )
        grandchild = Bead(
            bead_id="B0001-1-1",
            title="Grandchild",
            agent_type="developer",
            description="a11",
            parent_id="B0001-1",
        )

        rows = build_tree_rows([child_b2, child_a2, root_b, grandchild, root_a, child_a1])

        self.assertEqual(
            ["B0001", "B0001-1", "B0001-1-1", "B0001-2", "B0002", "B0002-2"],
            [row.bead_id for row in rows],
        )
        self.assertEqual([0, 1, 2, 1, 0, 1], [row.depth for row in rows])
        self.assertEqual("  B0001-1 · Child A1", rows[1].label)
        self.assertEqual("    B0001-1-1 · Grandchild", rows[2].label)

    def test_tui_selection_preserves_selected_bead_when_visible(self) -> None:
        first = Bead(bead_id="B0001", title="First", agent_type="developer", description="one")
        second = Bead(bead_id="B0002", title="Second", agent_type="developer", description="two")
        rows = build_tree_rows([first, second])

        self.assertEqual(1, resolve_selected_index(rows, selected_bead_id="B0002", previous_index=0))
        self.assertEqual("B0002", resolve_selected_bead(rows, selected_bead_id="B0002", previous_index=0).bead_id)
        self.assertEqual(1, resolve_selected_index(rows, selected_bead_id="B9999", previous_index=3))
        self.assertEqual("B0001", resolve_selected_bead(rows, previous_index=None).bead_id)

    def test_tui_detail_panel_and_footer_include_handoff_scope_and_counts(self) -> None:
        bead = Bead(
            bead_id="B0099",
            title="Implement TUI",
            agent_type="developer",
            description="build helpers",
            status=BEAD_BLOCKED,
            parent_id="B0090",
            feature_root_id="B0030",
            dependencies=["B0098"],
            acceptance_criteria=["Build rows", "Format detail panel"],
            expected_files=["src/agent_takt/tui.py"],
            expected_globs=["tests/test_tui*.py"],
            touched_files=["src/agent_takt/tui.py"],
            changed_files=["src/agent_takt/tui.py", "tests/test_orchestrator.py"],
            updated_docs=["docs/tui.md"],
            block_reason="Waiting on review",
            conflict_risks="Coordinate with review bead on footer text.",
            handoff_summary=HandoffSummary(
                completed="Implemented the TUI helpers.",
                remaining="Need review signoff.",
                risks="Footer wording may change with runtime integration.",
                changed_files=["src/agent_takt/tui.py", "tests/test_orchestrator.py"],
                updated_docs=["docs/tui.md"],
                next_action="Run the review bead.",
                next_agent="review",
                block_reason="Waiting on review",
                expected_files=["src/agent_takt/tui.py"],
                expected_globs=["tests/test_tui*.py"],
                touched_files=["src/agent_takt/tui.py"],
                conflict_risks="Coordinate with review bead on footer text.",
            ),
        )

        detail = format_detail_panel(bead)
        footer = format_footer(
            [bead],
            filter_mode=FILTER_DEFAULT,
            selected_index=0,
            total_rows=1,
            continuous_run_enabled=False,
        )

        self.assertIn("Bead: B0099", detail)
        self.assertIn("Status: blocked", detail)
        self.assertIn("Parent: B0090", detail)
        self.assertIn("Feature Root: B0030", detail)
        self.assertIn("Dependencies: B0098", detail)
        self.assertIn("  - Build rows", detail)
        self.assertIn("  changed: src/agent_takt/tui.py, tests/test_orchestrator.py", detail)
        self.assertIn("  next_agent: review", detail)
        self.assertIn("  conflict_risks: Coordinate with review bead on footer text.", detail)
        self.assertEqual(
            "filter=default | run=manual | rows=1 | selected=1 | open=0 | ready=0 | in_progress=0 | blocked=1 | handed_off=0 | done=0",
            footer.removesuffix(" | ? help"),
        )
        self.assertTrue(footer.endswith(" | ? help"))

    def test_tui_detail_panel_handles_empty_selection_and_empty_scope_lists(self) -> None:
        self.assertEqual("No bead selected.", format_detail_panel(None))

        bead = Bead(
            bead_id="B0100",
            title="Empty detail state",
            agent_type="tester",
            description="verify formatter fallbacks",
        )

        detail = format_detail_panel(bead)

        self.assertIn("Dependencies: -", detail)
        self.assertIn("Acceptance Criteria:\n  -", detail)
        self.assertIn("Block Reason: -", detail)
        self.assertIn("  expected: -", detail)
        self.assertIn("  conflict_risks: -", detail)

    def test_tui_runtime_refresh_preserves_selection_and_shows_new_rows(self) -> None:
        first = self.storage.create_bead(bead_id="B0001", title="First", agent_type="developer", description="one", status=BEAD_READY)
        second = self.storage.create_bead(bead_id="B0002", title="Second", agent_type="developer", description="two", status=BEAD_BLOCKED)
        state = TuiRuntimeState(self.storage)
        state.selected_bead_id = second.bead_id
        state.selected_index = 1

        self.storage.create_bead(bead_id="B0003", title="Third", agent_type="developer", description="three", status=BEAD_READY)
        state.refresh()

        self.assertEqual(second.bead_id, state.selected_bead_id)
        self.assertEqual(second.bead_id, state.selected_bead().bead_id)
        self.assertEqual(["B0001", "B0002", "B0003"], [row.bead_id for row in state.rows])

    def test_tui_runtime_cycles_filters_and_updates_status_panel(self) -> None:
        self.storage.create_bead(bead_id="B0001", title="Open", agent_type="developer", description="one", status=BEAD_OPEN)
        self.storage.create_bead(bead_id="B0002", title="Done", agent_type="developer", description="two", status=BEAD_DONE)
        state = TuiRuntimeState(self.storage)

        state.cycle_filter(1)

        self.assertEqual(FILTER_ALL, state.filter_mode)
        self.assertIn("Filter set to all.", state.status_panel_text())
        self.assertIn("done=1", state.status_panel_text())

    def test_tui_runtime_merge_shows_cli_redirect_for_any_bead(self) -> None:
        # TUI no longer performs merges inline; it shows the CLI command regardless of bead status
        bead = self.storage.create_bead(bead_id="B0001", title="Ready", agent_type="developer", description="one", status=BEAD_READY)
        state = TuiRuntimeState(self.storage)

        state.request_merge()

        self.assertFalse(state.awaiting_merge_confirmation)
        self.assertIsNone(state.pending_merge_bead_id)
        self.assertIn(f"takt merge {bead.bead_id}", state.status_message)

    def test_tui_runtime_merge_shows_cli_redirect_for_done_bead(self) -> None:
        # TUI redirects to CLI instead of executing merge inline
        bead = self.storage.create_bead(bead_id="B0001", title="Done", agent_type="developer", description="one", status=BEAD_DONE)
        state = TuiRuntimeState(self.storage, filter_mode=FILTER_ALL)

        state.request_merge()

        self.assertFalse(state.awaiting_merge_confirmation)
        self.assertIsNone(state.pending_merge_bead_id)
        self.assertIn(f"takt merge {bead.bead_id}", state.status_message)

    def test_tui_runtime_confirm_merge_no_op_when_no_pending_state(self) -> None:
        # confirm_merge returns False gracefully when awaiting_merge_confirmation is False
        self.storage.create_bead(bead_id="B0001", title="Done", agent_type="developer", description="one", status=BEAD_DONE)
        state = TuiRuntimeState(self.storage, filter_mode=FILTER_ALL)

        # request_merge no longer sets awaiting_merge_confirmation
        state.request_merge()
        self.assertFalse(state.awaiting_merge_confirmation)

        merged = state.confirm_merge()

        self.assertFalse(merged)
        self.assertEqual("No merge pending confirmation.", state.status_message)

    def test_tui_runtime_merge_clears_other_pending_states(self) -> None:
        # request_merge clears pending retry/status flows
        bead = self.storage.create_bead(bead_id="B0001", title="Done", agent_type="developer", description="one", status=BEAD_DONE)
        state = TuiRuntimeState(self.storage, filter_mode=FILTER_ALL)

        state.request_merge()

        self.assertFalse(state.awaiting_retry_confirmation)
        self.assertFalse(state.status_flow_active)
        self.assertIn(f"takt merge {bead.bead_id}", state.status_message)

    def test_tui_render_tree_panel_marks_selected_row(self) -> None:
        rows = build_tree_rows([
            Bead(bead_id="B0001", title="One", agent_type="developer", description="one", status=BEAD_READY),
            Bead(bead_id="B0002", title="Two", agent_type="developer", description="two", status=BEAD_BLOCKED),
        ])

        panel = render_tree_panel(rows, 1)

        self.assertIn("> B0002 · Two [blocked]", panel)
        self.assertIn("  B0001 · One [ready]", panel)
        self.assertNotIn("Beads [", panel)

    def test_run_tui_returns_nonzero_and_hint_when_textual_missing(self) -> None:
        stream = io.StringIO()

        with patch("agent_takt.tui.load_textual_runtime", side_effect=RuntimeError("missing textual")):
            exit_code = run_tui(self.storage, stream=stream)

        self.assertEqual(1, exit_code)
        self.assertIn("Hint: install project dependencies", stream.getvalue())


    def test_allocate_bead_id_returns_uuid_format(self) -> None:
        bead_id = self.storage.allocate_bead_id()
        import re
        self.assertRegex(bead_id, r"^B-[0-9a-f]{8}$")

    def test_allocate_bead_id_returns_unique_ids(self) -> None:
        ids = {self.storage.allocate_bead_id() for _ in range(20)}
        self.assertEqual(20, len(ids))

    def test_allocate_bead_id_via_create_bead_uses_uuid_format(self) -> None:
        import re
        bead = self.storage.create_bead(title="UUID test", agent_type="developer", description="work")
        self.assertRegex(bead.bead_id, r"^B-[0-9a-f]{8}$")

    def test_resolve_bead_id_exact_match(self) -> None:
        bead = self.storage.create_bead(title="Exact", agent_type="developer", description="work")
        resolved = self.storage.resolve_bead_id(bead.bead_id)
        self.assertEqual(bead.bead_id, resolved)

    def test_resolve_bead_id_prefix_match(self) -> None:
        bead = self.storage.create_bead(title="Prefix", agent_type="developer", description="work")
        # Use a 4-char prefix (B- plus 2 hex chars) that is unambiguous
        prefix = bead.bead_id[:4]
        # If only one bead exists, the prefix resolves to it
        resolved = self.storage.resolve_bead_id(prefix)
        self.assertEqual(bead.bead_id, resolved)

    def test_resolve_bead_id_no_match_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.storage.resolve_bead_id("B-nonexist")
        self.assertIn("No bead found", str(ctx.exception))

    def test_resolve_bead_id_ambiguous_raises(self) -> None:
        # Create two beads then find a common prefix
        bead_a = self.storage.create_bead(title="A", agent_type="developer", description="a")
        bead_b = self.storage.create_bead(title="B", agent_type="developer", description="b")
        # Find a shared prefix (both start with "B-")
        with self.assertRaises(ValueError) as ctx:
            self.storage.resolve_bead_id("B-")
        self.assertIn("Ambiguous prefix", str(ctx.exception))
        self.assertIn(bead_a.bead_id, str(ctx.exception))
        self.assertIn(bead_b.bead_id, str(ctx.exception))

    def test_resolve_bead_id_no_beads_dir_raises(self) -> None:
        import shutil
        shutil.rmtree(self.storage.beads_dir)
        with self.assertRaises(ValueError) as ctx:
            self.storage.resolve_bead_id("B-anything")
        self.assertIn("No bead found", str(ctx.exception))

    def test_cli_handoff_resolves_prefix(self) -> None:
        bead = self.storage.create_bead(title="Handoff me", agent_type="developer", description="done")
        prefix = bead.bead_id[:4]
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_handoff(
            Namespace(bead_id=prefix, to="tester", summary="Hand off to tester"),
            self.storage,
            console,
        )
        self.assertEqual(0, exit_code)
        beads = self.storage.list_beads()
        child_ids = [b.bead_id for b in beads if b.bead_id != bead.bead_id]
        self.assertEqual(1, len(child_ids))
        child = self.storage.load_bead(child_ids[0])
        self.assertEqual("tester", child.agent_type)
        self.assertIn(bead.bead_id, child.dependencies)

    def test_cli_retry_resolves_prefix(self) -> None:
        bead = self.storage.create_bead(title="Retry me", agent_type="developer", description="blocked")
        bead.status = BEAD_BLOCKED
        bead.block_reason = "something failed"
        self.storage.save_bead(bead)
        prefix = bead.bead_id[:4]
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_retry(Namespace(bead_id=prefix), self.storage, console)
        self.assertEqual(0, exit_code)
        reloaded = self.storage.load_bead(bead.bead_id)
        self.assertEqual(BEAD_READY, reloaded.status)
        self.assertEqual("", reloaded.block_reason)

    def test_cli_summary_resolves_feature_root_prefix(self) -> None:
        bead = self.storage.create_bead(title="Feature root", agent_type="developer", description="work")
        prefix = bead.bead_id[:4]
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_summary(Namespace(feature_root=prefix), self.storage, console)
        self.assertEqual(0, exit_code)
        data = json.loads(stream.getvalue())
        self.assertIn("counts", data)

    def test_cli_summary_returns_error_on_invalid_feature_root_prefix(self) -> None:
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_summary(Namespace(feature_root="B-nonexist"), self.storage, console)
        self.assertEqual(1, exit_code)

    def test_cli_summary_no_feature_root_passes_none(self) -> None:
        stream = io.StringIO()
        console = ConsoleReporter(stream=stream)
        exit_code = command_summary(Namespace(feature_root=None), self.storage, console)
        self.assertEqual(0, exit_code)
        data = json.loads(stream.getvalue())
        self.assertIn("counts", data)

    def test_list_beads_sorted_by_creation_time(self) -> None:
        """list_beads() returns beads ordered by creation timestamp, not by ID."""
        import time
        bead_a = self.storage.create_bead(title="Alpha", agent_type="developer", description="first")
        time.sleep(0.01)  # ensure distinct timestamps
        bead_b = self.storage.create_bead(title="Beta", agent_type="developer", description="second")
        beads = self.storage.list_beads()
        ids = [b.bead_id for b in beads]
        self.assertEqual([bead_a.bead_id, bead_b.bead_id], ids)

    def test_old_sequential_ids_coexist_with_uuid_ids(self) -> None:
        """Beads with old sequential IDs (B0001) load alongside new UUID-format IDs."""
        import re
        # Create a bead with the old sequential format
        old_bead = self.storage.create_bead(
            bead_id="B0001",
            title="Legacy bead",
            agent_type="developer",
            description="old format",
        )
        # Create a bead with the new UUID format (auto-allocated)
        new_bead = self.storage.create_bead(title="UUID bead", agent_type="developer", description="new format")
        self.assertRegex(new_bead.bead_id, r"^B-[0-9a-f]{8}$")

        beads = self.storage.list_beads()
        bead_ids = {b.bead_id for b in beads}
        self.assertIn("B0001", bead_ids)
        self.assertIn(new_bead.bead_id, bead_ids)
        # Both load successfully
        loaded_old = self.storage.load_bead("B0001")
        self.assertEqual("Legacy bead", loaded_old.title)
        loaded_new = self.storage.load_bead(new_bead.bead_id)
        self.assertEqual("UUID bead", loaded_new.title)



if __name__ == "__main__":
    unittest.main()
