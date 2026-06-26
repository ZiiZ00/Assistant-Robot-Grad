"""Arabic shaping, bidirectional display, and Tk font selection helpers."""
from __future__ import annotations

import re
import tkinter.font as tkfont
from typing import Any

ARABIC_PATTERN = re.compile(r"[\u0600-\u06FF]")
ARABIC_FONT_CANDIDATES = ("Noto Naskh Arabic", "Noto Sans Arabic", "DejaVu Sans")

try:
    import arabic_reshaper  # type: ignore
    from bidi.algorithm import get_display  # type: ignore
except ImportError as exc:
    arabic_reshaper = None
    get_display = None
    print(f"WARNING: Arabic shaping libraries are unavailable ({exc}). "
          "Install arabic-reshaper and python-bidi; using unshaped text.")

_font_cache: dict[str, str] = {}


def contains_arabic(text: str) -> bool:
    return bool(ARABIC_PATTERN.search(str(text)))


def shape_arabic_text(text: str) -> str:
    """Return Tk-ready visual-order Arabic while leaving other text unchanged."""
    if not contains_arabic(text):
        return text
    if arabic_reshaper is None or get_display is None:
        return text
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception as exc:
        print(f"WARNING: Could not shape Arabic UI text: {exc}")
        return text


def select_arabic_font(widget: Any) -> str:
    """Choose the first installed Arabic-capable font from the preferred list."""
    display_key = str(widget.winfo_toplevel())
    if display_key in _font_cache:
        return _font_cache[display_key]
    try:
        installed = set(tkfont.families(widget))
    except Exception:
        installed = set()
    selected = next((name for name in ARABIC_FONT_CANDIDATES if name in installed), "DejaVu Sans")
    _font_cache[display_key] = selected
    return selected


def ui_font(widget: Any, text: str, size: int, bold: bool = False) -> tuple[str, int, str]:
    family = select_arabic_font(widget) if contains_arabic(text) else "Arial"
    return family, size, "bold" if bold else "normal"


def configure_text(widget: Any, text: str, size: int, bold: bool = False) -> None:
    """Apply shaped text and a matching font to an existing Tk widget."""
    widget.configure(text=shape_arabic_text(text), font=ui_font(widget, text, size, bold))
