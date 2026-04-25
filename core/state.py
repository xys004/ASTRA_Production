class GlobalState:
    def __init__(self):
        self.axiomatic_base = "Axioms: 4D Spacetime, signature (-,+,+,+)."
        self.current_intuition = None
        
        self.status = "IDLE"
        self.current_conjecture = ""
        self.last_python_code = ""
        self.last_execution_result = {}
        
        self.logs = []
        
        # Concurrency flags
        self.start_loop_requested = False
        self.approve_theorem_requested = False
        self.reject_theorem_requested = False
        
    def add_log(self, message):
        self.logs.append(message)
        # Keep only the last 50 logs to avoid memory overflow
        if len(self.logs) > 50:
            self.logs.pop(0)
            
    def get_state_dict(self):
        return {
            "status": self.status,
            "axiomatic_base": self.axiomatic_base,
            "current_conjecture": self.current_conjecture,
            "last_python_code": self.last_python_code,
            "logs": self.logs
        }

# Singleton instance
state = GlobalState()
