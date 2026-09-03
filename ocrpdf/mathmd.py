import re
from html import unescape
from html.parser import HTMLParser

PIPE_ALLOWED_TAGS = {"br", "sup", "sub", "b", "i", "em", "strong", "u", "small", "span"}

UNICODE_MATH = {
    "×": r"\times",
    "÷": r"\div",
    "−": "-",
    "–": "-",
    "—": "-",
    "≤": r"\le",
    "≥": r"\ge",
    "⩽": r"\le",
    "⩾": r"\ge",
    "≦": r"\le",
    "≧": r"\ge",
    "≠": r"\ne",
    "≈": r"\approx",
    "≅": r"\cong",
    "∼": r"\sim",
    "±": r"\pm",
    "∓": r"\mp",
    "√": r"\sqrt",
    "°": r"^{\circ}",
    "′": "'",
    "″": "''",
    "π": r"\pi",
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\varepsilon",
    "θ": r"\theta",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "τ": r"\tau",
    "φ": r"\varphi",
    "ω": r"\omega",
    "Δ": r"\Delta",
    "Σ": r"\sum",
    "∑": r"\sum",
    "∫": r"\int",
    "∞": r"\infty",
    "∩": r"\cap",
    "∪": r"\cup",
    "∈": r"\in",
    "∉": r"\notin",
    "⊂": r"\subset",
    "⊆": r"\subseteq",
    "⊥": r"\perp",
    "∥": r"\parallel",
    "∠": r"\angle",
    "△": r"\triangle",
    "→": r"\to",
    "⇒": r"\Rightarrow",
    "⇔": r"\Leftrightarrow",
    "∴": r"\therefore",
    "∵": r"\because",
    "⋅": r"\cdot",
    "∘": r"\circ",
    "…": r"\ldots",
    "…": r"\ldots",
}

ENTITIES = {
    "&lt;": "<",
    "&gt;": ">",
    "&amp;": "&",
    "&nbsp;": " ",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
}

_FENCE_SPLIT = re.compile(r"^(\s*```.*?\n[\s\S]*?```\s*)$", re.MULTILINE)
_DOLLAR_DISPLAY = re.compile(r"\$\$([\s\S]+?)\$\$")
_DOLLAR_INLINE = re.compile(r"(?<!\$)\$((?:[^$\n\\]|\\.)+?)(?<!\\)\$(?!\$)")
_CODE_SPAN = re.compile(r"`[^`\n]+`")
_TABLE_BLOCK = re.compile(r"<table\b[\s\S]*?</table\s*>", re.IGNORECASE)


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None
        self.complex = False
        self.found = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag == "td" or tag == "th":
            self._cell = []
            a = dict(attrs)
            if "rowspan" in a or "colspan" in a:
                self.complex = True
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")
        elif tag == "table":
            self.found = True

    def handle_endtag(self, tag):
        if tag == "tr" and self._row is not None:
            if self._cell is not None:
                self._row.append("".join(self._cell))
                self._cell = None
            self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            if self._row is None:
                self._row = []
            self._row.append("".join(self._cell))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _pipe_cell(text: str) -> str:
    text = text.strip()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    text = "<br>".join(ln for ln in lines if ln)
    return text.replace("|", "\\|")


def _convert_one_table(html_block: str) -> str:
    p = _TableParser()
    try:
        p.feed(html_block)
        p.close()
    except Exception:
        return html_block
    if not p.found or p.complex or len(p.rows) < 1:
        return html_block
    rows = [r for r in p.rows if any(c.strip() for c in r)]
    if not rows:
        return html_block
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    header = rows[0]
    out = ["| " + " | ".join(_pipe_cell(c) for c in header) + " |"]
    out.append("|" + "---|" * ncols)
    for r in rows[1:]:
        out.append("| " + " | ".join(_pipe_cell(c) for c in r) + " |")
    return "\n".join(out)


def _outside_fences(md: str):
    parts = _FENCE_SPLIT.split(md)
    return [p for p in parts if p]


def html_tables_to_pipes(md: str) -> str:
    result = []
    for part in _outside_fences(md):
        if part.lstrip().startswith("```"):
            result.append(part)
            continue
        result.append(_TABLE_BLOCK.sub(lambda m: _convert_one_table(m.group(0)), part))
    return "".join(result)


def _fix_math(text: str) -> str:
    for ent, ch in ENTITIES.items():
        text = text.replace(ent, ch)
    text = unescape(text) if "&" in text else text
    for uni, cmd in UNICODE_MATH.items():
        text = text.replace(uni, cmd)
    return text


def _clean_segment(segment: str) -> str:
    pieces = []
    last = 0
    for m in _CODE_SPAN.finditer(segment):
        pieces.append(_apply_math(segment[last:m.start()]))
        pieces.append(m.group(0))
        last = m.end()
    pieces.append(_apply_math(segment[last:]))
    return "".join(pieces)


def _apply_math(segment: str) -> str:
    pieces = []
    last = 0
    pattern = re.compile(_DOLLAR_DISPLAY.pattern + "|" + _DOLLAR_INLINE.pattern)
    for m in pattern.finditer(segment):
        pieces.append(segment[last:m.start()])
        inner = m.group(1) if m.group(1) is not None else (m.group(2) or "")
        marker = "$$" if m.group(1) is not None else "$"
        pieces.append(marker + _fix_math(inner) + marker)
        last = m.end()
    pieces.append(segment[last:])
    return "".join(pieces)


def cleanup_math(md: str) -> str:
    result = []
    for part in _outside_fences(md):
        if part.lstrip().startswith("```"):
            result.append(part)
        else:
            result.append(_clean_segment(part))
    return "".join(result)


def mathify(md: str) -> str:
    return cleanup_math(html_tables_to_pipes(md))
