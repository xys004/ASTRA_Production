import os
import json
import threading
from datetime import datetime


class GlobalState:
    def __init__(self):
        self.state_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "workspace", "state.json"
        )
        self.axiomatic_base = ""
        self.cycle_count = 0
        self.investigation_cycle_count = 0
        self.reports = []

        self.load_state()

        self.current_intuition = None
        self.status = "IDLE"
        self.current_phase = "Idle"
        self.current_cycle = 0
        self.current_conjecture = ""
        self.last_python_code = ""
        self.last_execution_result = {}
        self.last_analysis = {}
        self.last_report = {}
        self.logs = []
        self._log_lock = threading.Lock()

        self.autonomous_mode = False
        self.max_runtime_minutes = 0   # 0 = unlimited

        # ── Single-cycle mode flags ──────────────────────────────────────
        self.start_loop_requested      = False
        self.stop_requested            = False
        self.approve_theorem_requested = False
        self.reject_theorem_requested  = False

        # ── Research-loop mode flags & state ─────────────────────────────
        self.start_research_requested    = False   # trigger research loop
        self.continue_research_requested = False   # milestone: keep navigator's direction
        self.redirect_research_requested = False   # milestone: use human's direction
        self.redirect_direction          = ""      # human-provided direction on redirect
        self.switch_branch_id            = ""      # branch id to activate on switch

        # Current session object (ResearchSession | None) — not persisted in state.json
        self.research_session = None
        # Latest navigator output, exposed to the UI while waiting at a milestone
        self.navigator_proposal: dict = {}

    def add_log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        with self._log_lock:
            self.logs.append(f"[{ts}] {message}")
            if len(self.logs) > 100:
                self.logs.pop(0)

    def save_state(self) -> None:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        data = {
            "axiomatic_base":          self.axiomatic_base,
            "cycle_count":             self.cycle_count,
            "investigation_cycle_count": self.investigation_cycle_count,
            "reports":                 self.reports,
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def load_state(self) -> None:
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.axiomatic_base            = data.get("axiomatic_base",            self.axiomatic_base)
            self.cycle_count               = data.get("cycle_count",               self.cycle_count)
            self.investigation_cycle_count = data.get("investigation_cycle_count", self.investigation_cycle_count)
            self.reports                   = data.get("reports",                   self.reports)
        except Exception as exc:
            print(f"[WARN] Failed to load saved state: {exc}")

    def get_state_dict(self) -> dict:
        session_dict = (
            self.research_session.to_dict() if self.research_session is not None else None
        )
        return {
            "status":                    self.status,
            "current_phase":             self.current_phase,
            "cycle_count":               self.cycle_count,
            "investigation_cycle_count": self.investigation_cycle_count,
            "current_cycle":             self.current_cycle,
            "axiomatic_base":        self.axiomatic_base,
            "current_conjecture":    self.current_conjecture,
            "last_python_code":      self.last_python_code,
            "last_execution_result": self.last_execution_result,
            "last_analysis":         self.last_analysis,
            "last_report":           self.last_report,
            "reports":               self.reports,
            "logs":                  self.logs,
            # Research-loop extras
            "research_session":      session_dict,
            "navigator_proposal":    self.navigator_proposal,
        }


state = GlobalState()
