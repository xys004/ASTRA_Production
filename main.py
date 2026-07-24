import asyncio
import logging
import os
import time
from typing import Optional

from core.llm_client import ASTRAIntelligence
from core.executor import execute_python_code
from core.preflight import phase_provider_map
from core.report_generator import generate_cycle_report
from core.state import state

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ASTRA_CORE")

PROVIDERS_BY_PHASE = phase_provider_map()
conjecture_llm = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["conjecture"])
translator_llm  = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["translator"])
reviewer_llm    = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["reviewer"])
analyst_llm     = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["analyst"])

# Navigator uses Antigravity in the production role map.
_nav_provider   = PROVIDERS_BY_PHASE["navigator"]
navigator_llm   = ASTRAIntelligence(provider=_nav_provider)

MAX_CODE_RETRIES = 3


def _reload_llm_clients() -> None:
    """Re-read provider env vars and recreate LLM clients. Called before each cycle."""
    global conjecture_llm, translator_llm, reviewer_llm, analyst_llm, navigator_llm, PROVIDERS_BY_PHASE
    from core.preflight import phase_provider_map, load_project_env
    load_project_env()
    PROVIDERS_BY_PHASE = phase_provider_map()
    conjecture_llm = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["conjecture"])
    translator_llm  = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["translator"])
    reviewer_llm    = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["reviewer"])
    analyst_llm     = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["analyst"])
    nav_prov        = PROVIDERS_BY_PHASE["navigator"]
    navigator_llm   = ASTRAIntelligence(provider=nav_prov)


# ═══════════════════════════════════════════════════════════════════
# Phase functions
# ═══════════════════════════════════════════════════════════════════

async def phase_2_generate_conjecture(
    context: str, intuition: str = None, shared_goal: str = ""
) -> str:
    state.status = "CONJECTURING"
    state.current_phase = "2/6 Deliberative Conjecture"
    raw = os.environ.get("ASTRA_CONJECTURE_PROVIDER", conjecture_llm.provider)
    providers = [p.strip().lower() for p in raw.strip().strip("'\"").split(",") if p.strip()]
    directed = (
        f"SHARED FINAL OBJECTIVE:\n{shared_goal or intuition}\n\n"
        f"CURRENT RESEARCH DIRECTION:\n{intuition or 'Explore freely.'}\n\n"
        "Develop balanced evidence for proof and refutation."
    )
    if len(providers) > 1:
        from astra_tool import _ensemble_conjecture

        synth = os.environ.get("ASTRA_SYNTH_PROVIDER", PROVIDERS_BY_PHASE["synth"])
        state.add_log(
            "Phase 2: Parallel conjectures, cross-critique and synthesis via "
            f"{', '.join(providers)} -> {synth}."
        )
        conjecture, _agents, _deliberation = await _ensemble_conjecture(
            providers, context, directed, None, synth
        )
        return conjecture
    state.add_log(f"Phase 2: Formulating hypothesis via {conjecture_llm.provider}...")
    return await conjecture_llm.generate_conjecture(context, directed)


async def phase_3_formal_translation(
    conjecture: str, is_correction: bool = False, previous_error: str = None
) -> str:
    state.status = "TRANSLATING"
    state.current_phase = "3/5 Translation"
    state.add_log(f"Phase 3: Translating hypothesis via {translator_llm.provider}...")
    return await translator_llm.translate_to_code(conjecture, is_correction, previous_error)


async def phase_4_validation_oracle(python_code: str) -> dict:
    state.status = "VALIDATING"
    state.current_phase = "4/5 Validation Oracle"
    state.add_log("Phase 4: Running Oracle validation subprocess...")
    return await execute_python_code(python_code)


async def phase_review_validation_code(
    shared_goal: str, conjecture: str, python_code: str
) -> dict:
    state.status = "REVIEWING"
    state.current_phase = "4/6 Independent Code Review"
    state.add_log(
        f"Independent review: auditing Claude's validator via {reviewer_llm.provider}..."
    )
    return await reviewer_llm.review_validation_code(
        shared_goal=shared_goal,
        conjecture=conjecture,
        code=python_code,
    )


async def phase_5_result_analysis(
    conjecture: str, execution_result: dict, shared_goal: str = ""
) -> dict:
    state.status = "ANALYZING"
    state.current_phase = "6/6 Refutation Analysis"
    state.add_log(f"Phase 5: Analyzing execution results via {analyst_llm.provider}...")
    return await analyst_llm.analyze_results(
        conjecture, execution_result, shared_goal=shared_goal
    )


