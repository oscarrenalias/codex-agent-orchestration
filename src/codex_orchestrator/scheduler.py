from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .gitutils import GitError, WorktreeManager
from .models import (
    AGENT_TYPES,
    BEAD_BLOCKED,
    BEAD_DONE,
    BEAD_IN_PROGRESS,
    BEAD_READY,
    ExecutionRecord,
    HandoffSummary,
    Lease,
    MUTATING_AGENTS,
    AgentRunResult,
    Bead,
    SchedulerResult,
    utc_now,
)
from .runner import AgentRunner
from .storage import RepositoryStorage


FOLLOWUP_SUFFIXES = {
    "tester": "test",
    "documentation": "docs",
    "review": "review",
}


class Scheduler:
    def __init__(self, storage: RepositoryStorage, runner: AgentRunner, worktrees: WorktreeManager) -> None:
        self.storage = storage
        self.runner = runner
        self.worktrees = worktrees

    def expire_stale_leases(self, *, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        expired: list[str] = []
        for bead in self.storage.list_beads():
            if bead.lease is None:
                continue
            if datetime.fromisoformat(bead.lease.expires_at) <= now:
                bead.lease = None
                if bead.status == BEAD_IN_PROGRESS:
                    bead.status = BEAD_READY
                bead.execution_history.append(
                    ExecutionRecord(
                        timestamp=utc_now(),
                        event="lease_expired",
                        agent_type="scheduler",
                        summary="Lease expired and bead was requeued",
                    )
                )
                self.storage.save_bead(bead)
                expired.append(bead.bead_id)
        return expired

    def run_once(self, *, max_workers: int = 1, reporter: "SchedulerReporter | None" = None) -> SchedulerResult:
        result = SchedulerResult()
        expired = self.expire_stale_leases()
        if reporter:
            for bead_id in expired:
                reporter.lease_expired(bead_id)
        for bead in self.storage.ready_beads()[:max_workers]:
            result.started.append(bead.bead_id)
            self._process(bead, result, reporter=reporter)
        return result

    def _process(self, bead: Bead, result: SchedulerResult, *, reporter: "SchedulerReporter | None" = None) -> None:
        workdir = self.storage.root
        bead.status = BEAD_IN_PROGRESS
        bead.lease = Lease(owner=f"{bead.agent_type}:{bead.bead_id}", expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat())
        if reporter:
            reporter.bead_started(bead)
        if bead.agent_type in MUTATING_AGENTS:
            branch_name = bead.branch_name or f"bead/{bead.bead_id.lower()}"
            try:
                worktree_path = self.worktrees.ensure_worktree(bead.bead_id, branch_name)
            except GitError as exc:
                bead.status = BEAD_BLOCKED
                bead.lease = None
                bead.block_reason = str(exc)
                self.storage.update_bead(bead, event="blocked", summary=str(exc))
                result.blocked.append(bead.bead_id)
                if reporter:
                    reporter.bead_blocked(bead, str(exc))
                return
            bead.branch_name = branch_name
            bead.worktree_path = str(worktree_path)
            workdir = worktree_path
            if reporter:
                reporter.worktree_ready(bead, branch_name, worktree_path)
        self.storage.update_bead(bead, event="started", summary="Worker started")
        context_paths = self.storage.linked_context_paths(bead)
        try:
            agent_result = self.runner.run_bead(bead, workdir=Path(workdir), context_paths=context_paths)
        except Exception as exc:
            agent_result = AgentRunResult(
                outcome="failed",
                summary=f"Worker execution failed: {exc}",
                block_reason=str(exc),
            )
        self._finalize(bead, agent_result, result, reporter=reporter)

    def _finalize(self, bead: Bead, agent_result: AgentRunResult, result: SchedulerResult, *, reporter: "SchedulerReporter | None" = None) -> None:
        bead.lease = None
        bead.block_reason = agent_result.block_reason
        handoff = HandoffSummary(
            completed=agent_result.completed,
            remaining=agent_result.remaining,
            risks=agent_result.risks,
            changed_files=agent_result.changed_files,
            updated_docs=agent_result.updated_docs,
            next_action=agent_result.next_action,
        )
        bead.handoff_summary = handoff
        bead.changed_files = list(agent_result.changed_files)
        bead.updated_docs = list(agent_result.updated_docs)

        if agent_result.outcome == "blocked":
            bead.status = BEAD_BLOCKED
            self.storage.update_bead(bead, event="blocked", summary=agent_result.summary)
            result.blocked.append(bead.bead_id)
            if reporter:
                reporter.bead_blocked(bead, agent_result.summary)
            return

        if agent_result.outcome == "failed":
            bead.status = BEAD_BLOCKED
            bead.retries += 1
            self.storage.update_bead(bead, event="failed", summary=agent_result.summary)
            result.blocked.append(bead.bead_id)
            if reporter:
                reporter.bead_failed(bead, agent_result.summary)
            return

        bead.status = BEAD_DONE
        self.storage.update_bead(bead, event="completed", summary=agent_result.summary)
        self.storage.record_event("bead_completed", {"bead_id": bead.bead_id, "agent_type": bead.agent_type})
        created = self._create_followups(bead, agent_result)
        if reporter:
            reporter.bead_completed(bead, agent_result.summary, created)
        result.completed.append(bead.bead_id)

    def _create_followups(self, bead: Bead, agent_result: AgentRunResult) -> list[Bead]:
        created: list[Bead] = []
        for new_bead in agent_result.new_beads:
            child_id = self.storage.allocate_child_bead_id(bead.bead_id, "subtask")
            created.append(self.storage.create_bead(
                bead_id=child_id,
                title=new_bead["title"],
                agent_type=new_bead["agent_type"],
                description=new_bead["description"],
                parent_id=bead.bead_id,
                dependencies=list(new_bead.get("dependencies", [])),
                acceptance_criteria=list(new_bead.get("acceptance_criteria", [])),
                linked_docs=list(new_bead.get("linked_docs", [])),
                metadata={"discovered_by": bead.bead_id},
            ))

        if bead.agent_type != "developer":
            return created

        test_id = self._existing_or_new_child_id(bead.bead_id, FOLLOWUP_SUFFIXES["tester"])
        doc_id = self._existing_or_new_child_id(bead.bead_id, FOLLOWUP_SUFFIXES["documentation"])
        review_id = self._existing_or_new_child_id(bead.bead_id, FOLLOWUP_SUFFIXES["review"])

        if not self.storage.bead_path(test_id).exists():
            created.append(self.storage.create_bead(
                bead_id=test_id,
                title=f"Test {bead.title}",
                agent_type="tester",
                description=f"Validate implementation for {bead.bead_id}",
                parent_id=bead.bead_id,
                dependencies=[bead.bead_id],
                linked_docs=bead.linked_docs,
            ))
        if not self.storage.bead_path(doc_id).exists():
            created.append(self.storage.create_bead(
                bead_id=doc_id,
                title=f"Document {bead.title}",
                agent_type="documentation",
                description=f"Update docs for {bead.bead_id}",
                parent_id=bead.bead_id,
                dependencies=[bead.bead_id],
                linked_docs=bead.linked_docs,
            ))
        if not self.storage.bead_path(review_id).exists():
            created.append(self.storage.create_bead(
                bead_id=review_id,
                title=f"Review {bead.title}",
                agent_type="review",
                description=f"Review implementation for {bead.bead_id}",
                parent_id=bead.bead_id,
                dependencies=[bead.bead_id, test_id, doc_id],
                linked_docs=bead.linked_docs,
            ))
        return created

    def _existing_or_new_child_id(self, parent_id: str, suffix: str) -> str:
        base = f"{parent_id}-{suffix}"
        for bead in self.storage.list_beads():
            if bead.parent_id == parent_id and bead.bead_id == base:
                return bead.bead_id
        return self.storage.allocate_child_bead_id(parent_id, suffix)


class SchedulerReporter(Protocol):
    def lease_expired(self, bead_id: str) -> None: ...

    def bead_started(self, bead: Bead) -> None: ...

    def worktree_ready(self, bead: Bead, branch_name: str, worktree_path: Path) -> None: ...

    def bead_completed(self, bead: Bead, summary: str, created: list[Bead]) -> None: ...

    def bead_blocked(self, bead: Bead, summary: str) -> None: ...

    def bead_failed(self, bead: Bead, summary: str) -> None: ...
