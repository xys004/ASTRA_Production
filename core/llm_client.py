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
    "perplexity": {
        "env":      "PERPLEXITY_API_KEY",
        "base_url": "https://api.perplexity.ai",
        "model":    "sonar-pro",        # busqueda web con citas (API, no suscripcion)
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
    partially-formatted Navigator response.
    """
    # Look for the value after "next_direction": possibly truncated JSON
    match = re.search(r'"next_direction"\s*:\s*"([^"]{20,})', response)
    if match:
        return match.group(1)[:400]
    # Look for sentences starting with investigative verbs
    for prefix in ("Investigate", "Examine", "Compute", "Determine", "Verify",
                   "Calculate", "Explore", "Formulate", "Consider", "Derive", "Now"):
        match = re.search(rf'{prefix}[^.!?]{{20,}}[.!?]', response)
        if match:
            return match.group(0)[:400]
    # Last resort: return a short excerpt of the macro question, not the full text
    return macro_question[:300] + ("…" if len(macro_question) > 300 else "")


class ASTRAIntelligence:
    """
    Unified client for underlying LLM interaction.
    Supports OpenAI, Anthropic, Google Gemini/Vertex AI, DeepSeek,
    xAI Grok, Qwen, Mistral, Codestral, and Groq.
    """
    def __init__(self, provider: str = "gemini", cli_models: str = None,
                 cli_timeout: int = None):
        self.provider = provider.lower()
        self.cli_models = cli_models    # escalera de modelos POR FASE para el CLI (opcional)
        self.cli_timeout = cli_timeout  # presupuesto por llamada especifico de la fase
        self.api_key = None
        self.client = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cli_kind = None   # set para proveedores de suscripcion claude_cli/codex_cli
        self.cli_last_model = None  # modelo CLI que respondio la ultima llamada (escalera)
        self.cli_warnings = []      # avisos de cuota/fallback, expuestos en el JSON del ciclo

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

        elif self.provider in ("claude_cli", "codex_cli", "gemini_cli", "agy_cli"):
            # Backend de SUSCRIPCION: usa los CLIs oficiales (Claude Code / Codex /
            # Gemini CLI / agy=Antigravity) en modo headless. NO usa API de pago ->
            # no requiere API key. (gemini_cli/agy = OAuth de suscripcion, cuota de la
            # cuenta Google; distintos del provider 'gemini', que factura contra
            # GEMINI_API_KEY. agy SUSTITUYE a gemini_cli, descontinuado para cuentas
            # individuales.)
            self.cli_kind = {"claude_cli": "claude", "codex_cli": "codex",
                             "gemini_cli": "gemini", "agy_cli": "agy"}[self.provider]
            self.api_key = "CLI_SUBSCRIPTION"   # marca "modo real" (evita SIMULATED)
            self.client = "CLI"

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
            if self.cli_kind:
                # Suscripcion via CLI (claude/codex/gemini/agy): combinamos system+user
                # en un solo prompt (los CLIs headless reciben un unico prompt) y
                # corremos en un hilo para no bloquear el loop async. Enrutamos por
                # self.cli_kind (no por lista de providers) para cubrir TODOS los
                # backends CLI; asi gemini_cli/agy_cli tambien pasan por call_cli.
                from core.cli_backend import call_cli
                combined = f"{system_prompt}\n\n{user_prompt}" if system_prompt else user_prompt
                if self.cli_kind == "codex":
                    # ASTRA's Codex turns are deliberative model calls, not autonomous
                    # workspace tasks.  Everything that may be inspected (objective,
                    # conjecture, validator and evidence) is already embedded above.
                    # Explicitly suppress tool exploration so xhigh reasoning is spent
                    # on the scientific exchange instead of scanning the repository.
                    combined = (
                        "ASTRA INTERNAL DELIBERATION MODE.\n"
                        "Respond directly from the context in this prompt. Do not "
                        "inspect the workspace, browse, run commands, call tools, "
                        "spawn agents, wait for files, or modify anything. Return "
                        "only the requested scientific or JSON response.\n\n"
                        + combined
                    )
                res = await asyncio.to_thread(call_cli, self.cli_kind, combined,
                                              models=self.cli_models,
                                              timeout=self.cli_timeout)
                if res.model_used:
                    self.cli_last_model = res.model_used
                if res.warning:
                    # Hubo fallback por cuota: dejar rastro en el log y en el ciclo
                    logger.warning(res.warning)
                    self.cli_warnings.append(res.warning)
                if not res.ok:
                    # Tope de cuota / fallo -> semantica API_ERROR (el loop lo salta/reintenta)
                    return f"API_ERROR: {res.error}"
                return res.text

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

        # Robust extraction: CLI models sometimes return prose/evidence or several
        # blocks. Pick the fenced block that actually COMPILES as Python (or carries an
        # ASTRA_ENGINE marker for Sage/Maxima/Cadabra) instead of the first block blindly.
        import ast, re as _re
        _blocks = _re.findall(r"```[A-Za-z0-9_+-]*\n(.*?)```", response, _re.DOTALL)
        _cands = [b.strip() for b in _blocks if b.strip()] or [response.strip()]
        def _score(c):
            if _re.match(r"#\s*ASTRA_ENGINE:\s*(sage|maxima|cadabra)", c):
                return (2, len(c))
            try:
                ast.parse(c)
                if _re.search(r"(^|\n)\s*(import |from |def |print\(|@)", c):
                    return (2, len(c))
                return (1, len(c))
            except SyntaxError:
                return (0, len(c))
        response = max(_cands, key=_score)

        return response

    async def review_validation_code(
        self,
        shared_goal: str,
        conjecture: str,
        code: str,
    ) -> dict:
        """Independent pre-oracle audit of the translator's validation code."""
        logger.info(f"[{self.provider.upper()}] Reviewing validation-code coverage...")

        from agents.reviewer import CODE_REVIEWER_PROMPT

        user_prompt = (
            f"SHARED FINAL OBJECTIVE:\n{shared_goal[:2000]}\n\n"
            f"CONSENSUS CONJECTURE:\n{conjecture[:5000]}\n\n"
            f"PROPOSED VALIDATION SCRIPT:\n```text\n{code[:14000]}\n```"
        )
        response = await self._call_api(CODE_REVIEWER_PROMPT, user_prompt)
        if response == "SIMULATED_RESPONSE":
            return {
                "status": "APPROVED",
                "reasoning": "Simulated code review.",
                "revision_instructions": "",
                "coverage": [],
            }
        if isinstance(response, str) and response.startswith("API_ERROR:"):
            return {
                "status": "API_ERROR",
                "reasoning": response,
                "revision_instructions": "",
                "coverage": [],
            }

        parsed = _extract_json_object(_fix_json_backslashes(response))
        if not isinstance(parsed, dict):
            return {
                "status": "REVISE",
                "reasoning": "Reviewer output was not valid JSON.",
                "revision_instructions": (
                    "Regenerate a compact, falsifiable validator whose decisive checks "
                    "and failure paths are explicit."
                ),
                "coverage": [],
            }

        status = str(parsed.get("status") or "REVISE").upper()
        if status not in {"APPROVED", "REVISE", "REJECT"}:
            status = "REVISE"
        coverage = parsed.get("coverage")
        if not isinstance(coverage, list):
            coverage = []
        return {
            "status": status,
            "reasoning": str(parsed.get("reasoning") or response)[:2000],
            "revision_instructions": str(parsed.get("revision_instructions") or "")[:3000],
            "coverage": [str(item)[:500] for item in coverage[:12]],
        }

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

        # Truncate macro_question for the navigator — it may be a full PDF (15k+ chars)
        mac_q_short = macro_question[:600] + ("…[truncated]" if len(macro_question) > 600 else "")

        user_prompt = (
            f"macro_question: {mac_q_short}\n\n"
            f"axiomatic_base:\n{axiomatic_base}\n\n"
            f"last_conjecture:\n{last_conjecture[:800]}\n\n"
            f"last_status: {last_status}\n"
            f"last_reasoning: {last_reasoning[:400]}\n\n"
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
                "macro_resolved": False,
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
            parsed.setdefault("macro_resolved", False)
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
            "macro_resolved": False,
        }

    async def analyze_results(
        self,
        conjecture: str,
        exec_result: dict,
        shared_goal: str = "",
    ) -> dict:
        """Phase 5: independent evidence and validation-code audit."""
        logger.info(f"[{self.provider.upper()}] Analyzing execution stdout/stderr...")

        from agents.analyst import REFUTATION_ANALYST_PROMPT
        system_prompt = REFUTATION_ANALYST_PROMPT

        # Deterministic evidence constrains the LLM verdict, but no longer bypasses the
        # analyst. Codex must read Claude's code even when it prints a clean PASS.
        _exit = exec_result.get("exit_code", 0)
        _stdout_up = (exec_result.get("stdout") or "").upper()
        _has_stderr = bool((exec_result.get("stderr") or "").strip())
        _explicit_fail = "VERDICT: FAIL" in _stdout_up
        _clean_pass = "VERDICT: PASS" in _stdout_up and _exit == 0 and not _has_stderr
        _crashed = _exit != 0 or _has_stderr

        if not self.api_key:
            if _crashed:
                return {"status": "CODE_ERROR", "reasoning": "Execution failed."}
            if _explicit_fail:
                return {"status": "REFUTED", "reasoning": "Validation script reported FAIL."}
            if _clean_pass:
                return {"status": "VALIDATED", "reasoning": "Validation script reported a clean PASS."}
            return {"status": "CODE_ERROR", "reasoning": "No explicit executable verdict."}

        review = exec_result.get("code_review") or {}
        user_prompt = (
            f"SHARED FINAL OBJECTIVE:\n{shared_goal or conjecture}\n\n"
            f"CONSENSUS CONJECTURE:\n{conjecture}\n\n"
            f"VALIDATION SCRIPT:\n```text\n"
            f"{(exec_result.get('validation_code') or '')[:16000]}\n```\n\n"
            f"PRE-ORACLE CODE REVIEW:\n{review}\n\n"
            f"EXECUTION EXIT CODE: {_exit}\n"
            f"EXECUTION STDOUT:\n{(exec_result.get('stdout') or '')[:10000]}\n\n"
            f"EXECUTION STDERR:\n{(exec_result.get('stderr') or '')[:6000]}"
        )
        response = await self._call_api(system_prompt, user_prompt)
        if isinstance(response, str) and response.startswith("API_ERROR:"):
            return {"status": "API_ERROR", "reasoning": response}

        parsed = _extract_json_object(_fix_json_backslashes(response))
        status = str((parsed or {}).get("status") or "").upper()
        if status not in {"CODE_ERROR", "REFUTED", "VALIDATED"}:
            parsed = None

        # A crashed run never establishes a theorem.
        if _crashed:
            if parsed and status in {"CODE_ERROR", "REFUTED"}:
                return parsed
            return {
                "status": "CODE_ERROR",
                "corrected_code": (parsed or {}).get("corrected_code"),
                "reasoning": (parsed or {}).get("reasoning") or response,
            }

        # An explicit failing check cannot be promoted to VALIDATED by prose.
        if _explicit_fail:
            if parsed and status in {"REFUTED", "CODE_ERROR"}:
                return parsed
            return {
                "status": "REFUTED",
                "reasoning": "The executable validator reported VERDICT: FAIL. " + response[:1000],
            }

        if parsed:
            return parsed

        # Parsing failed after a clean PASS. Preserve deterministic evidence only when
        # the independent pre-oracle review approved the validator; otherwise force a
        # conservative retry instead of silently accepting the script.
        if _clean_pass and str(review.get("status") or "").upper() == "APPROVED":
            return {
                "status": "VALIDATED",
                "reasoning": (
                    "Clean executable PASS with an approved independent code review; "
                    "the final analyst response was not parseable."
                ),
            }
        return {
            "status": "WEAK_PASS" if _clean_pass else "CODE_ERROR",
            "corrected_code": None,
            "reasoning": response,
        }
