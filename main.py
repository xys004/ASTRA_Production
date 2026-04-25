import asyncio
import logging
from core.llm_client import ASTRAIntelligence
from core.executor import execute_python_code
from core.state import state

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ASTRA_CORE")

llm = ASTRAIntelligence(provider="gemini")

async def phase_2_generate_conjecture(context: str, intuition: str = None) -> str:
    state.status = "CONJECTURING"
    state.add_log("Phase 2: Formulating theoretical hypothesis...")
    return await llm.generate_conjecture(context, intuition)

async def phase_3_formal_translation(conjecture: str) -> str:
    state.status = "TRANSLATING"
    state.add_log("Phase 3: Translating LaTeX into Python script...")
    return await llm.translate_to_code(conjecture)

async def phase_4_validation_oracle(python_code: str) -> dict:
    state.status = "VALIDATING"
    state.add_log("Phase 4: Running Oracle validation subprocess...")
    return await execute_python_code(python_code)

async def phase_5_result_analysis(conjecture: str, execution_result: dict) -> dict:
    state.status = "ANALYZING"
    state.add_log("Phase 5: Analyzing execution results...")
    return await llm.analyze_results(conjecture, execution_result)

async def astra_orchestrator_loop():
    logger.info("Starting ASTRA Production Orchestrator background task...")
    state.add_log("ASTRA Background Orchestrator Started. Waiting for input...")
    
    while True:
        # Wait for the user to trigger a loop via the UI
        if not state.start_loop_requested:
            await asyncio.sleep(1)
            continue
            
        state.start_loop_requested = False
        state.add_log("--- STARTING NEW EPISTEMOLOGICAL LOOP ITERATION ---")
        
        user_intuition = state.current_intuition
        
        # Phase 2: Conjecture
        conjecture = await phase_2_generate_conjecture(state.axiomatic_base, user_intuition)
        state.current_conjecture = conjecture
        
        code_resolved = False
        python_code = None
        
        while not code_resolved:
            if python_code is None: 
                python_code = await phase_3_formal_translation(conjecture)
                state.last_python_code = python_code
            
            exec_result = await phase_4_validation_oracle(python_code)
            state.last_execution_result = exec_result
            
            analysis = await phase_5_result_analysis(conjecture, exec_result)
            status = analysis.get("status")
            
            if status == "CODE_ERROR":
                state.add_log("Engine error detected. Re-translating the script...")
                python_code = analysis.get("corrected_code")
                state.last_python_code = python_code
                
            elif status == "REFUTED":
                state.add_log("Hypothesis refuted. Feeding back to the axiomatic base...")
                state.axiomatic_base += f"\n[REFUTED]: {conjecture}\nReasoning: {analysis.get('reasoning')}"
                code_resolved = True 
                
            elif status == "VALIDATED":
                state.add_log("Hypothesis mathematically VALIDATED! Waiting for Human Approval.")
                state.status = "WAITING_APPROVAL"
                
                # Block until UI approves or rejects
                while not state.approve_theorem_requested and not state.reject_theorem_requested:
                    await asyncio.sleep(1)
                    
                if state.approve_theorem_requested:
                    state.add_log("Theorem APPROVED by user. Adding to Axiomatic Base.")
                    state.axiomatic_base += f"\n[ESTABLISHED THEOREM]: {conjecture}"
                else:
                    state.add_log("Theorem REJECTED by user. Discarding.")
                    
                state.approve_theorem_requested = False
                state.reject_theorem_requested = False
                code_resolved = True 
                
            else:
                state.add_log("Unknown analysis status. Aborting iteration.")
                code_resolved = True
                
        state.status = "IDLE"
        state.add_log("Loop completed. Idling.")
        
def start_background_loop():
    asyncio.run(astra_orchestrator_loop())

if __name__ == "__main__":
    start_background_loop()
