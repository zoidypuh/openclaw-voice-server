from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys

from .errors import ValidationError


def module_available(import_name: str | None) -> bool:
    if not import_name:
        return True
    return importlib.util.find_spec(import_name) is not None


def ensure_python_package(requirement: str | None, import_name: str | None) -> dict[str, str | bool]:
    if not requirement or module_available(import_name):
        return {"installed": False, "requirement": requirement or ""}

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", requirement],
        capture_output=True,
        text=True,
        check=False,
    )
    importlib.invalidate_caches()
    if result.returncode != 0 or not module_available(import_name):
        detail = (result.stderr or result.stdout or "package install failed").strip()
        raise ValidationError(detail.splitlines()[-1] if detail else "package install failed")

    return {"installed": True, "requirement": requirement}
