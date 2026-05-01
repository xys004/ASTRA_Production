import asyncio
import logging
from core.llm_client import ASTRAIntelligence
from core.executor import execute_python_code
from core.preflight import phase_provider_map
from core.report_generator import generate_cycle_report
from core.state import state

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ASTRA_CORE")

PROVIDERS_BY_PHASE = phase_provider_map()
conjecture_llm = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["conjecture"])
translator_llm = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["translator"])
analyst_llm = ASTRAIntelligence(provider=PROVIDERS_BY_PHASE["analyst"])
MAX_CODE_RETRIES = 3

async def phase_2_generate_conjecture(context: str, intuition: str = None) -> str:
    state.status = "CONJECTURING"
    state.current_phase = "2/5 Conjecture"
    state.add_log(f"Phase 2: Formulating theoretical hypothesis via {conjecture_llm.provider}...")
    return await conjecture_llm.generate_conjecture(context, intuition)

async def phase_3_formal_translation(conjecture: str, is_correction: bool = False, previous_error: str = None) -> str:
    state.status = "TRANSLATING"
    state.current_phase = "3/5 Translation"
    state.add_log(f"Phase 3: Translating hypothesis via {translator_llm.provider}...")
    return await translator_llm.translate_to_code(conjecture, is_correction, previous_error)

async def phase_4_validation_oracle(python_code: str) -> dict:
    state.status = "VALIDATING"
    state.current_phase = "4/5 Validation Oracle"
    state.add_log("Phase 4: Running Oracle validation subprocess...")
    return await execute_python_code(python_code)

async def phase_5_result_analysis(conjecture: str, execution_result: dict) -> dict:
    state.status = "ANALYZING"
    state.current_phase = "5/5 Refutation Analysis"
    state.add_log(f"Phase 5: Analyzing execution results via {analyst_llm.provider}...")
    return await analyst_llm.analyze_results(conjecture, execution_result)


def _stop_requested() -> bool:
    if state.stop_requested:
        state.add_log("Stop requested. Ending cycle at the next safe checkpoint.")
        return True
    return False


def _write_cycle_report(final_status: str, user_intuition: str | None, analysis: dict) -> None:
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
        state.add_log(f"Cycle report generated: {report.get('html')}")
    except Exception as exc:
        state.add_log(f"Failed to generate cycle report: {exc}")