async def phase_nav_navigate(session, last_conjecture: str, last_status: str, last_reasoning: str) -> dict:
    state.status = "NAVIGATING"
    state.current_phase = "Navigator"
    state.add_log(f"Navigator: Determining next research direction via {navigator_llm.provider}...")
    return await navigator_llm.navigate_research(
        macro_question=session.macro_question,
        axiomatic_base=state.axiomatic_base,
        last_conjecture=last_conjecture,
        last_status=last_status,
        last_reasoning=last_reasoning,
        thread_summary=session.thread_summary(),
        cycles_since_milestone=session.cycles_since_milestone,
    )


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _stop_requested() -> bool:
    if state.stop_requested:
        state.add_log("Stop requested. Ending cycle at the next safe checkpoint.")
        return True
    return False


def _write_cycle_report(final_status: str, user_intuition: Optional[str], analysis: dict) -> None:
    try:
        report = generate_cycle_report(
            cycle=state.current_cycle,
            status=final_status,
            intuition=user_intuition,
            conjecture=state.current_conjecture,
            code=state.last_python_code,
            execution_result=state.last_execution_result,
            analysis=analysis,
            axiomatic_base=state.axiomatic_base,
            providers=PROVIDERS_BY_PHASE,
        )
        state.last_report = report
        state.reports.insert(0, report)
        state.reports = state.reports[:20]
        state.add_log("Cycle report generated.")
    except Exception as exc:
        state.add_log(f"Failed to generate cycle report: {exc}")


def _idle() -> None:
    state.stop_requested = False
    state.status = "IDLE"
    state.current_phase = "Idle"


def _is_api_error(text: str) -> bool:
    return isinstance(text, str) and text.startswith("API_ERROR:")


# ═══════════════════════════════════════════════════════════════════
# Core execution engine (shared by single-cycle and research modes)
# ═══════════════════════════════════════════════════════════════════

