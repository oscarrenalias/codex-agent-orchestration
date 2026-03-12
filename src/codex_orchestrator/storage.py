from __future__ import annotations

import json
from pathlib import Path

from .models import (
    BEAD_DONE,
    BEAD_READY,
    Bead,
    ExecutionRecord,
    HandoffSummary,
    utc_now,
)


class RepositoryStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.state_dir = self.root / ".orchestrator"
        self.beads_dir = self.state_dir / "beads"
        self.logs_dir = self.state_dir / "logs"
        self.worktrees_dir = self.state_dir / "worktrees"
        self.memory_dir = self.root / "docs" / "memory"

    def initialize(self) -> None:
        for path in (self.beads_dir, self.logs_dir, self.worktrees_dir, self.memory_dir):
            path.mkdir(parents=True, exist_ok=True)

    def bead_path(self, bead_id: str) -> Path:
        return self.beads_dir / f"{bead_id}.json"

    def save_bead(self, bead: Bead) -> None:
        self.initialize()
        self.bead_path(bead.bead_id).write_text(json.dumps(bead.to_dict(), indent=2) + "\n", encoding="utf-8")

    def load_bead(self, bead_id: str) -> Bead:
        return Bead.from_dict(json.loads(self.bead_path(bead_id).read_text(encoding="utf-8")))

    def list_beads(self) -> list[Bead]:
        if not self.beads_dir.exists():
            return []
        beads = [self.load_bead(path.stem) for path in sorted(self.beads_dir.glob("*.json"))]
        return sorted(beads, key=lambda bead: bead.bead_id)

    def allocate_bead_id(self) -> str:
        self.initialize()
        numbers: list[int] = []
        for path in self.beads_dir.glob("B*.json"):
            stem = path.stem
            if stem.startswith("B") and stem[1:].isdigit():
                numbers.append(int(stem[1:]))
        return f"B{(max(numbers) + 1) if numbers else 1:04d}"

    def allocate_child_bead_id(self, parent_id: str, suffix: str) -> str:
        candidate = f"{parent_id}-{suffix}"
        if not self.bead_path(candidate).exists():
            return candidate
        index = 2
        while self.bead_path(f"{candidate}-{index}").exists():
            index += 1
        return f"{candidate}-{index}"

    def create_bead(
        self,
        *,
        title: str,
        agent_type: str,
        description: str,
        status: str = BEAD_READY,
        bead_type: str = "task",
        parent_id: str | None = None,
        dependencies: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        linked_docs: list[str] | None = None,
        bead_id: str | None = None,
        metadata: dict | None = None,
    ) -> Bead:
        bead = Bead(
            bead_id=bead_id or self.allocate_bead_id(),
            title=title,
            agent_type=agent_type,
            description=description,
            status=status,
            bead_type=bead_type,
            parent_id=parent_id,
            dependencies=list(dependencies or []),
            acceptance_criteria=list(acceptance_criteria or []),
            linked_docs=list(linked_docs or []),
            metadata=dict(metadata or {}),
        )
        bead.execution_history.append(
            ExecutionRecord(timestamp=utc_now(), event="created", agent_type="scheduler", summary="Bead created")
        )
        self.save_bead(bead)
        return bead

    def update_bead(self, bead: Bead, *, event: str | None = None, summary: str = "") -> None:
        if event:
            bead.execution_history.append(
                ExecutionRecord(timestamp=utc_now(), event=event, agent_type=bead.agent_type, summary=summary)
            )
        self.save_bead(bead)

    def dependency_satisfied(self, bead: Bead) -> bool:
        return all(self.load_bead(dep).status == BEAD_DONE for dep in bead.dependencies)

    def ready_beads(self) -> list[Bead]:
        ready: list[Bead] = []
        for bead in self.list_beads():
            if bead.status != BEAD_READY:
                continue
            if bead.lease is not None:
                continue
            if self.dependency_satisfied(bead):
                ready.append(bead)
        return sorted(ready, key=lambda item: item.bead_id)

    def record_event(self, event_type: str, payload: dict) -> None:
        self.initialize()
        event_path = self.logs_dir / "events.jsonl"
        record = {"timestamp": utc_now(), "event_type": event_type, "payload": payload}
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def write_memory_file(self, relative_path: str, content: str) -> Path:
        target = self.memory_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def linked_context_paths(self, bead: Bead) -> list[Path]:
        candidates = [self.root / path for path in bead.linked_docs]
        agents_path = self.root / "AGENTS.md"
        if agents_path.exists():
            candidates.append(agents_path)
        if self.memory_dir.exists():
            candidates.extend(sorted(path for path in self.memory_dir.rglob("*") if path.is_file()))
        return [path for path in candidates if path.exists()]

    def set_handoff(self, bead: Bead, handoff: HandoffSummary) -> None:
        bead.handoff_summary = handoff
        bead.changed_files = list(handoff.changed_files)
        bead.updated_docs = list(handoff.updated_docs)
        self.save_bead(bead)