async def astra_orchestrator_loop():
    logger.info("Starting ASTRA Production Orchestrator background task...")
    state.add_log("ASTRA Background Orchestrator Started. Waiting for input...")
    state.add_log(
        "Provider layout: "
        f"conjecture={conjecture_llm.provider}, "
        f"translator={translator_llm.provider}, "
        f"analyst={analyst_llm.provider}"
    )
    
    while True:
        # Wait for the user to trigger a loop via the UI
        if not state.start_loop_requested:
            await asyncio.sleep(1)
            continue
            
        state.start_loop_requested = False
        state.stop_requested = False
        state.cycle_count += 1
        state.current_cycle = state.cycle_count
        state.current_phase = "1/5 Intake"
        state.add_log("--- STARTING NEW EPISTEMOLOGICAL LOOP ITERATION ---")
        state.add_log(f"Cycle #{state.current_cycle} started.")
        
        user_intuition = state.current_intuition
        final_status = "INCOMPLETE"
        final_analysis = {"status": "INCOMPLETE", "reasoning": "Cycle did not complete."}
        
        # Phase 2: Conjecture
        if _stop_requested():
            final_status = "STOPPED"
            final_analysis = {"status": "STOPPED", "reasoning": "Stopped before conjecture generation."}
            _write_cycle_report(final_status, user_intuition, final_analysis)
            state.save_state()
            state.stop_requested = False
            state.status = "IDLE"
            state.current_phase = "Idle"
            continue
        conjecture = await phase_2_generate_conjecture(state.axiomatic_base, user_intuition)
        state.current_conjecture = conjecture
        
        code_resolved = False
        python_code = None
        code_retries = 0
        
        while not code_resolved:
            if _stop_requested():
                final_status = "STOPPED"
                final_analysis = {"status": "STOPPED", "reasoning": "Stopped before next validation step."}
                code_resolved = True
                continue
            if python_code is None: 
                python_code = await phase_3_formal_translation(conjecture)
                state.last_python_code = python_code
            
            if _stop_requested():
                final_status = "STOPPED"
                final_analysis = {"status": "STOPPED", "reasoning": "Stopped after translation."}
                code_resolved = True
                continue
            exec_result = await phase_4_validation_oracle(python_code)
            state.last_execution_result = exec_result
            
            if _stop_requested():
                final_status = "STOPPED"
                final_analysis = {"status": "STOPPED", "reasoning": "Stopped after oracle validation."}
                code_resolved = True
                continue
            analysis = await phase_5_result_analysis(conjecture, exec_result)
            state.last_analysis = analysis
            final_analysis = analysis
            status = analysis.get("status")
            final_status = status or "UNKNOWN"
            
            if status == "CODE_ERROR":
                code_retries += 1
                if code_retries > MAX_CODE_RETRIES:
                    state.add_log("Maximum correction retries reached. Aborting iteration.")
                    final_status = "CODE_ERROR"
                    code_resolved = True
                    continue
                state.add_log("Engine error detected. Attempting to fix the script...")
                corrected = analysis.get("corrected_code")
                if corrected:
                    # Strip possible markdown code blocks if the analyst included them
                    if "```" in corrected:
                        parts = corrected.split("```")
                        if len(parts) >= 3:
                            corrected = parts[1]
                            if "\n" in corrected and corrected.split("\n")[0].strip() in ["python", "sage", "maxima", "cadabra"]:
                                corrected = corrected.split("\n", 1)[1]
                    python_code = corrected.strip()
                else:
                    state.add_log("Analyst provided no fix. Falling back to Translator...")
                    python_code = await phase_3_formal_translation(
                        conjecture, 
                        is_correction=True, 
                        previous_error=exec_result.get('stderr', 'Unknown execution error')
                    )
                state.last_python_code = python_code
                
            elif status == "REFUTED":
                state.add_log("Hypothesis refuted. Feeding back to the axiomatic base...")
                state.axiomatic_base += f"\n[REFUTED]: {conjecture}\nReasoning: {analysis.get('reasoning')}"
                final_status = "REFUTED"
                code_resolved = True 
                
            elif status == "VALIDATED":
                state.add_log("Hypothesis mathematically VALIDATED! Waiting for Human Approval.")
                state.status = "WAITING_APPROVAL"
                state.current_phase = "Human Approval"
                
                # Block until UI approves or rejects
                while not state.approve_theorem_requested and not state.reject_theorem_requested:
                    if state.stop_requested:
                        state.reject_theorem_requested = True
                        state.add_log("Stop requested during approval. Treating theorem as rejected.")
                        break
                    await asyncio.sleep(1)
                    
                if state.approve_theorem_requested:
                    state.add_log("Theorem APPROVED by user. Adding to Axiomatic Base.")
                    state.axiomatic_base += f"\n[ESTABLISHED THEOREM]: {conjecture}"
                    
                    # LaTeX Auto-Generation
                    import shutil
                    if shutil.which("pdflatex"):
                        state.add_log("LaTeX detected. Generating formal PDF report...")
                        try:
                            from core.pdf_generator import generate_pdf_report
                            pdf_path = generate_pdf_report(conjecture)
                            state.add_log(f"PDF Report successfully compiled at {pdf_path}")
                        except Exception as e:
                            state.add_log(f"Failed to generate PDF: {e}")
                    final_status = "VALIDATED_APPROVED"
                else:
                    state.add_log("Theorem REJECTED by user. Discarding.")
                    final_status = "VALIDATED_REJECTED"
                    
                state.approve_theorem_requested = False
                state.reject_theorem_requested = False
                code_resolved = True 
                
            else:
                state.add_log("Unknown analysis status. Aborting iteration.")
                final_status = "UNKNOWN"
                code_resolved = True
                
        _write_cycle_report(final_status, user_intuition, final_analysis)
        state.save_state()
        state.stop_requested = False
        state.status = "IDLE"
        state.current_phase = "Idle"
        state.add_log("Loop completed. Idling. State saved.")
        
def start_background_loop():
    asyncio.run(astra_orchestrator_loop())

if __name__ == "__main__":
    start_background_loop()
