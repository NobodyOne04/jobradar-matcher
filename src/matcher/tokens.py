"""Tokens for phrase matching: the same function tokenizes job text and skill aliases."""

import re
import unicodedata

# A token keeps . + # inside (c++, c#, .net, node.js) and splits on everything else, including
# "/" and "-": "Python/Scala" and "CI/CD" become two tokens each, and so do their aliases.
_TOKEN = re.compile(r"\.?[^\W_](?:[^\W_]|[.+#])*")


def tokens(text: str) -> list[str]:
    """Tokens in their original case (for case-sensitive aliases like "Go")."""
    text = unicodedata.normalize("NFKC", text)
    out = []
    for m in _TOKEN.finditer(text):
        tok = m.group().rstrip(".")  # sentence-final dot: "Python." -> "Python"
        if tok and tok != ".":
            out.append(tok)
    return out


def lower(toks: list[str]) -> list[str]:
    return [t.casefold() for t in toks]
