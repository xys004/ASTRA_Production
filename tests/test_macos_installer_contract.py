from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_macos_installer_prefers_supported_python_and_replaces_mismatched_venv():
    installer = (ROOT / "install_macos.sh").read_text(encoding="utf-8")

    candidates = "python3.12 python3.11 python3.10 python3"
    assert candidates in installer
    assert installer.index("python3.12") < installer.index("python3.11")
    assert 'VENV_ID" != "$PYTHON_ID' in installer
    assert "venv.backup." in installer


def test_macos_compiled_accelerators_are_pinned_to_binary_wheels():
    installer = (ROOT / "install_macos.sh").read_text(encoding="utf-8")
    mac_requirements = (ROOT / "requirements-macos.txt").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-workstation.txt").read_text(encoding="utf-8")

    assert "--only-binary=llvmlite,numba" in installer
    assert "-r requirements-workstation.txt" in mac_requirements
    assert "numba==0.60.0" in requirements
    assert "llvmlite==0.43.0" in requirements
