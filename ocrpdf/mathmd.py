import re
from html import unescape
from html.parser import HTMLParser

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
_MATH_PATTERN = re.compile(r"\$\$([\s\S]+?)\$\$|(?<!\$)\$((?:[^$\n\\]|\\.)+?)(?<!\\)\$(?!\$)")
_CODE_SPAN = re.compile(r"`[^`\n]+`")
_TABLE_BLOCK = re.compile(r"<table\b[\s\S]*?</table\s*>", re.IGNORECASE)


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row_idx = -1
        self._cell = None
        self._span = 1
        self._colspan = 1
        self.found = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.found = True
        elif tag == "tr":
            if self._cell is not None:
                self._close_cell()
            self._row_idx += 1
        elif tag in ("td", "th"):
            if self._cell is not None:
                self._close_cell()
            self._cell = []
            a = dict(attrs)
            self._span = min(int(a.get("rowspan", 1) or 1), 100)
            self._colspan = min(int(a.get("colspan", 1) or 1), 100)
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._close_cell()
        elif tag == "table":
            if self._cell is not None:
                self._close_cell()

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def _close_cell(self):
        text = "".join(self._cell)
        self._cell = None
        while len(self.rows) <= self._row_idx:
            self.rows.append({})
        row = self.rows[self._row_idx]
        col = 0
        while col in row:
            col += 1
        row[col] = text
        for k in range(1, self._colspan):
            row[col + k] = ""
        for r in range(1, self._span):
            idx = self._row_idx + r
            while len(self.rows) <= idx:
                self.rows.append({})
            self.rows[idx][col] = text
            for k in range(1, self._colspan):
                self.rows[idx][col + k] = ""
        self._span = 1
        self._colspan = 1


def _pipe_cell(text: str) -> str:
    text = text.strip()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    text = "<br>".join(ln for ln in lines if ln)
    if text.count("$") % 2 == 1:
        text = text.replace("$", "\\$")
    return text.replace("|", "\\|")


def _convert_one_table(html_block: str) -> str:
    p = _TableParser()
    try:
        p.feed(html_block)
        p.close()
    except Exception:
        return html_block
    if not p.found or not p.rows:
        return html_block
    rows = [r for r in p.rows if any(c.strip() for c in r.values())]
    if not rows:
        return html_block
    ncols = max(max(r) for r in rows) + 1
    grid = [[r.get(c, "") for c in range(ncols)] for r in rows]
    out = ["| " + " | ".join(_pipe_cell(c) for c in grid[0]) + " |"]
    out.append("|" + "---|" * ncols)
    for r in grid[1:]:
        out.append("| " + " | ".join(_pipe_cell(c) for c in r) + " |")
    return "\n".join(out)


def _outside_fences(md: str):
    return [p for p in _FENCE_SPLIT.split(md) if p]


def html_tables_to_pipes(md: str) -> str:
    result = []
    for part in _outside_fences(md):
        if part.lstrip().startswith("```"):
            result.append(part)
            continue
        result.append(_TABLE_BLOCK.sub(lambda m: _convert_one_table(m.group(0)), part))
    return "".join(result)


def _balance_braces(text: str) -> str:
    out = []
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
            out.append(ch)
        elif ch == "}":
            if depth == 0:
                continue
            depth -= 1
            out.append(ch)
        else:
            out.append(ch)
    if depth > 0:
        out.append("}" * depth)
    return "".join(out)


def _fix_math(text: str) -> str:
    for ent, ch in ENTITIES.items():
        text = text.replace(ent, ch)
    if "&" in text:
        text = unescape(text)
    for uni, cmd in UNICODE_MATH.items():
        text = text.replace(uni, cmd)
    if "{" in text or "}" in text:
        text = _balance_braces(text)
    return text


def _apply_math(segment: str) -> str:
    pieces = []
    last = 0
    for m in _MATH_PATTERN.finditer(segment):
        pieces.append(segment[last:m.start()])
        inner = m.group(1) if m.group(1) is not None else (m.group(2) or "")
        marker = "$$" if m.group(1) is not None else "$"
        pieces.append(marker + _fix_math(inner) + marker)
        last = m.end()
    pieces.append(segment[last:])
    return "".join(pieces)


def _clean_segment(segment: str) -> str:
    pieces = []
    last = 0
    for m in _CODE_SPAN.finditer(segment):
        pieces.append(_apply_math(segment[last:m.start()]))
        pieces.append(m.group(0))
        last = m.end()
    pieces.append(_apply_math(segment[last:]))
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
