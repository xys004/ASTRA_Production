import asyncio
import logging
from core.llm_client import ASTRAIntelligence
from core.executor import execute_python_code

# Basic logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ASTRA_CORE")

# Initialize the Intelligence Layer (Defaulting to gemini, but can be switched)
llm = ASTRAIntelligence(provider="gemini")

async def phase_1_load_axioms() -> str:
    """Phase 1: Load the static context and starting axiomatic base."""
    # TODO: Implement loading from core.state
    return "Axioms: 4D Spacetime, signature (-,+,+,+)."

async def phase_2_generate_conjecture(context: str, intuition: str = None) -> str:
    """Phase 2: Calls the LLM to propose a rigorous physical hypothesis."""
    return await llm.generate_conjecture(context, intuition)

async def phase_3_formal_translation(conjecture: str) -> str:
    """Phase 3: Translates the conjecture into an executable Python script."""
    return await llm.translate_to_code(conjecture)

async def phase_4_validation_oracle(python_code: str) -> dict:
    """Phase 4: Executes the code in an isolated asynchronous subprocess."""
    logger.info("Phase 4: Sending code to the validation oracle...")
    return await execute_python_code(python_code)

async def phase_5_result_analysis(conjecture: str, execution_result: dict) -> dict:
    """Phase 5: Interprets the result and returns VALIDATED, REFUTED, or CODE_ERROR."""
    return await llm.analyze_results(conjecture, execution_result)

async def astra_orchestrator_loop():
    """Main asynchronous execution loop of ASTRA."""
    logger.info("Starting ASTRA Production Orchestrator...")
    
    # Phase 1: Initialize state
    axiomatic_base = await phase_1_load_axioms()
    
    while True:
        logger.info("\n--- STARTING NEW EPISTEMOLOGICAL LOOP ITERATION ---")
        
        # Phase 1b: Optional Human Intuition
        print("\n" + "="*50)
        user_intuition = input("[ASTRA INPUT] Enter your physical intuition/idea (or press Enter to let ASTRA freely explore): ")
        
        # Phase 2: Conjecture
        conjecture = await phase_2_generate_conjecture(axiomatic_base, user_intuition)
        
        code_resolved = False
        python_code = None
        
        while not code_resolved:
            # Phase 3: Translation
            if python_code is None: 
                python_code = await phase_3_formal_translation(conjecture)
            
            # Phase 4: Oracle
            exec_result = await phase_4_validation_oracle(python_code)
            
            # Phase 5: Analysis
            analysis = await phase_5_result_analysis(conjecture, exec_result)
            status = analysis.get("status")
            
            if status == "CODE_ERROR":
                logger.warning("Engine error detected. Re-translating the script...")
                python_code = analysis.get("corrected_code")
                
            elif status == "REFUTED":
                logger.info("Hypothesis refuted. Feeding back to the axiomatic base...")
                axiomatic_base += f"\n[REFUTED]: {conjecture}\nReasoning: {analysis.get('reasoning')}"
                code_resolved = True 
                
            elif status == "VALIDATED":
                logger.info("Hypothesis mathematically VALIDATED!")
                # Phase 6: Human Interruption
                print("\n" + "="*50)
                print(f"VALIDATED THEOREM:\n{conjecture}")
                print("="*50)
                user_input = input("\n[ASTRA INTERRUPT] Approve physical relevance and add to axioms? (y/n/exit): ")
                
                if user_input.lower() == 'y':
                    axiomatic_base += f"\n[ESTABLISHED THEOREM]: {conjecture}"
                elif user_input.lower() == 'exit':
                    logger.info("Shutting down ASTRA Orchestrator...")
                    return
                
                code_resolved = True 
                
            else:
                logger.error("Unknown analysis status. Aborting iteration.")
                code_resolved = True

if __name__ == "__main__":
    try:
        asyncio.run(astra_orchestrator_loop())
    except KeyboardInterrupt:
        print("\nOrchestrator manually stopped by the user.")
