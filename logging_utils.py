"""Console output that never crashes the tour on a non-UTF-8 terminal."""
from __future__ import annotations

import sys


def safe_print(message: object) -> None:
    text = str(message)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, errors="backslashreplace").decode(encoding), flush=True)
