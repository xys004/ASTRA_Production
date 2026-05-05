from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv, set_key
except ModuleNotFoundError:
    load_dotenv = None
    set_key = None


PROVIDERS = {
    "gemini": {
        "env": "GEMINI_API_KEY",
        "package": "google.genai",
        "label": "Google Gemini",
    },
    "vertexai": {
        "env": None,           # Uses Application Default Credentials — no API key required
        "package": "google.genai",
        "label": "Google Vertex AI",
    },
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "package": "anthropic",
        "label": "Anthropic Claude",
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "package": "openai",
        "label": "OpenAI",
    },
    "deepseek": {
        "env": "DEEPSEEK_API_KEY",
        "package": "openai",
        "label": "DeepSeek",
    },
    "xai": {
        "env": "XAI_API_KEY",
        "package": "openai",
        "label": "xAI Grok",
    },
    "qwen": {
        "env": "DASHSCOPE_API_KEY",
        "package": "openai",
        "label": "Qwen (Alibaba)",
    },
    "mistral": {
        "env": "MISTRAL_API_KEY",
        "package": "openai",
        "label": "Mistral AI",
    },
    "codestral": {
        "env": "MISTRAL_API_KEY",
        "package": "openai",
        "label": "Codestral (Mistral)",
    },
    "groq": {
        "env": "GROQ_API_KEY",
        "package": "openai",
        "label": "Groq",
    },
}

