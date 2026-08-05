from pathlib import Path

from scripts.configure_antigravity_mcp import venv_python_path


ROOT = Path(__file__).resolve().parent.parent


def test_windows_installer_selects_python_312_and_backs_up_mismatched_venv():
    installer = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "-3.12" in installer
    assert "venv.backup." in installer
    assert "requirements-workstation.txt" in installer
    assert "--only-binary=llvmlite,numba" in installer


def test_antigravity_config_uses_native_venv_layout():
    assert venv_python_path("nt") == ROOT / "venv" / "Scripts" / "python.exe"
    assert venv_python_path("posix") == ROOT / "venv" / "bin" / "python"