async def _execute_one_cycle(intuition: str) -> dict:
    """
    Run phases 2–5 (including the theorem approval gate) for a single intuition.
    Increments cycle_count, updates state, writes report, saves state.
    Returns {"conjecture": str, "status": str, "analysis": dict}.
    Does NOT call _idle() — the caller manages lifecycle.
    """
    state.cycle_count += 1
    state.investigation_cycle_count += 1
    state.current_cycle = state.cycle_count
    state.current_phase = "1/5 Intake"
    state.add_log("--- STARTING NEW EPISTEMOLOGICAL LOOP ITERATION ---")
    state.add_log(f"Cycle #{state.current_cycle} started.")

    final_status   = "INCOMPLETE"
    final_analysis = {"status": "INCOMPLETE", "reasoning": "Cycle did not complete."}
    session = getattr(state, "research_session", None)
    shared_goal = (
        getattr(session, "macro_question", None)
        if session is not None
        else None
    ) or intuition

    # ── Phase 2 ─────────────────────────────────────────────────────────
    if _stop_requested():
        final_status   = "STOPPED"
        final_analysis = {"status": "STOPPED", "reasoning": "Stopped before conjecture generation."}
        _write_cycle_report(final_status, intuition, final_analysis)
        state.save_state()
        return {"conjecture": "", "status": final_status, "analysis": final_analysis}

    conjecture = await phase_2_generate_conjecture(
        state.axiomatic_base, intuition, shared_goal=shared_goal
    )
    state.current_conjecture = conjecture

    if _is_api_error(conjecture):
        state.add_log(f"[API_ERROR] Phase 2 API error — aborting cycle: {conjecture[:160]}")
        final_status   = "API_ERROR"
        final_analysis = {"status": "API_ERROR", "reasoning": conjecture}
        _write_cycle_report(final_status, intuition, final_analysis)
        state.save_state()
        return {"conjecture": conjecture, "status": final_status, "analysis": final_analysis}

    # ── Phases 3–5 with retry loop ───────────────────────────────────────
    python_code   = None
    code_review   = None
    code_retries  = 0
    code_resolved = False
    validation_brief = (
        f"SHARED FINAL OBJECTIVE:\n{shared_goal}\n\n"
        f"CONSENSUS CONJECTURE TO VALIDATE:\n{conjecture}"
    )

    while not code_resolved:
        if _stop_requested():
            final_status   = "STOPPED"
            final_analysis = {"status": "STOPPED", "reasoning": "Stopped during validation loop."}
            code_resolved  = True
            continue

        if python_code is None:
            python_code = await phase_3_formal_translation(validation_brief)
            state.last_python_code = python_code
            if _is_api_error(python_code):
                state.add_log(f"[API_ERROR] Phase 3 API error — aborting cycle: {python_code[:160]}")
                final_status   = "API_ERROR"
                final_analysis = {"status": "API_ERROR", "reasoning": python_code}
                code_resolved  = True
                continue

        if code_review is None:
            code_review = await phase_review_validation_code(
                shared_goal, conjecture, python_code
            )
            review_status = str(code_review.get("status") or "").upper()
            if review_status != "APPROVED":
                code_retries += 1
                if review_status == "API_ERROR" or code_retries > MAX_CODE_RETRIES:
                    final_status = "CODE_ERROR"
                    final_analysis = {
                        "status": "CODE_ERROR",
                        "reasoning": code_review.get("reasoning")
                        or "Independent code review failed.",
                    }
                    code_resolved = True
                    continue
                state.add_log(
                    f"Code review requested revision {code_retries}/{MAX_CODE_RETRIES}."
                )
                python_code = await phase_3_formal_translation(
                    validation_brief,
                    is_correction=True,
                    previous_error=(
                        "Independent Codex review returned "
                        f"{review_status}: "
                        f"{code_review.get('revision_instructions') or code_review.get('reasoning')}"
                    ),
                )
                state.last_python_code = python_code
                code_review = None
                continue

        if _stop_requested():
            final_status   = "STOPPED"
            final_analysis = {"status": "STOPPED", "reasoning": "Stopped after translation."}
            code_resolved  = True
            continue

        exec_result = await phase_4_validation_oracle(python_code)
        exec_result["validation_code"] = python_code
        exec_result["code_review"] = code_review
        state.last_execution_result = exec_result

        if _stop_requested():
            final_status   = "STOPPED"
            final_analysis = {"status": "STOPPED", "reasoning": "Stopped after oracle validation."}
            code_resolved  = True
            continue

        analysis = await phase_5_result_analysis(
            conjecture, exec_result, shared_goal=shared_goal
        )
        state.last_analysis = analysis
        final_analysis = analysis
        status         = analysis.get("status")
        final_status   = status or "UNKNOWN"

        if status in ("CODE_ERROR", "WEAK_PASS"):
            code_retries += 1
            if code_retries > MAX_CODE_RETRIES:
                state.add_log("Maximum correction retries reached. Aborting iteration.")
                code_resolved = True
                continue

            state.add_log(
                f"{status} detected. Correction attempt "
                f"{code_retries}/{MAX_CODE_RETRIES}..."
            )
            state.add_log("Codex diagnosed the issue; Claude will revise the validator.")
            python_code = await phase_3_formal_translation(
                validation_brief,
                is_correction=True,
                previous_error=(
                    (exec_result.get("stderr") or "No stderr.")
                    + "\nCodex diagnosis: "
                    + str(analysis.get("reasoning") or "")
                )[:3000],
            )
            code_review = None
            state.last_python_code = python_code
            if _is_api_error(python_code):
                state.add_log(f"[API_ERROR] Phase 3 (correction) API error — aborting: {python_code[:160]}")
                final_status   = "API_ERROR"
                final_analysis = {"status": "API_ERROR", "reasoning": python_code}
                code_resolved  = True
                continue

        elif status == "REFUTED":
            state.add_log("Hypothesis refuted. Feeding back to the axiomatic base...")
            state.axiomatic_base += f"\n[REFUTED]: {conjecture}\nReasoning: {analysis.get('reasoning')}"
            code_resolved = True

        elif status == "VALIDATED":
            state.add_log("Hypothesis mathematically VALIDATED! Waiting for Human Approval.")
            state.status       = "WAITING_APPROVAL"
            state.current_phase = "Human Approval"

            while not state.approve_theorem_requested and not state.reject_theorem_requested:
                if state.stop_requested:
                    state.reject_theorem_requested = True
                    state.add_log("Stop requested during approval. Treating theorem as rejected.")
                    break
                await asyncio.sleep(1)

            if state.approve_theorem_requested:
                state.add_log("Theorem APPROVED by user. Adding to Axiomatic Base.")
                state.axiomatic_base += f"\n[ESTABLISHED THEOREM]: {conjecture}"

                import shutil
                if shutil.which("pdflatex"):
                    state.add_log("LaTeX detected. Generating formal PDF report...")
                    try:
                        from core.pdf_generator import generate_pdf_report
                        pdf_path = generate_pdf_report(conjecture)
                        state.add_log(f"PDF Report compiled: {pdf_path}")
                    except Exception as exc:
                        state.add_log(f"Failed to generate PDF: {exc}")
                final_status = "VALIDATED_APPROVED"
            else:
                state.add_log("Theorem REJECTED by user. Discarding.")
                final_status = "VALIDATED_REJECTED"

            state.approve_theorem_requested = False
            state.reject_theorem_requested  = False
            code_resolved = True

        else:
            state.add_log(f"Unknown analysis status '{status}'. Aborting iteration.")
            code_resolved = True

    _write_cycle_report(final_status, intuition, final_analysis)
    state.save_state()
    return {"conjecture": conjecture, "status": final_status, "analysis": final_analysis}


