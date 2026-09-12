"""Machine-local subscription account profiles for ASTRA's model CLIs.

Only profile labels, paths, and optional expected account emails are stored in
the registry. Provider credentials remain in the private configuration
directories owned by Codex, Claude Code, and Antigravity (``agy``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Optional


PROVIDERS = ("codex", "claude", "agy")
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class AccountProfileError(RuntimeError):
    """Raised when the local profile registry is invalid or incomplete."""


def account_profile_root() -> Path:
    configured = (os.environ.get("ASTRA_ACCOUNT_PROFILE_ROOT") or "").strip().strip("'\"")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "astra" / "account_profiles"
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "astra" / "account_profiles"
    return Path.home() / ".config" / "astra" / "account_profiles"


def registry_path() -> Path:
    return account_profile_root() / "profiles.json"


def _empty_registry() -> dict:
    return {"version": 1, "active": {}, "profiles": {}}


def load_registry() -> dict:
    path = registry_path()
    if not path.exists():
        return _empty_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AccountProfileError(f"No se pudo leer {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise AccountProfileError(f"Registro de perfiles invalido: {path}")
    data.setdefault("version", 1)
    data.setdefault("active", {})
    if not isinstance(data["active"], dict):
        raise AccountProfileError(f"Mapa 'active' invalido: {path}")
    return data


def save_registry(data: dict) -> Path:
    root = account_profile_root()
    root.mkdir(parents=True, exist_ok=True)
    path = registry_path()
    fd, temporary = tempfile.mkstemp(prefix="profiles-", suffix=".json", dir=str(root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


def validate_profile_name(name: str) -> str:
    clean = (name or "").strip()
    if not _PROFILE_RE.fullmatch(clean):
        raise AccountProfileError(
            "El perfil debe comenzar con una letra o numero y usar solo "
            "letras, numeros, punto, guion o guion bajo (maximo 64 caracteres)."
        )
    return clean


def _provider_record(home: Path, expected_email: Optional[str] = None) -> dict:
    record = {"home": str(home.resolve())}
    if expected_email:
        record["expected_email"] = expected_email.strip()
    return record


def bootstrap_current_profile(
    name: str = "primary",
    expected_emails: Optional[dict] = None,
    replace: bool = False,
) -> dict:
    """Register existing provider homes without copying any credentials."""
    name = validate_profile_name(name)
    expected_emails = expected_emails or {}
    data = load_registry()
    profile = data["profiles"].setdefault(name, {"providers": {}})
    providers = profile.setdefault("providers", {})
    current_home = Path.home()
    defaults = {
        "codex": Path(os.environ.get("CODEX_HOME") or current_home / ".codex"),
        "claude": Path(
            os.environ.get("CLAUDE_CONFIG_DIR") or current_home / ".claude"
        ),
        # agy resolves ~/.gemini itself, so its isolated root is the user home.
        "agy": current_home,
    }
    for provider, home in defaults.items():
        if replace or provider not in providers:
            providers[provider] = _provider_record(
                home, expected_emails.get(provider)
            )
        if expected_emails.get(provider) and not providers[provider].get("expected_email"):
            providers[provider]["expected_email"] = expected_emails[provider].strip()
        data["active"].setdefault(provider, name)
    save_registry(data)
    return data


def add_isolated_profile(
    name: str,
    expected_emails: Optional[dict] = None,
) -> dict:
    name = validate_profile_name(name)
    expected_emails = expected_emails or {}
    data = load_registry()
    if name in data["profiles"]:
        raise AccountProfileError(f"El perfil '{name}' ya existe.")
    base = account_profile_root() / "profiles" / name
    homes = {
        "codex": base / "codex",
        "claude": base / "claude",
        "agy": base / "agy-home",
    }
    for home in homes.values():
        home.mkdir(parents=True, exist_ok=True)
    # A profile-specific file store keeps Codex credentials attached to this
    # CODEX_HOME instead of a shared OS-keyring entry. The resulting auth.json
    # is sensitive and remains outside Git in the machine-local profile root.
    codex_config = homes["codex"] / "config.toml"
    if not codex_config.exists():
        codex_config.write_text(
            'cli_auth_credentials_store = "file"\n', encoding="utf-8"
        )
    data["profiles"][name] = {
        "providers": {
            provider: _provider_record(home, expected_emails.get(provider))
            for provider, home in homes.items()
        }
    }
    save_registry(data)
    return data


def provider_record(data: dict, name: str, provider: str) -> dict:
    if provider not in PROVIDERS:
        raise AccountProfileError(f"Proveedor desconocido: {provider}")
    try:
        record = data["profiles"][name]["providers"][provider]
    except (KeyError, TypeError) as exc:
        raise AccountProfileError(
            f"El perfil '{name}' no tiene configuracion para {provider}."
        ) from exc
    if not isinstance(record, dict) or not record.get("home"):
        raise AccountProfileError(
            f"La configuracion de {provider} en '{name}' no contiene 'home'."
        )
    return record


def environment_for_record(provider: str, record: dict) -> dict:
    """Build child-process isolation variables for one provider record."""
    home = str(Path(record["home"]).expanduser())
    if provider == "codex":
        return {"CODEX_HOME": home}
    if provider == "claude":
        return {"CLAUDE_CONFIG_DIR": home}
    if provider == "agy" and os.name == "nt":
        return {"USERPROFILE": home}
    if provider == "agy":
        return {"HOME": home}
    raise AccountProfileError(f"Proveedor desconocido: {provider}")


def profile_environment(provider: str) -> tuple[str, dict]:
    """Return the active profile label and child-process environment.

    An absent registry preserves ASTRA's historical provider defaults. Once a
    registry exists, an incomplete active selection fails closed so a run can
    never silently use the wrong subscription account.
    """
    if provider not in PROVIDERS:
        return "", {}
    if not registry_path().exists():
        return "default", {}
    data = load_registry()
    name = data["active"].get(provider)
    if not name:
        raise AccountProfileError(f"No hay perfil activo para {provider}.")
    record = provider_record(data, name, provider)
    return name, environment_for_record(provider, record)


def auth_marker(provider: str, record: dict) -> Path:
    home = Path(record["home"]).expanduser()
    if provider == "codex":
        return home / "auth.json"
    if provider == "claude":
        return home / ".credentials.json"
    return home / ".gemini" / "oauth_creds.json"


def profile_is_authenticated(provider: str, record: dict) -> bool:
    return auth_marker(provider, record).is_file()


def set_active_profile(name: str, providers: list[str]) -> dict:
    name = validate_profile_name(name)
    data = load_registry()
    for provider in providers:
        record = provider_record(data, name, provider)
        if not profile_is_authenticated(provider, record):
            raise AccountProfileError(
                f"'{name}' aun no esta autenticado en {provider}; ejecuta primero "
                f"scripts/astra_accounts.py login {name} {provider}."
            )
    for provider in providers:
        data["active"][provider] = name
    save_registry(data)
    return data


def set_provider_home(
    name: str,
    provider: str,
    home: Path,
    expected_email: Optional[str] = None,
) -> dict:
    """Point one profile/provider at an existing authenticated CLI home."""
    name = validate_profile_name(name)
    data = load_registry()
    provider_record(data, name, provider)
    replacement = _provider_record(Path(home).expanduser(), expected_email)
    if not profile_is_authenticated(provider, replacement):
        raise AccountProfileError(
            f"No se encontro autenticacion de {provider} en "
            f"{auth_marker(provider, replacement)}."
        )
    data["profiles"][name]["providers"][provider] = replacement
    save_registry(data)
    return data


def confirm_provider_identity(
    name: str,
    provider: str,
    email: str,
    source: str = "manual",
) -> dict:
    """Record an explicit identity confirmation when a CLI hides its email."""
    name = validate_profile_name(name)
    data = load_registry()
    record = provider_record(data, name, provider)
    if not profile_is_authenticated(provider, record):
        raise AccountProfileError(f"'{name}' no esta autenticado en {provider}.")
    record["expected_email"] = email.strip()
    record["identity_confirmation"] = {
        "email": email.strip(),
        "source": source,
        "timestamp": int(time.time()),
    }
    save_registry(data)
    return data
