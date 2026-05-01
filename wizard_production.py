from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser

from core.preflight import (
    print_checks,
    prompt_for_api_keys,
    prompt_for_phase_providers,
    run_preflight,
)


HOST = "127.0.0.1"
PORT = 5050
URL = f"http://{HOST}:{PORT}"


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def open_browser(url: str) -> None:
    if os.environ.get("WSL_DISTRO_NAME"):
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            pass
    webbrowser.open(url)


def main() -> int:
    clear_screen()
    print("=" * 68)
    print("   ASTRA PRODUCTION WIZARD - API Validation + Robust Launch")
    print("=" * 68)

    prompt_for_api_keys()
    phase_providers = prompt_for_phase_providers()

    verify_api = input("\nRun a live API health check before launch? [Y/n]: ").strip().lower() != "n"
    checks = run_preflight(verify_api=verify_api, phase_providers=phase_providers)
    ready = print_checks(checks)

    if not ready:
        print("\nPreflight found required failures.")
        print("Fix the failed items above, then run this wizard again.")
        input("\nPress Enter to exit...")
        return 1

    print("\nStarting ASTRA Web Studio Server...")
    print("Providers:")
    for phase, provider in phase_providers.items():
        print(f"  {phase}: {provider}")
    print(f"URL: {URL}")
    print("Your browser will open automatically.")

    time.sleep(1.5)
    open_browser(URL)

    return subprocess.call([sys.executable, "web/app.py"])


if __name__ == "__main__":
    raise SystemExit(main())
