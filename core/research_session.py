from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Optional


class ResearchSession:
    """
    Tracks the state of one depth-first research session:
    - the overarching macro question
    - the ordered thread of completed cycles
    - the branch registry (parallel directions saved for later)
    - milestone pause points
    """

    def __init__(
        self,
        macro_question: str,
        session_id: str = None,
        heartbeat_interval: int = 5,
    ) -> None:
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.macro_question = macro_question
        self.started_at = datetime.now().isoformat()
        self.updated_at = self.started_at
        self.heartbeat_interval = heartbeat_interval
        self.cycles_since_milestone = 0

        # ACTIVE | PAUSED_MILESTONE | COMPLETED
        self.status = "ACTIVE"

        # Ordered depth-first chain of explored cycles
        self.thread: list[dict] = []

        # Parallel directions saved by the navigator for future exploration
        self.branch_registry: list[dict] = []

        # Human-review pause points
        self.milestones: list[dict] = []

    # ── Thread management ────────────────────────────────────────────────

    def record_cycle(
        self,
        cycle_num: int,
        conjecture: str,
        status: str,
        reasoning: str,
        nav_direction: str = "",
    ) -> None:
        self.thread.append(
            {
                "cycle": cycle_num,
                "conjecture": conjecture[:600],
                "status": status,
                "reasoning": reasoning[:400],
                "nav_direction": nav_direction[:300],
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.updated_at = datetime.now().isoformat()

    def thread_summary(self, max_recent: int = 5) -> str:
        if not self.thread:
            return "No cycles completed yet in this session."
        total = len(self.thread)
        recent = self.thread[-max_recent:]
        lines = [f"Thread depth: {total} cycle(s) completed."]
        if total > max_recent:
            lines.append(f"  [...{total - max_recent} earlier cycle(s) omitted...]")
        for entry in recent:
            snippet = entry["conjecture"]
            if len(snippet) > 140:
                snippet = snippet[:140] + "..."
            lines.append(f"  Cycle {entry['cycle']} [{entry['status']}]: {snippet}")
        return "\n".join(lines)

    # ── Branch registry ──────────────────────────────────────────────────

    def add_branches(self, branches: list[dict]) -> None:
        for b in branches:
            b_id = b.get("id") or f"branch_{uuid.uuid4().hex[:6]}"
            if any(e["id"] == b_id for e in self.branch_registry):
                continue
            self.branch_registry.append(
                {
                    "id": b_id,
                    "direction": b.get("direction", ""),
                    "motivation": b.get("motivation", ""),
                    "origin_cycle": len(self.thread),
                    "created_at": datetime.now().isoformat(),
                    "status": "PENDING",  # PENDING | ACTIVE | COMPLETED
                }
            )

    def activate_branch(self, branch_id: str) -> Optional[dict]:
        for b in self.branch_registry:
            if b["id"] == branch_id and b["status"] == "PENDING":
                b["status"] = "ACTIVE"
                return b
        return None

    def pending_branches(self) -> list[dict]:
        return [b for b in self.branch_registry if b["status"] == "PENDING"]

    # ── Milestones ───────────────────────────────────────────────────────

    def record_milestone(self, cycle_num: int, reason: str) -> None:
        self.milestones.append(
            {
                "cycle": cycle_num,
                "reason": reason,
                "thread_depth": len(self.thread),
                "timestamp": datetime.now().isoformat(),
            }
        )

    # ── Serialisation ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "macro_question": self.macro_question,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "heartbeat_interval": self.heartbeat_interval,
            "cycles_since_milestone": self.cycles_since_milestone,
            "thread": self.thread,
            "branch_registry": self.branch_registry,
            "milestones": self.milestones,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchSession":
        s = cls(
            macro_question=data["macro_question"],
            session_id=data.get("session_id"),
            heartbeat_interval=data.get("heartbeat_interval", 5),
        )
        s.started_at = data.get("started_at", s.started_at)
        s.updated_at = data.get("updated_at", s.updated_at)
        s.status = data.get("status", "ACTIVE")
        s.cycles_since_milestone = data.get("cycles_since_milestone", 0)
        s.thread = data.get("thread", [])
        s.branch_registry = data.get("branch_registry", [])
        s.milestones = data.get("milestones", [])
        return s

    # ── Persistence ──────────────────────────────────────────────────────

    def save(self, session_dir: str) -> str:
        os.makedirs(session_dir, exist_ok=True)
        path = os.path.join(session_dir, f"session_{self.session_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
        return path

    @classmethod
    def load(cls, path: str) -> Optional["ResearchSession"]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return cls.from_dict(json.load(fh))
        except Exception:
            return None
