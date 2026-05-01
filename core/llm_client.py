import os
import asyncio
import logging
import json
import re
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

logger = logging.getLogger("ASTRA_CORE.llm")


def _extract_json_object(text: str) -> dict | None:
    """Parse a JSON object even if the model wrapped it in prose or fences."""
    if not text:
        return None
    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

    candidates = [cleaned]
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            continue
    return None

class ASTRAIntelligence:
    """
    Unified client for underlying LLM interaction.
    Encapsulates asynchronous calls for all orchestration phases.
    Supports OpenAI, Anthropic, and Google Gemini via official SDKs.
    """
    def __init__(self, provider: str = "gemini"):
        self.provider = provider.lower()
        self.api_key = None
        self.client = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        
        # Boilerplate Initialization based on provider
        if self.provider == "openai":
            self.api_key = os.environ.get("OPENAI_API_KEY")
            if self.api_key:
                try:
                    from openai import AsyncOpenAI
                    self.client = AsyncOpenAI(api_key=self.api_key)
                except ImportError:
                    logger.error("OpenAI SDK not installed. Run: pip install openai")
        elif self.provider == "anthropic":
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
            if self.api_key:
                try:
                    from anthropic import AsyncAnthropic
                    self.client = AsyncAnthropic(api_key=self.api_key)
                except ImportError:
                    logger.error("Anthropic SDK not installed. Run: pip install anthropic")
        elif self.provider == "gemini":
            self.api_key = os.environ.get("GEMINI_API_KEY")
            if self.api_key:
                try:
                    from google import genai
                    self.client = genai.Client(api_key=self.api_key)
                except ImportError:
                    logger.error("Gemini SDK not installed. Run: pip install google-genai")
        else:
            logger.error(f"Unsupported provider: {self.provider}")
            
        if not self.api_key:
            logger.warning(f"No API KEY found for {self.provider}. Operating in SIMULATED mode.")

    async def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        """Internal router to call the specific provider API."""
        if not self.api_key or not self.client:
            await asyncio.sleep(1) # Simulate latency
            return "SIMULATED_RESPONSE"
            
        try:
            if self.provider == "openai":
                response = await self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                )
                if hasattr(response, 'usage') and response.usage:
                    self.prompt_tokens += response.usage.prompt_tokens
                    self.completion_tokens += response.usage.completion_tokens
                return response.choices[0].message.content
                
            elif self.provider == "anthropic":
                response = await self.client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=4000,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}]
                )
                if hasattr(response, 'usage') and response.usage:
                    self.prompt_tokens += getattr(response.usage, 'input_tokens', 0)
                    self.completion_tokens += getattr(response.usage, 'output_tokens', 0)
                return response.content[0].text
                
            elif self.provider == "gemini":
                # Google GenAI async bridging
                def _gemini_call():
                    return self.client.models.generate_content(
                        model='gemini-2.5-pro',
                        contents=user_prompt,
                        config={'system_instruction': system_prompt}
                    )
                response = await asyncio.to_thread(_gemini_call)
                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                    self.prompt_tokens += getattr(response.usage_metadata, 'prompt_token_count', 0)
                    self.completion_tokens += getattr(response.usage_metadata, 'candidates_token_count', 0)
                return response.text
                
        except Exception as e:
            logger.error(f"API Error with {self.provider}: {e}")
            return f"API_ERROR: {str(e)}"

    async def generate_conjecture(self, axiomatic_base: str, intuition: str = None) -> str:
        """Phase 2: Conjecture Engine (Physicist Co-Pilot)"""
        logger.info(f"[{self.provider.upper()}] Formulating theoretical hypothesis...")
        
        from agents.conjecture import CONJECTURE_ENGINE_PROMPT
        system_prompt = CONJECTURE_ENGINE_PROMPT
        user_prompt = f"Axiomatic Base:\n{axiomatic_base}\n\nIntuition:\n{intuition or 'Explore freely.'}"
        
        response = await self._call_api(system_prompt, user_prompt)
        
        if response == "SIMULATED_RESPONSE":
            return "Simulated Conjecture: The Ricci scalar R vanishes for the proposed metric."
        return response
        
    async def translate_to_code(self, conjecture: str, is_correction: bool = False, previous_error: str = None) -> str:
        """Phase 3: Formal Translator"""
        logger.info(f"[{self.provider.upper()}] Translating to SymPy/Z3/QuTiP/SageMath...")
        
        from agents.translator import FORMAL_TRANSLATOR_PROMPT
        system_prompt = FORMAL_TRANSLATOR_PROMPT
        user_prompt = f"Conjecture:\n{conjecture}"
        if is_correction:
            user_prompt += f"\n\nPrevious code failed with error:\n{previous_error}\nPlease correct it."
            
        response = await self._call_api(system_prompt, user_prompt)
        
        if response == "SIMULATED_RESPONSE":
            return "import sympy as sp\nprint('VERDICT: PASS\\nEvidence: 0')"
            
        # Clean markdown code blocks
        if "```python" in response:
            response = response.split("```python")[1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[1].split("```")[0].strip()
            
        return response
        
    async def analyze_results(self, conjecture: str, exec_result: dict) -> dict:
        """Phase 5: Refutation Analyst"""
        logger.info(f"[{self.provider.upper()}] Analyzing execution stdout/stderr...")
        
        from agents.analyst import REFUTATION_ANALYST_PROMPT
        system_prompt = REFUTATION_ANALYST_PROMPT
        
        if exec_result.get("exit_code", 0) != 0 or exec_result.get("stderr"):
            if not self.api_key:
                return {"status": "CODE_ERROR", "corrected_code": "print('Fixed Code')"}
                
            user_prompt = f"Conjecture:\n{conjecture}\n\nExecution Error:\n{exec_result['stderr']}"
            response = await self._call_api(system_prompt, user_prompt)
            parsed = _extract_json_object(response)
            if parsed and parsed.get("status") in {"CODE_ERROR", "REFUTED", "VALIDATED"}:
                return parsed
            return {"status": "CODE_ERROR", "corrected_code": None, "reasoning": response}
            
        else:
            if not self.api_key:
                return {"status": "VALIDATED", "reasoning": "Null residual."}
                
            user_prompt = f"Conjecture:\n{conjecture}\n\nExecution Output:\n{exec_result['stdout']}"
            response = await self._call_api(system_prompt, user_prompt)
            parsed = _extract_json_object(response)
            if parsed and parsed.get("status") in {"CODE_ERROR", "REFUTED", "VALIDATED"}:
                return parsed

            stdout = exec_result.get("stdout", "").upper()
            if "VERDICT: FAIL" in stdout:
                return {"status": "REFUTED", "reasoning": "Validation script reported VERDICT: FAIL."}
            if "VERDICT: PASS" in stdout:
                return {"status": "VALIDATED", "reasoning": "Validation script reported VERDICT: PASS."}
            return {"status": "CODE_ERROR", "corrected_code": None, "reasoning": response}
