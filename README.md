# ASTRA Production (Autonomous Asynchronous Orchestrator)

ASTRA (Assisted Symbolic Testing, Reporting, and Analysis) is a multi-agent AI orchestrator designed to explore, translate, and rigorously validate theoretical physics hypotheses using mathematical logic backends.

## 1. System Architecture

The ecosystem relies on an asynchronous `while True` loop that orchestrates 3 distinct LLM Agents and an isolated execution oracle.

- **Phase 1 (Axiomatic Base):** A static context memory where validated theorems are appended.
- **Phase 2 (Conjecture Engine):** Acts as a "Physicist Co-Pilot". It takes an intuitive prompt from the user and formalizes it into a rigorous math hypothesis using LaTeX.
- **Phase 3 (Formal Translator):** Translates the LaTeX hypothesis into a `sympy`, `qutip`, or `z3-solver` Python script.
- **Phase 4 (Validation Oracle):** A subprocess executor (`core/executor.py`) that runs the Python script in isolation with a strict 60-second timeout to prevent infinite symbolic loops.
- **Phase 5 (Refutation Analyst):** Interprets the `stdout` and `stderr` to determine if the hypothesis is mathematically `VALIDATED`, `REFUTED`, or if there is a `CODE_ERROR`.

## 2. Supported LLM Providers

ASTRA supports the three major LLM providers natively. The wrapper (`core/llm_client.py`) will automatically use the respective SDK based on the `provider` argument passed to `ASTRAIntelligence`.

Before running ASTRA, you must set the appropriate environment variable in your terminal:
- **Google Gemini**: `$env:GEMINI_API_KEY="your_key"`
- **Anthropic Claude**: `$env:ANTHROPIC_API_KEY="your_key"`
- **OpenAI**: `$env:OPENAI_API_KEY="your_key"`

*Note: If no API key is detected, ASTRA will safely fallback to a "SIMULATED" mode, returning mock responses to allow for architectural testing.*

## 3. User Manual: How to Operate ASTRA

### Installation
Run the automated setup script to build the virtual environment and install the solvers and SDKs:
```powershell
.\install.ps1
```

### Execution
Activate the virtual environment and run the main orchestrator:
```powershell
.\venv\Scripts\Activate.ps1
python main.py
```

### The Intuition Workflow
ASTRA is designed to be accessible to non-physicists. When you run `main.py`, the terminal will pause and prompt you:
```text
[ASTRA INPUT] Enter your physical intuition/idea (or press Enter to let ASTRA freely explore):
```
Here, you can write abstract concepts (e.g., *"What if dark matter is a topological defect in the SU(3) symmetry?"*). The Conjecture Engine will parse this intuition, mathematically formalize it, and pass it down the pipeline. 

If a hypothesis is definitively proven by the Validation Oracle, the orchestrator will pause again and ask for Human Approval before writing the Theorem into the system's Axiomatic Memory.
