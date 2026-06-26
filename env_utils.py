"""Environment and .env helpers for Plan B secrets."""
from __future__ import annotations

import os
from pathlib import Path


_DOTENV_LOADED = False


def load_project_dotenv() -> None:
    """Load .env from the Plan B project folder without overriding shell variables."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    env_path = Path(__file__).resolve().parent / ".env"
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(env_path)
        return
    except Exception:
        pass
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name and name not in os.environ:
                os.environ[name] = value
    except Exception:
        return


def get_env_first(*names: str) -> str | None:
    load_project_dotenv()
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None
