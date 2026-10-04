from __future__ import annotations
import html

def esc(text: str) -> str:
    return html.escape(text, quote=False)

def chunk(text: str, limit: int) -> list[str]:
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit * 0.5:
            cut = text.rfind(" ", 0, limit)
        if cut < limit * 0.5:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n ")
    if text or not parts:
        parts.append(text)
    return parts
