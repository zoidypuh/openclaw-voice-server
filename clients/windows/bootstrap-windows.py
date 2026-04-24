#!/usr/bin/env python3
"""
Windows bootstrap script for agentic-switchboard v1.

Usage on Windows (PowerShell or CMD):
    py bootstrap-windows.py

This script:
    1. Creates a .venv in the repo root
    2. Installs all dependencies via uv (preferred) or pip
    3. Creates a .env file with a prompt for required secrets
    4. Prints next steps
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.parent
VENV_PATH = REPO_ROOT / ".venv"
ENV_FILE = REPO_ROOT / ".env"
REQUIRED_SECRETS = [
    "AGENTIC_SWITCHBOARD_GATEWAY_TOKEN",
    "AGENTIC_SWITCHBOARD_ELEVENLABS_API_KEY",
]
OPTIONAL_SECRETS = [
    ("AGENTIC_SWITCHBOARD_HTTP_HOST", "127.0.0.1"),
    ("AGENTIC_SWITCHBOARD_HTTP_PORT", "8765"),
]


def has_uv() -> bool:
    return shutil.which("uv") is not None


def has_python() -> bool:
    return shutil.which("python") is not None or shutil.which("python3") is not None


def cmd(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(argv)}")
    return subprocess.run(argv, **kwargs)


def run_or_exit(argv: list[str], *, error_message: str, **kwargs) -> None:
    result = cmd(argv, **kwargs)
    if result.returncode != 0:
        print(f"ERROR: {error_message}")
        sys.exit(result.returncode or 1)


def rmtree(path: Path) -> None:
    def onerror(func, path2, exc_info):
        os.chmod(path2, stat.S_IWRITE)
        func(path2)
    shutil.rmtree(path, onerror=onerror)


def main() -> None:
    print(f"=== agentic-switchboard Windows bootstrap ===")
    print(f"Repo root: {REPO_ROOT}")
    print()

    if not has_python():
        print("ERROR: Python not found. Install Python 3.10+ from python.org first.")
        sys.exit(1)

    # 1. Create or reuse .venv
    if VENV_PATH.exists():
        print(f"[1/4] .venv exists at {VENV_PATH}, skipping creation.")
    else:
        print("[1/4] Creating .venv ...")
        python_bin = "python" if shutil.which("python") else "python3"
        result = cmd([python_bin, "-m", "venv", str(VENV_PATH)])
        if result.returncode != 0:
            print("ERROR: Failed to create .venv.")
            sys.exit(1)
        print("  .venv created.")

    # 2. Install dependencies
    print("[2/4] Installing dependencies ...")
    pip_exe = VENV_PATH / "Scripts" / "pip.exe"
    uv_exe = VENV_PATH / "Scripts" / "uv.exe"

    if uv_exe.exists():
        print("  Using uv (fast, preferred) ...")
        run_or_exit(
            [str(uv_exe), "pip", "install", "-e", str(REPO_ROOT)],
            cwd=str(REPO_ROOT),
            error_message="Dependency installation failed.",
        )
    elif pip_exe.exists():
        print("  Using pip ...")
        run_or_exit(
            [str(pip_exe), "install", "-e", str(REPO_ROOT)],
            cwd=str(REPO_ROOT),
            error_message="Dependency installation failed.",
        )
    else:
        print("ERROR: Neither uv nor pip found inside .venv.")
        sys.exit(1)

    # 3. .env setup
    print("[3/4] Setting up .env ...")
    existing: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()

    secrets_to_write: dict[str, str] = {}

    print("  Required secrets (paste from your gateway config):")
    for key in REQUIRED_SECRETS:
        current = existing.get(key, "")
        if current:
            print(f"    {key}: [already set]")
            continue
        value = input(f"    {key}: ").strip()
        if value:
            secrets_to_write[key] = value

    print("  Optional secrets (press Enter to use defaults):")
    for key, default in OPTIONAL_SECRETS:
        current = existing.get(key, "")
        if current:
            print(f"    {key}: [already set]")
            continue
        value = input(f"    {key} [{default}]: ").strip()
        secrets_to_write[key] = value or default

    if secrets_to_write or not ENV_FILE.exists():
        env_lines = [f"{k}={v}" for k, v in secrets_to_write.items()]
        if existing:
            env_lines = [f"{k}={v}" for k, v in existing.items()] + env_lines
        env_lines.append("")
        ENV_FILE.write_text("\n".join(env_lines), encoding="utf-8")
        print(f"  .env written.")

    # 4. Done
    print()
    print("[4/4] Bootstrap complete.")
    print()
    print("Next steps:")
    print(f"  1. Edit config.json to use the Windows v1 defaults:")
    print(f"       stt.device: 'cpu'  (or set a remote whisper_endpoint_url)")
    print(f"       tts.enabled_providers: ['elevenlabs']  (or keep ['edge'])")
    print(f"  2. Start the server:")
    print(f"       .\\.venv\\Scripts\\python.exe -m agentic_switchboard")
    print(f"  3. Or use the Tauri tray client: run 'npm run tauri:dev' from src-tauri/")
    print()


if __name__ == "__main__":
    main()
