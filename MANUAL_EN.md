# ASTRA — User Manual

**Autonomous Scientific Theory Research Assistant**
Version 1.0 — May 2026

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Requirements and Launch](#2-system-requirements-and-launch)
3. [Interface Layout](#3-interface-layout)
4. [Single Cycle Mode](#4-single-cycle-mode)
5. [Research Loop Mode](#5-research-loop-mode)
6. [Understanding the Output Panels](#6-understanding-the-output-panels)
7. [Status Reference](#7-status-reference)
8. [Provider Configuration](#8-provider-configuration)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Overview

ASTRA is a multi-agent AI system designed to generate, formalize, and validate scientific hypotheses through an automated five-phase pipeline:

| Phase | Agent | What it does |
|-------|-------|--------------|
| 1 — Intake | — | Receives the intuition or document |
| 2 — Conjecture | Conjecture Engine | Formalizes the intuition into a rigorous hypothesis with axioms and definitions |
| 3 — Translation | Formal Translator | Writes a Python validation script using SymPy, SciPy, or other CAS |
| 4 — Validation Oracle | Sandbox executor | Runs the script in an isolated environment and captures output |
| 5 — Analysis | Refutation Analyst | Interprets the result: VALIDATED, REFUTED, or CODE_ERROR |

ASTRA operates in two modes:

- **Single Cycle** — you supply one intuition; ASTRA runs it through the pipeline once and waits for your approval before adding the result to the Axiomatic Base.
- **Research Loop** — you supply a macro research question; ASTRA autonomously cycles through hypotheses, guided by a fifth agent (the Research Navigator), until it reaches a milestone and pauses for your review.

---

## 2. System Requirements and Launch

### Prerequisites

- Python 3.10+
- At least one LLM API key (Vertex AI ADC, Gemini, Anthropic, OpenAI, DeepSeek, xAI, Qwen, Mistral, or Groq)
- All Python dependencies installed (`pip install -r requirements.txt` inside the `venv`)

### Environment variables

Configure your keys in a `.env` file in the `ASTRA_Production/` root:

```
GEMINI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
VERTEX_PROJECT=your_gcp_project_id
VERTEX_LOCATION=us-central1
```

Add only the keys for the providers you intend to use.

### Launching

Run the ASTRA wizard from the terminal:

```powershell
cd ASTRA_Production
.\venv\Scripts\python.exe wizard.py
```

The wizard runs a preflight check (dependencies, keys, external CAS) and then starts the Flask server on port **5050**. Open your browser to:

```
http://localhost:5050
```

---

## 3. Interface Layout

The interface is divided into three sections:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ASTRUM / Production                        [IDLE]  Cycle 0       [Help]   │
├──────────────────────┬──────────────────────────────────────────────────────┤
│                      │                                                      │
│    SIDEBAR           │    CANVAS                                            │
│                      │                                                      │
│  Mode toggle         │  [Research Thread]  [Branch Registry]  ← research   │
│  Input panel         │                                                      │
│  System Log          │  [Hypothesis]                                        │
│                      │  [Validation Script]                                 │
│                      │  [Cycle Reports]    [Axiomatic Base]                 │
└──────────────────────┴──────────────────────────────────────────────────────┘
```

**Topbar** — shows the current status pill and cycle counter. Turns red when the server goes offline.

**Sidebar** — contains the mode toggle, the input panel (Single Cycle) or session panel (Research Loop), and the real-time System Log with a progress bar.

**Canvas** — the main information area. The Research Thread and Branch Registry panels are only visible in Research Loop mode.

---

## 4. Single Cycle Mode

### Step-by-step

1. Ensure the **Single Cycle** tab is selected in the mode toggle.
2. Type a falsifiable scientific claim in the **Intuition Input** text area.

   Good intuitions are:
   - Specific and bounded (not open-ended research questions)
   - Falsifiable in principle by computation
   - Expressed in terms that can be translated into SymPy/SciPy code

   **Example:** "Test whether the Schwarzschild metric has vanishing Ricci scalar outside r = 2M."

3. (Optional) Upload a PDF or TXT document using the drop zone — ASTRA will extract the text and use it as the intuition context.

4. Select your preferred AI providers for Conjecture, Translator, and Analyst using the dropdowns.

5. Click **Launch Cycle**. The progress bar and System Log will track the pipeline in real time.

6. When the pipeline completes successfully, an **Approval Modal** will appear:
   - **Approve & Add** — adds the validated theorem to the Axiomatic Base, where it can inform future cycles.
   - **Reject** — discards the result.

7. If the cycle is **REFUTED**, no approval is needed. The result appears in Cycle Reports.

8. Click **Launch Cycle** again to run another cycle with a new or refined intuition.

### What each phase looks like in the log

| Status shown | What is happening |
|---|---|
| CONJECTURING | The Conjecture Engine is formalizing your intuition |
| TRANSLATING | The Formal Translator is writing the validation script |
| VALIDATING | The script is executing in the sandbox |
| ANALYZING | The Refutation Analyst is reading the output |
| WAITING_APPROVAL | Pipeline succeeded — awaiting your decision |
| IDLE | No cycle is running |

---

## 5. Research Loop Mode

### Concept

In Research Loop mode, ASTRA acts as an autonomous research assistant. Instead of one intuition, you supply a **macro research question** — a broad scientific question that cannot be answered in a single cycle. ASTRA then:

1. Generates a hypothesis relevant to the question
2. Validates it
3. Passes the result to the **Research Navigator**, which decides the next direction
4. Runs the next cycle automatically
5. Pauses at **milestones** for your review

The Navigator also identifies **parallel branches** — independent sub-questions worth exploring later — and saves them in the Branch Registry.

### Step-by-step

1. Click **Research Loop** in the mode toggle at the top of the sidebar.

2. Enter your **macro research question** in the text area.

   A good macro question is:
   - Open-ended (cannot be answered in one cycle)
   - Scientifically precise
   - Amenable to computational validation

   **Example:** "Determine whether the Alcubierre warp metric requires strictly negative energy density everywhere within the bubble, or whether geometric modifications can localise or reduce the exotic matter requirements."

3. Select AI providers for all four roles: Conjecture, Translator, Analyst, and **Navigator**.

4. Set the **Heartbeat** interval — the maximum number of cycles between forced checkpoints. Default is 5. The Navigator may pause earlier if it judges a result to be a significant milestone.

5. Click **Launch Session**. The sidebar will show the active session info bar with live counters.

6. ASTRA will run cycles autonomously. Watch the **Research Thread** panel for the history of what has happened, and the **Validation Script** and **Hypothesis** panels for what is happening right now.

7. When a **milestone** is reached, ASTRA pauses and the **Navigator Proposal modal** appears automatically.

### The Navigator Proposal modal

This modal appears at every milestone and shows:

| Field | Meaning |
|---|---|
| Checkpoint Reason | Why the Navigator decided to pause here |
| Progress Assessment | Honest one-sentence summary of how far the research has advanced |
| Proposed Next Direction | The Navigator's recommended direction for the next cycle |
| Navigator Rationale | The reasoning behind that recommendation |
| Pending Branches (if any) | Saved parallel directions you can activate instead |

You have three options:

- **Continue with Proposed Direction** — accept the Navigator's recommendation and resume autonomously.
- **Redirect** — type your own direction in the text field and click Redirect. ASTRA will use your direction for the next cycle instead.
- **Activate a Branch** — click any branch button to switch to a saved parallel direction. ASTRA will explore that branch as the new main thread.

### The Branch Registry panel

The Branch Registry lists all parallel directions proposed by the Navigator during the session. Each entry shows:

- The branch ID (short snake_case identifier)
- The research direction
- The motivation (why the Navigator saved it)
- Status: **PENDING** (not yet explored), **ACTIVE** (currently being explored), or **COMPLETED**

Click **Activate** on any PENDING branch to redirect the session to that branch at the next milestone.

### Stopping a session

Click **Stop** at any time. The current cycle will complete and ASTRA will return to IDLE. Session data is saved automatically to `workspace/sessions/session_{id}.json`.

---

## 6. Understanding the Output Panels

### Hypothesis panel

Displays the full conjecture formulated by the Conjecture Engine in the current cycle. Mathematical notation is rendered using MathJax (LaTeX inline and display math). Use **Copy** to copy the raw text.

### Validation Script panel

Displays the Python code generated by the Formal Translator. Syntax-highlighted with Prism. Use **Copy** to copy the script. The script is what actually runs in the Validation Oracle.

### Research Thread panel *(Research Loop only)*

A chronological list of all completed cycles in the current session. Each entry shows:

- **C1, C2 …** — cycle number
- Status badge: green VALIDATED, amber REFUTED, red CODE_ERROR
- Timestamp
- Conjecture excerpt (first ~180 characters)
- The Navigator's chosen direction for the next cycle (in blue)

### Branch Registry panel *(Research Loop only)*

Lists all parallel branches saved by the Navigator. See Section 5 for details.

### Cycle Reports panel

Shows a list of all completed cycles with links to the generated reports (HTML, Markdown, PDF where available). Click any link to open the full report in a new tab.

### Axiomatic Base panel

Shows all theorems that have been validated and approved during the session. Content is MathJax-rendered. The Axiomatic Base is provided to the Conjecture Engine in every subsequent cycle, ensuring the research builds cumulatively.

### System Log panel

Shows real-time log lines from the ASTRA backend. Useful for monitoring progress or diagnosing errors. Includes the phase name chip and progress bar. Scrolls automatically to the latest entry.

---

## 7. Status Reference

| Status | Description | Action required |
|---|---|---|
| IDLE | No cycle running | None |
| CONJECTURING | Conjecture Engine is working | Wait |
| TRANSLATING | Formal Translator is generating code | Wait |
| VALIDATING | Validation Oracle is running the script | Wait |
| ANALYZING | Refutation Analyst is reading results | Wait |
| NAVIGATING | Research Navigator is computing next direction | Wait |
| WAITING_APPROVAL | Hypothesis validated; awaiting human decision | Approve or Reject in modal |
| WAITING_DIRECTION | Research milestone reached; awaiting human decision | Use Navigator Proposal modal |
| OFFLINE | Flask server unreachable | Restart the wizard |

---

## 8. Provider Configuration

ASTRA supports the following LLM providers:

| Provider key | Model used | API key variable |
|---|---|---|
| `vertexai` | Gemini 2.5 Flash (via GCP) | `VERTEX_PROJECT` + ADC |
| `gemini` | Gemini 2.5 Flash | `GEMINI_API_KEY` |
| `anthropic` | Claude Sonnet 4.6 | `ANTHROPIC_API_KEY` |
| `openai` | GPT-4o | `OPENAI_API_KEY` |
| `deepseek` | DeepSeek R1 | `DEEPSEEK_API_KEY` |
| `xai` | Grok 3 | `XAI_API_KEY` |
| `qwen` | Qwen2.5-Math-72B | `DASHSCOPE_API_KEY` |
| `mistral` | Mistral Large | `MISTRAL_API_KEY` |
| `codestral` | Codestral | `MISTRAL_API_KEY` |
| `groq` | Llama 3.3 70B | `GROQ_API_KEY` |

**Recommended configuration:**

| Role | Recommended provider | Reason |
|---|---|---|
| Conjecture | Vertex AI / Gemini | Strong at formal scientific reasoning and LaTeX |
| Translator | Anthropic Claude | Highest code quality and correctness |
| Analyst | OpenAI GPT-4o | Reliable JSON output and result interpretation |
| Navigator | Vertex AI / Gemini | Strong at strategic reasoning and JSON adherence |

If no API key is found for a selected provider, ASTRA operates in **Simulated mode** — cycles complete with placeholder data, no real LLM calls are made.

---

## 9. Troubleshooting

**Cycle stuck at IDLE after clicking Launch**
- Confirm the Flask server is running (check the terminal).
- Verify at least one API key is set in `.env`.
- Reload the page and try again.

**CODE_ERROR repeating on every retry**
- The Translator is producing invalid code. Narrow your intuition to a more concrete and specific claim. Avoid open-ended or ambiguous phrasing.
- Try switching the Translator provider (Claude and Codestral tend to produce the most reliable Python).

**REFUTED on a claim you believe to be true**
- Read the full report (Cycle Reports → HTML). The Analyst's reasoning will explain what the validation found.
- The claim may be true but too abstract for the current validator to verify. Try reformulating it more concretely.

**Research Loop not pausing for milestones**
- Lower the heartbeat interval (e.g., set it to 3 cycles).
- Check the System Log — if the Navigator is failing to parse, it may be skipping milestone detection.

**Navigator Proposal modal not appearing**
- Confirm the server returned a `WAITING_DIRECTION` status (visible in the topbar pill).
- Reload the page — the modal should reappear within the next polling cycle (1 second).

**Server shows OFFLINE**
- The Flask process has stopped. Relaunch the wizard from the terminal.
- If the port 5050 is in use, kill the existing process: `Get-Process python | Stop-Process`.

**Vertex AI / ADC authentication error**
- Run `gcloud auth application-default login` in the terminal.
- Confirm `VERTEX_PROJECT` is set correctly in `.env`.

**PDF upload not working**
- PyMuPDF must be installed: `pip install PyMuPDF`.
- The wizard's auto-install step should handle this on first launch.

**External CAS not found (SageMath, Maxima)**
- These are optional. Run `install_windows_wsl.ps1` to install via WSL.
- Python-only validation (SymPy, SciPy, NumPy) works without them for most domains.

---

*ASTRA is developed by Astrum Drive Technologies.*
*For technical issues, consult the System Log or contact the development team.*
