#!/usr/bin/env python3
"""Manage explicit, isolated subscription profiles for ASTRA's model CLIs."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from core.account_profiles import (  # noqa: E402
    PROVIDERS,
    AccountProfileError,
    add_isolated_profile,
    auth_marker,
    bootstrap_current_profile,
    confirm_provider_identity,
    environment_for_record,
    load_registry,
    profile_is_authenticated,
    provider_record,
    registry_path,
    set_active_profile,
    set_provider_home,
)
from core.runtime_resources import acquire_cycle_slot, recommended_parallelism  # noqa: E402


def _jwt_email(token: str) -> str | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return None
    direct = claims.get("email")
    if direct:
        return str(direct)
    for value in claims.values():
        if isinstance(value, dict) and value.get("email"):
            return str(value["email"])
    return None


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _detect_current_emails() -> dict:
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    codex = _json(codex_home / "auth.json")
    codex_email = _jwt_email(str((codex.get("tokens") or {}).get("id_token") or ""))
    agy = _json(home / ".gemini" / "google_accounts.json")
    emails = {"codex": codex_email, "agy": agy.get("active")}
    # Claude's credential file intentionally has no stable public email field.
    try:
        result = subprocess.run(
            [shutil.which("claude") or "claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        status = json.loads(result.stdout) if result.returncode == 0 else {}
        emails["claude"] = status.get("email")
    except Exception:
        emails["claude"] = None
    return {key: value for key, value in emails.items() if value}


def _emails_from_args(args) -> dict:
    return {
        provider: getattr(args, f"{provider}_email")
        for provider in PROVIDERS
        if getattr(args, f"{provider}_email", None)
    }


def _print_registry(data: dict) -> None:
    print(f"Registry: {registry_path()}")
    active = data.get("active") or {}
    for name in sorted((data.get("profiles") or {}).keys()):
        print(f"\n{name}")
        for provider in PROVIDERS:
            try:
                record = provider_record(data, name, provider)
            except AccountProfileError:
                continue
            marker = "authenticated" if profile_is_authenticated(provider, record) else "login required"
            selected = " ACTIVE" if active.get(provider) == name else ""
            email = record.get("expected_email") or "email not recorded"
            print(f"  {provider:7} {marker:15} {email}{selected}")
            print(f"           home={record['home']}")


def _detected_email(provider: str, record: dict) -> str | None:
    home = Path(record["home"])
    if provider == "codex":
        auth = _json(home / "auth.json")
        return _jwt_email(str((auth.get("tokens") or {}).get("id_token") or ""))
    if provider == "agy":
        return _json(home / ".gemini" / "google_accounts.json").get("active")
    env = os.environ.copy()
    env.update(environment_for_record(provider, record))
    try:
        result = subprocess.run(
            [shutil.which("claude") or "claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=env,
        )
        status = json.loads(result.stdout) if result.returncode == 0 else {}
        return status.get("email")
    except Exception:
        return None


def _verify(data: dict) -> bool:
    active = data.get("active") or {}
    valid = True
    print("Active account verification:")
    for provider in PROVIDERS:
        name = active.get(provider)
        if not name:
            print(f"  {provider:7} FAIL no active profile")
            valid = False
            continue
        record = provider_record(data, name, provider)
        expected = record.get("expected_email")
        actual = _detected_email(provider, record)
        confirmation = record.get("identity_confirmation") or {}
        confirmed = (
            not actual
            and bool(expected)
            and confirmation.get("email", "").casefold() == expected.casefold()
        )
        matches = (
            bool(actual) and (not expected or actual.casefold() == expected.casefold())
        ) or confirmed
        evidence = "cli" if actual else confirmation.get("source", "none")
        print(
            f"  {provider:7} {'PASS' if matches else 'FAIL'} "
            f"profile={name} actual={actual or 'not exposed'} "
            f"evidence={evidence} "
            f"expected={expected or 'not recorded'}"
        )
        valid = valid and matches
    return valid


def _acquire_switch_guard() -> list:
    count = int(recommended_parallelism().get("deliberative_cycles", 1))
    held = []
    for _ in range(max(1, count)):
        slot, active = acquire_cycle_slot(PROJECT_ROOT, max_slots=max(1, count))
        if slot is None:
            for acquired in held:
                acquired.release()
            pids = sorted({str(item.get("pid", "?")) for item in active})
            raise AccountProfileError(
                "No se cambia una cuenta durante un ciclo deliberativo activo"
                + (f" (PID {', '.join(pids)})." if pids else ".")
            )
        held.append(slot)
    return held


def _login(name: str, provider: str) -> int:
    data = load_registry()
    record = provider_record(data, name, provider)
    current = data.get("active", {}).get(provider)
    override = environment_for_record(provider, record)

    env = os.environ.copy()
    env.update(override)
    if provider == "codex":
        binary = (os.environ.get("ASTRA_CODEX_BIN") or shutil.which("codex") or "codex")
        command = [binary, "login"]
    elif provider == "claude":
        binary = (os.environ.get("ASTRA_CLAUDE_BIN") or shutil.which("claude") or "claude")
        command = [binary, "auth", "login"]
    else:
        binary = (os.environ.get("ASTRA_AGY_BIN") or shutil.which("agy") or "agy")
        command = [binary]
        print("AGY abrira su interfaz en el hogar aislado. Completa el acceso Google y sal.")
    print(f"Autenticando {provider} para '{name}' (perfil activo permanece: {current or 'ninguno'})...")
    return subprocess.call(command, env=env)


def _add_email_options(parser: argparse.ArgumentParser) -> None:
    for provider in PROVIDERS:
        parser.add_argument(f"--{provider}-email")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Perfiles manuales de Codex, Claude y AGY para ASTRA"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    bootstrap = sub.add_parser("bootstrap", help="registrar las sesiones actuales")
    bootstrap.add_argument("--name", default="primary")
    bootstrap.add_argument(
        "--refresh",
        action="store_true",
        help="actualizar las rutas del perfil con el entorno actual",
    )
    _add_email_options(bootstrap)
    add = sub.add_parser("add", help="crear hogares aislados para otro usuario")
    add.add_argument("name")
    _add_email_options(add)
    sub.add_parser("list", help="listar perfiles sin mostrar secretos")
    sub.add_parser("status", help="alias de list")
    login = sub.add_parser("login", help="autenticar una vez un proveedor/perfil")
    login.add_argument("name")
    login.add_argument("provider", choices=PROVIDERS)
    use = sub.add_parser("use", help="cambiar explicitamente el perfil activo")
    use.add_argument("name")
    use.add_argument("--provider", choices=(*PROVIDERS, "all"), required=True)
    configure = sub.add_parser(
        "configure",
        help="asociar un proveedor a un hogar autenticado existente",
    )
    configure.add_argument("name")
    configure.add_argument("provider", choices=PROVIDERS)
    configure.add_argument("home")
    configure.add_argument("--email", required=True)
    confirm = sub.add_parser(
        "confirm",
        help="registrar una comprobacion manual cuando el CLI oculta el correo",
    )
    confirm.add_argument("name")
    confirm.add_argument("provider", choices=PROVIDERS)
    confirm.add_argument("email")
    sub.add_parser("verify", help="verificar las identidades activas reales")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "bootstrap":
            emails = _detect_current_emails()
            emails.update(_emails_from_args(args))
            data = bootstrap_current_profile(args.name, emails, replace=args.refresh)
            _print_registry(data)
        elif args.command == "add":
            data = add_isolated_profile(args.name, _emails_from_args(args))
            _print_registry(data)
            print("\nSiguiente paso: autentica cada proveedor con el subcomando 'login'.")
        elif args.command in {"list", "status"}:
            _print_registry(load_registry())
        elif args.command == "login":
            return _login(args.name, args.provider)
        elif args.command == "use":
            providers = list(PROVIDERS) if args.provider == "all" else [args.provider]
            held = _acquire_switch_guard()
            try:
                data = set_active_profile(args.name, providers)
            finally:
                for slot in held:
                    slot.release()
            print(f"Perfil '{args.name}' activo para: {', '.join(providers)}")
            _print_registry(data)
        elif args.command == "configure":
            held = _acquire_switch_guard()
            try:
                candidate = {"home": str(Path(args.home).expanduser())}
                actual = _detected_email(args.provider, candidate)
                if not actual or actual.casefold() != args.email.casefold():
                    raise AccountProfileError(
                        f"La identidad real de {args.provider} es "
                        f"'{actual or 'desconocida'}', no '{args.email}'."
                    )
                data = set_provider_home(
                    args.name, args.provider, Path(args.home), args.email
                )
            finally:
                for slot in held:
                    slot.release()
            print(
                f"{args.provider} en '{args.name}' asociado y verificado como {actual}."
            )
            _print_registry(data)
        elif args.command == "verify":
            return 0 if _verify(load_registry()) else 3
        elif args.command == "confirm":
            data = confirm_provider_identity(
                args.name, args.provider, args.email, source="manual-user"
            )
            print(
                f"Identidad de {args.provider} en '{args.name}' confirmada "
                f"manualmente como {args.email}."
            )
            _print_registry(data)
        return 0
    except AccountProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