# ═══════════════════════════════════════════════════════════════════
# Single-cycle mode (original behaviour, unchanged for the UI)
# ═══════════════════════════════════════════════════════════════════

async def _run_single_cycle() -> None:
    _reload_llm_clients()
    state.start_loop_requested = False
    state.stop_requested       = False
    state.add_log("--- SINGLE CYCLE MODE ---")
    intuition = state.current_intuition
    await _execute_one_cycle(intuition)
    _idle()
    state.add_log("Single cycle completed. Idling.")


# ═══════════════════════════════════════════════════════════════════
# Research-loop mode
# ═══════════════════════════════════════════════════════════════════

async def _run_research_loop() -> None:
    """
    Depth-first autonomous research loop driven by the Research Navigator.
    Runs until the session is stopped or completed.
    Human review pauses occur at milestones (navigator-flagged or heartbeat).
    """
    from core.research_session import ResearchSession

    _reload_llm_clients()
    state.start_research_requested = False
    state.stop_requested           = False

    session = state.research_session
    if session is None:
        state.add_log("[ERROR] Research loop started with no active session.")
        _idle()
        return

    session_dir = os.path.join(
        os.path.dirname(__file__), "workspace", "sessions"
    )

    state.add_log(
        f"=== RESEARCH LOOP STARTED === "
        f"Session: {session.session_id} | "
        f"Macro question: {session.macro_question[:120]}"
    )

    # First direction = macro question itself
    current_direction = session.macro_question
    _session_start = time.time()

    while session.status == "ACTIVE":
        if state.stop_requested:
            state.add_log("Stop requested. Ending research loop.")
            break

        if state.max_runtime_minutes > 0:
            elapsed_min = (time.time() - _session_start) / 60
            if elapsed_min >= state.max_runtime_minutes:
                state.add_log(
                    f"Maximum runtime of {state.max_runtime_minutes} min reached "
                    f"({elapsed_min:.1f} min elapsed). Ending session."
                )
                break

        # ── Execute one cycle ────────────────────────────────────────────
        result = await _execute_one_cycle(current_direction)

        if result["status"] in ("STOPPED", "INCOMPLETE"):
            break

        if result["status"] == "API_ERROR":
            state.add_log("[API_ERROR] Cycle aborted due to API error. Retrying same direction after pause.")
            await asyncio.sleep(5)
            continue

        # ── Navigator phase ──────────────────────────────────────────────
        if state.stop_requested:
            break

        analysis   = result["analysis"]
        nav_status = result["status"]
        # Normalise status for the navigator (strip _APPROVED / _REJECTED suffix)
        if nav_status.startswith("VALIDATED"):
            nav_status = "VALIDATED"
        elif nav_status.startswith("REFUTED"):
            nav_status = "REFUTED"

        nav = await phase_nav_navigate(
            session=session,
            last_conjecture=result["conjecture"],
            last_status=nav_status,
            last_reasoning=analysis.get("reasoning", ""),
        )

        state.navigator_proposal = nav
        session.add_branches(nav.get("parallel_branches", []))
        session.record_cycle(
            cycle_num=state.current_cycle,
            conjecture=result["conjecture"],
            status=result["status"],
            reasoning=analysis.get("reasoning", ""),
            nav_direction=nav.get("next_direction", ""),
        )
        session.cycles_since_milestone += 1

        state.add_log(
            f"Navigator: progress → {nav.get('progress_assessment', '')[:120]}"
        )
        if nav.get("parallel_branches"):
            state.add_log(
                f"Navigator: {len(nav['parallel_branches'])} branch(es) saved to registry."
            )

        # ── Macro resolved check ─────────────────────────────────────────
        if nav.get("macro_resolved", False):
            state.add_log("Navigator: Macro question declared resolved. Ending session.")
            session.status = "COMPLETED"
            break

        # ── Milestone check ──────────────────────────────────────────────
        is_milestone = nav.get("milestone", False)
        is_heartbeat = session.cycles_since_milestone >= session.heartbeat_interval

        if is_milestone or is_heartbeat:
            reason = nav.get("milestone_reason") or (
                f"Heartbeat: {session.heartbeat_interval} cycles without review pause."
            )
            session.record_milestone(state.current_cycle, reason)
            session.cycles_since_milestone = 0
            session.save(session_dir)
            state.add_log(f"MILESTONE REACHED: {reason}")
            state.add_log("Proposed next direction: " + nav.get("next_direction", "")[:200])
            state.add_log("Pending branches in registry: " + str(len(session.pending_branches())))

            if state.autonomous_mode:
                # Auto-continue without pausing for human input
                current_direction = nav.get("next_direction", session.macro_question)
                state.add_log(f"[AUTONOMOUS] Auto-continuing past milestone to: {current_direction[:160]}")

            else:
                # Human review pause
                session.status      = "PAUSED_MILESTONE"
                state.status        = "WAITING_DIRECTION"
                state.current_phase = "Research Milestone — Awaiting Direction"

                while True:
                    if state.stop_requested:
                        break
                    if (
                        state.continue_research_requested
                        or state.redirect_research_requested
                        or state.switch_branch_id
                    ):
                        break
                    await asyncio.sleep(1)

                if state.stop_requested:
                    break

                if state.switch_branch_id:
                    branch = session.activate_branch(state.switch_branch_id)
                    if branch:
                        current_direction = branch["direction"]
                        state.add_log(f"Switched to branch '{state.switch_branch_id}'.")
                    else:
                        state.add_log(
                            f"Branch '{state.switch_branch_id}' not found or already active. "
                            "Continuing with navigator suggestion."
                        )
                        current_direction = nav.get("next_direction", session.macro_question)
                    state.switch_branch_id = ""

                elif state.redirect_research_requested:
                    current_direction = state.redirect_direction or session.macro_question
                    state.add_log(f"Human redirected research: {current_direction[:120]}")
                    state.redirect_research_requested = False
                    state.redirect_direction          = ""

                else:
                    current_direction = nav.get("next_direction", session.macro_question)
                    state.add_log("Continuing with navigator's suggested direction.")
                    state.continue_research_requested = False

                session.status = "ACTIVE"

        else:
            # No milestone — advance autonomously
            current_direction = nav.get("next_direction", session.macro_question)
            state.add_log(f"Auto-advancing to: {current_direction[:160]}")
            session.save(session_dir)

    # ── Session end ──────────────────────────────────────────────────────
    session.status = "COMPLETED"
    session.save(session_dir)
    state.research_session = None
    state.navigator_proposal = {}
    _idle()
    state.add_log("=== RESEARCH LOOP ENDED ===")


