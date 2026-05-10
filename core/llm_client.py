import os
import asyncio
import logging
import json
import re

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass  # dotenv not yet installed; .env will be loaded by preflight after auto-install

logger = logging.getLogger("ASTRA_CORE.llm")

from typing import Optional

# All providers that use the OpenAI-compatible chat completions API
_OPENAI_COMPAT = {
    "openai": {
        "env":      "OPENAI_API_KEY",
        "base_url": None,                                               # default OpenAI
        "model":    "gpt-4o",
    },
    "deepseek": {
        "env":      "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model":    "deepseek-reasoner",                                # DeepSeek R1
    },
    "xai": {
        "env":      "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "model":    "grok-3",
    },
    "qwen": {
        "env":      "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model":    "qwen2.5-math-72b-instruct",
    },
    "mistral": {
        "env":      "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "model":    "mistral-large-latest",
    },
    "codestral": {
        "env":      "MISTRAL_API_KEY",                                  # same key as mistral
        "base_url": "https://codestral.mistral.ai/v1",
        "model":    "codestral-latest",
    },
    "groq": {
        "env":      "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model":    "llama-3.3-70b-versatile",
    },
}


def _extract_json_object(text: str) -> Optional[dict]:
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


def _fix_json_backslashes(text: str) -> str:
    """Escape lone backslashes (e.g. LaTeX \\mu) that are invalid inside JSON strings."""
    # Valid JSON escape characters after a backslash: " \ / b f n r t u
    _VALID = set('"\\\/bfnrtu')
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text) and text[i + 1] not in _VALID:
            out.append('\\\\')   # double the backslash
        else:
            out.append(ch)
        i += 1
    return ''.join(out)


def _extract_next_direction_from_prose(response: str, macro_question: str) -> str:
    """
    Best-effort extraction of a next research direction from a prose or
    partially-formatted Navigator response.  Returns the macro_question as
    last resort so the loop never halts with a vacuous direction.
    """
    # Look for the value after "next_direction": possibly truncated JSON
    match = re.search(r'"next_direction"\s*:\s*"([^"]{20,})', response)
    if match:
        return match.group(1)[:400]
    # Look for sentences starting with investigative verbs
    for prefix in ("Investigate", "Examine", "Compute", "Determine", "Verify",
                   "Calculate", "Explore", "Formulate", "Consider", "Derive"):
        match = re.search(rf'{prefix}[^.!?]{{20,}}[.!?]', response)
        if match:
            return match.group(0)[:400]
    return macro_question


