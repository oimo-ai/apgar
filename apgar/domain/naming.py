from __future__ import annotations

import re
import unicodedata

_UNSAFE = re.compile(r"[^a-z0-9._-]+")
_DASH_RUN = re.compile(r"-+")


def _strip_edges(text: str) -> str:
    while text and (text[0] in "_-." or text[-1] in "-."):
        if text[0] in "_-.":
            text = text[1:]
        elif text[-1] in "-.":
            text = text[:-1]
    return text


def slugify(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw).lower()
    text = _UNSAFE.sub("-", text)
    text = _DASH_RUN.sub("-", text)
    text = _strip_edges(text)
    text = text[:64].rstrip("-.")
    if text == "":
        return "agent"
    return text