PHASES = {
    "conjecture": {
        "env": "ASTRA_CONJECTURE_PROVIDER",
        "label": "Conjecture Engine",
        "recommendation": "gemini",
    },
    "translator": {
        "env": "ASTRA_TRANSLATOR_PROVIDER",
        "label": "Formal Translator",
        "recommendation": "anthropic",
    },
    "analyst": {
        "env": "ASTRA_ANALYST_PROVIDER",
        "label": "Refutation Analyst",
        "recommendation": "openai",
    },
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True

    @property
    def status(self) -> str:
        if self.ok:
            return "OK"
        return "WARN" if not self.required else "FAIL"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def env_path() -> Path:
    return project_root() / ".env"


def load_project_env() -> None:
    path = env_path()
    if load_dotenv is not None:
        load_dotenv(path)
        return
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _set_env_key(key: str, value: str) -> None:
    path = env_path()
    path.touch(exist_ok=True)
    if set_key is not None:
        set_key(str(path), key, value)
    else:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        prefix = f"{key}="
        updated = False
        for idx, line in enumerate(lines):
            if line.startswith(prefix):
                lines[idx] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


def _masked(value: str | None) -> str:
    if not value:
        return "missing"
    if len(value) <= 10:
        return "set"
    return f"{value[:6]}...{value[-4:]}"


def configured_providers() -> list[str]:
    load_project_env()
    providers = []
    for provider, meta in PROVIDERS.items():
        if meta["env"] is None:
            # ADC-based provider (Vertex AI) — available if SDK is installed
            if _module_available(meta["package"]):
                providers.append(provider)
        elif os.environ.get(meta["env"]):
            providers.append(provider)
    return providers


def choose_default_provider() -> str:
    preferred = os.environ.get("ASTRA_PROVIDER", "").strip().lower()
    if preferred in PROVIDERS and os.environ.get(PROVIDERS[preferred]["env"]):
        return preferred
    configured = configured_providers()
    return configured[0] if configured else "gemini"


def save_provider(provider: str) -> None:
    _set_env_key("ASTRA_PROVIDER", provider)


def phase_provider(phase: str) -> str:
    load_project_env()
    meta = PHASES[phase]
    explicit = os.environ.get(meta["env"], "").strip().lower()
    if explicit in PROVIDERS:
        return explicit
    fallback = os.environ.get("ASTRA_PROVIDER", "").strip().lower()
    if fallback in PROVIDERS:
        return fallback
    return choose_default_provider()


def phase_provider_map() -> dict[str, str]:
    return {phase: phase_provider(phase) for phase in PHASES}


def save_phase_provider(phase: str, provider: str) -> None:
    _set_env_key(PHASES[phase]["env"], provider)


def _provider_from_choice(configured: list[str], raw: str, current: str) -> str:
    if not raw:
        return current
    try:
        selected = configured[int(raw) - 1]
    except (ValueError, IndexError):
        selected = raw.lower()
    if selected in configured:
        return selected
    print(f"Provider '{raw}' is not configured. Keeping {current}.")
    return current


def _recommended_provider_for_phase(phase: str, configured: list[str]) -> str:
    preferred_order = {
        "conjecture": ["gemini", "anthropic", "openai"],
        "translator": ["anthropic", "openai", "gemini"],
        "analyst": ["openai", "anthropic", "gemini"],
    }[phase]
    for provider in preferred_order:
        if provider in configured:
            return provider
    return configured[0] if configured else "gemini"


def prompt_for_api_keys() -> None:
    path = env_path()
    path.touch(exist_ok=True)
    load_project_env()

    if configured_providers():
        return

    print("\n[FIRST TIME SETUP]")
    print("No API key is configured. Add at least one provider to run real API mode.")
    print("Note: Google Vertex AI uses Application Default Credentials (no key needed).")
    for provider, meta in PROVIDERS.items():
        if meta["env"] is None:
            continue  # ADC-based — no key to prompt for
        value = input(f"{meta['label']} key ({meta['env']}) or Enter to skip: ").strip()
        if value:
            _set_env_key(meta["env"], value)


def prompt_for_provider() -> str:
    load_project_env()
    configured = configured_providers()
    if not configured:
        print("\nNo API keys were added. ASTRA can still start in simulated mode.")
        provider = "gemini"
        save_provider(provider)
        return provider

    current = choose_default_provider()
    print("\nAvailable API providers:")
    for idx, provider in enumerate(configured, start=1):
        meta = PROVIDERS[provider]
        marker = " [current]" if provider == current else ""
        print(f"  {idx}. {meta['label']} ({meta['env']}={_masked(os.environ.get(meta['env']))}){marker}")

    raw = input(f"Select provider [default: {current}]: ").strip()
    if raw:
        try:
            selected = configured[int(raw) - 1]
        except (ValueError, IndexError):
            selected = raw.lower()
        if selected in configured:
            current = selected
        else:
            print(f"Provider '{raw}' is not configured. Keeping {current}.")

    save_provider(current)
    return current


def prompt_for_phase_providers() -> dict[str, str]:
    load_project_env()
    configured = configured_providers()
    if not configured:
        print("\nNo API keys were added. ASTRA can still start in simulated mode.")
        for phase in PHASES:
            save_phase_provider(phase, "gemini")
        save_provider("gemini")
        return phase_provider_map()

    print("\nConfigured API providers:")
    for idx, provider in enumerate(configured, start=1):
        meta = PROVIDERS[provider]
        print(f"  {idx}. {meta['label']} ({meta['env']}={_masked(os.environ.get(meta['env']))})")

    print("\nProvider layout:")
    print("  1. Recommended per phase")
    print("     - Conjecture: Gemini if available, then Claude, then OpenAI")
    print("     - Translator: Claude if available, then OpenAI, then Gemini")
    print("     - Analyst: OpenAI if available, then Claude, then Gemini")
    print("  2. Use one provider for all phases")
    print("  3. Manual selection per phase")

    mode = input("Choose layout [default: 1]: ").strip() or "1"

    if mode == "2":
        current = choose_default_provider()
        raw = input(f"Provider for all phases [default: {current}]: ").strip()
        selected = _provider_from_choice(configured, raw, current)
        save_provider(selected)
        for phase in PHASES:
            save_phase_provider(phase, selected)
        return phase_provider_map()

    if mode == "3":
        for phase, meta in PHASES.items():
            current = phase_provider(phase)
            recommended = _recommended_provider_for_phase(phase, configured)
            raw = input(f"{meta['label']} provider [default: {current}, recommended: {recommended}]: ").strip()
            selected = _provider_from_choice(configured, raw, current)
            save_phase_provider(phase, selected)
        save_provider(phase_provider("conjecture"))
        return phase_provider_map()

    for phase in PHASES:
        save_phase_provider(phase, _recommended_provider_for_phase(phase, configured))
    save_provider(phase_provider("conjecture"))
    return phase_provider_map()


async def _oracle_smoke_test() -> Check:
    try:
        from core.executor import execute_python_code

        result = await execute_python_code("print('ASTRA_ORACLE_OK')", timeout=10)
        ok = result.get("exit_code") == 0 and "ASTRA_ORACLE_OK" in result.get("stdout", "")
        detail = "local subprocess validated" if ok else result.get("stderr", "unexpected output")
        return Check("Validation oracle", ok, detail)
    except Exception as exc:
        return Check("Validation oracle", False, str(exc))


def run_preflight(provider: str | None = None, verify_api: bool = True, phase_providers: dict[str, str] | None = None) -> list[Check]:
    load_project_env()
    checks: list[Check] = []
    checks.append(Check("Python", sys.version_info >= (3, 9), sys.version.split()[0]))
    checks.append(Check("Project .env", env_path().exists(), str(env_path())))

    selected_providers = set((phase_providers or phase_provider_map()).values())
    if provider:
        selected_providers.add(provider)

    for selected in sorted(selected_providers):
        meta = PROVIDERS.get(selected)
        if meta is None:
            checks.append(Check("API provider", False, f"unsupported provider: {selected}"))
            continue
        if meta["env"] is None:
            # ADC-based provider — no key check, just confirm SDK is present
            checks.append(Check(f"{meta['label']} credentials", True, "Application Default Credentials (ADC)", required=False))
        else:
            api_key = os.environ.get(meta["env"])
            checks.append(Check(f"{meta['label']} API key", bool(api_key), _masked(api_key)))
        checks.append(Check(f"{meta['label']} SDK", _module_available(meta["package"]), meta["package"]))

    for phase, selected in (phase_providers or phase_provider_map()).items():
        checks.append(Check(f"{PHASES[phase]['label']} provider", selected in PROVIDERS, selected))

    for module in (
        "flask",
        "fitz",
        "sympy",
        "z3",
        "qutip",
        "numpy",
        "scipy",
        "mpmath",
        "einsteinpy",
        "fluids",
        "pint",
        "numba",
        "matplotlib",
        "networkx",
        "dotenv",
    ):
        checks.append(Check(f"Python module {module}", _module_available(module), module))

    checks.append(Check("pdflatex", shutil.which("pdflatex") is not None, "optional PDF reports", required=False))

    try:
        from core.engine_router import available_cas

        for engine, location in available_cas().items():
            checks.append(Check(f"CAS engine {engine}", location is not None, location or "optional external CAS", required=False))
    except Exception as exc:
        checks.append(Check("CAS engine detection", False, str(exc), required=False))

    oracle_check = asyncio.run(_oracle_smoke_test())
    checks.append(oracle_check)

    if verify_api:
        for selected in sorted(selected_providers):
            meta = PROVIDERS.get(selected)
            if not meta or not _module_available(meta["package"]):
                continue
            has_credentials = meta["env"] is None or bool(os.environ.get(meta["env"]))
            if has_credentials:
                checks.append(asyncio.run(verify_provider_api(selected)))

    return checks


async def verify_provider_api(provider: str) -> Check:
    from core.llm_client import ASTRAIntelligence

    client = ASTRAIntelligence(provider=provider)
    response = await client._call_api(
        "You are a health check. Reply with exactly ASTRA_API_OK.",
        "Reply with exactly ASTRA_API_OK.",
    )
    ok = "ASTRA_API_OK" in response
    detail = "live API call succeeded" if ok else response[:180].replace("\n", " ")
    return Check(f"{PROVIDERS[provider]['label']} live API", ok, detail)


def print_checks(checks: list[Check]) -> bool:
    print("\n[ASTRA PREFLIGHT]")
    all_required_ok = True
    for check in checks:
        print(f"[{check.status:4}] {check.name}: {check.detail}")
        if check.required and not check.ok:
            all_required_ok = False
    return all_required_ok
