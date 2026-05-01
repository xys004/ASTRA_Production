import os
import json
import threading

class GlobalState:
    def __init__(self):
        self.state_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "state.json")
        self.axiomatic_base = "Axioms: 4D Spacetime, signature (-,+,+,+)."
        self.cycle_count = 0
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

        # Concurrency flags
        self.start_loop_requested = False
        self.stop_requested = False
        self.approve_theorem_requested = False
        self.reject_theorem_requested = False

    def add_log(self, message):
        with self._log_lock:
            self.logs.append(message)
            if len(self.logs) > 50:
                self.logs.pop(0)

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        data = {
            "axiomatic_base": self.axiomatic_base,
            "cycle_count": self.cycle_count,
            "reports": self.reports
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.axiomatic_base = data.get("axiomatic_base", self.axiomatic_base)
                    self.cycle_count = data.get("cycle_count", self.cycle_count)
                    self.reports = data.get("reports", self.reports)
            except Exception as e:
                print(f"Failed to load state: {e}")
            
    def get_state_dict(self):
        return {
            "status": self.status,
            "current_phase": self.current_phase,
            "cycle_count": self.cycle_count,
            "current_cycle": self.current_cycle,
            "axiomatic_base": self.axiomatic_base,
            "current_conjecture": self.current_conjecture,
            "last_python_code": self.last_python_code,
            "last_execution_result": self.last_execution_result,
            "last_analysis": self.last_analysis,
            "last_report": self.last_report,
            "reports": self.reports,
            "logs": self.logs
        }

# Singleton instance
state = GlobalState()