class ASTRAIntelligence:
    """
    Unified client for underlying LLM interaction.
    Supports OpenAI, Anthropic, Google Gemini/Vertex AI, DeepSeek,
    xAI Grok, Qwen, Mistral, Codestral, and Groq.
    """
    def __init__(self, provider: str = "gemini"):
        self.provider = provider.lower()
        self.api_key = None
        self.client = None
        self.prompt_tokens = 0
        self.completion_tokens = 0

        if self.provider in _OPENAI_COMPAT:
            cfg = _OPENAI_COMPAT[self.provider]
            self.api_key = os.environ.get(cfg["env"])
            if self.api_key:
                try:
                    from openai import AsyncOpenAI
                    kwargs = {"api_key": self.api_key}
                    if cfg["base_url"]:
                        kwargs["base_url"] = cfg["base_url"]
                    self.client = AsyncOpenAI(**kwargs)
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

        elif self.provider == "vertexai":
            try:
                from google import genai
                gcp_project  = os.environ.get("VERTEX_PROJECT")
                gcp_location = os.environ.get("VERTEX_LOCATION", "us-central1")
                if not gcp_project:
                    logger.error("VERTEX_PROJECT env var is not set. Add it to your .env file.")
                else:
                    self.client = genai.Client(vertexai=True, project=gcp_project, location=gcp_location)
                    self.api_key = "ADC_MANAGED"
            except ImportError:
                logger.error("Gemini SDK not installed. Run: pip install google-genai")

        else:
            logger.error(f"Unsupported provider: {self.provider}")

        if not self.api_key:
            logger.warning(f"No API KEY found for {self.provider}. Operating in SIMULATED mode.")

    async def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        """Internal router to call the specific provider API."""
        if not self.api_key or not self.client:
            await asyncio.sleep(1)
            return "SIMULATED_RESPONSE"

        try:
            if self.provider in _OPENAI_COMPAT:
                model = _OPENAI_COMPAT[self.provider]["model"]
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ]
                )
                if hasattr(response, "usage") and response.usage:
                    self.prompt_tokens     += response.usage.prompt_tokens
                    self.completion_tokens += response.usage.completion_tokens
                return response.choices[0].message.content

            elif self.provider == "anthropic":
                response = await self.client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4000,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}]
                )
                if hasattr(response, "usage") and response.usage:
                    self.prompt_tokens     += getattr(response.usage, "input_tokens", 0)
                    self.completion_tokens += getattr(response.usage, "output_tokens", 0)
                return response.content[0].text

            elif self.provider in ["gemini", "vertexai"]:
                def _gemini_call():
                    return self.client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=user_prompt,
                        config={"system_instruction": system_prompt}
                    )
                response = await asyncio.to_thread(_gemini_call)
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    self.prompt_tokens     += getattr(response.usage_metadata, "prompt_token_count", 0)
                    self.completion_tokens += getattr(response.usage_metadata, "candidates_token_count", 0)
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

        if "```python" in response:
            response = response.split("```python")[1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[1].split("```")[0].strip()

        return response

    async def navigate_research(
        self,
        macro_question: str,
        axiomatic_base: str,
        last_conjecture: str,
        last_status: str,
        last_reasoning: str,
        thread_summary: str,
        cycles_since_milestone: int,
    ) -> dict:
        """Navigator phase: decides next research direction and whether to pause."""
        logger.info(f"[{self.provider.upper()}] Navigating research thread...")

        from agents.navigator import RESEARCH_NAVIGATOR_PROMPT

        user_prompt = (
            f"macro_question: {macro_question}\n\n"
            f"axiomatic_base:\n{axiomatic_base}\n\n"
            f"last_conjecture:\n{last_conjecture}\n\n"
            f"last_status: {last_status}\n"
            f"last_reasoning: {last_reasoning}\n\n"
            f"thread_summary:\n{thread_summary}\n\n"
            f"cycles_since_milestone: {cycles_since_milestone}"
        )

        response = await self._call_api(RESEARCH_NAVIGATOR_PROMPT, user_prompt)

        if response == "SIMULATED_RESPONSE":
            return {
                "next_direction": "Investigate the next natural consequence of the current result.",
                "rationale": "Simulated continuation.",
                "parallel_branches": [],
                "milestone": False,
                "milestone_reason": "",
                "progress_assessment": "Simulated.",
            }

        # Pre-process: escape lone backslashes that break JSON parsing
        # (LLMs sometimes include LaTeX \mu, \nu etc. in JSON string values)
        cleaned_response = _fix_json_backslashes(response)
        parsed = _extract_json_object(cleaned_response)
        if parsed:
            parsed.setdefault("next_direction", "")
            parsed.setdefault("rationale", "")
            parsed.setdefault("parallel_branches", [])
            parsed.setdefault("milestone", False)
            parsed.setdefault("milestone_reason", "")
            parsed.setdefault("progress_assessment", "")
            return parsed

        # Fallback: try to extract next_direction from raw text so the loop
        # continues with a meaningful direction rather than a generic placeholder
        logger.warning(f"[{self.provider.upper()}] Navigator JSON parse failed; extracting direction from prose.")
        extracted_direction = _extract_next_direction_from_prose(response, macro_question)
        return {
            "next_direction": extracted_direction,
            "rationale": response[:600],
            "parallel_branches": [],
            "milestone": True,
            "milestone_reason": "Navigator JSON could not be fully parsed — human review recommended.",
            "progress_assessment": "Navigator output partially parsed.",
        }

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
