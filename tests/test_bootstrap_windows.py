import importlib.util
import subprocess
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "clients" / "windows" / "bootstrap-windows.py"
)


def load_bootstrap_module():
    spec = importlib.util.spec_from_file_location("bootstrap_windows", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bootstrap_aborts_when_dependency_install_fails(tmp_path, monkeypatch, capsys):
    bootstrap = load_bootstrap_module()
    repo_root = tmp_path / "repo"
    venv_path = repo_root / ".venv"
    pip_exe = venv_path / "Scripts" / "pip.exe"
    pip_exe.parent.mkdir(parents=True)
    pip_exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(bootstrap, "REPO_ROOT", repo_root)
    monkeypatch.setattr(bootstrap, "VENV_PATH", venv_path)
    monkeypatch.setattr(bootstrap, "ENV_FILE", repo_root / ".env")
    monkeypatch.setattr(bootstrap, "has_python", lambda: True)
    monkeypatch.setattr(
        bootstrap,
        "cmd",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, returncode=1),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": (_ for _ in ()).throw(AssertionError("input should not be reached")),
    )

    with pytest.raises(SystemExit, match="1"):
        bootstrap.main()

    captured = capsys.readouterr()
    assert "ERROR: Dependency installation failed." in captured.out
    assert "[4/4] Bootstrap complete." not in captured.out
    assert not (repo_root / ".env").exists()