# ═══════════════════════════════════════════════════════════════════
# Orchestrator — dispatches to single-cycle or research-loop mode
# ═══════════════════════════════════════════════════════════════════

async def astra_orchestrator_loop():
    logger.info("Starting ASTRA Production Orchestrator background task...")
    state.add_log("ASTRA Background Orchestrator Started. Waiting for input...")
    state.add_log(
        f"Provider layout: conjecture={conjecture_llm.provider}, "
        f"translator={translator_llm.provider}, analyst={analyst_llm.provider}, "
        f"navigator={navigator_llm.provider}"
    )

    while True:
        if state.start_research_requested:
            try:
                await _run_research_loop()
            except Exception as exc:
                logger.error(f"Unhandled exception in research loop: {exc}", exc_info=True)
                state.add_log(f"[ERROR] Research loop aborted: {exc}")
                state.research_session = None
                _idle()

        elif state.start_loop_requested:
            try:
                await _run_single_cycle()
            except Exception as exc:
                logger.error(f"Unhandled exception in single cycle: {exc}", exc_info=True)
                state.add_log(f"[ERROR] Unexpected error — cycle aborted: {exc}")
                _idle()

        else:
            await asyncio.sleep(1)


def start_background_loop():
    asyncio.run(astra_orchestrator_loop())


if __name__ == "__main__":
    start_background_loop()
