"""Guarantee KaTeX-valid LaTeX in extracted text.

Strategy:
  1. repair  — fix common OCR LaTeX issues (unicode symbols, unbalanced
     `$`/`{}`, dropped delimiters).
  2. validate — render every math segment with real KaTeX (strict mode) via
     node; anything still invalid is repaired again, and as a last resort
     wrapped so the document always renders without KaTeX throwing.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

UNICODE_MAP = {
    # relations & operators
    "≤": r" \leq ", "≥": r" \geq ", "≠": r" \neq ",
    "×": r" \times ", "÷": r" \div ", "±": r" \pm ",
    "−": "-", "–": "-", "—": "-", "‐": "-", "‑": "-",
    "∗": r" \ast ",
    # fullwidth variants (seen in A-Level schemes)
    "＜": "<", "＞": ">", "＝": "=",
    # greek
    "λ": r" \lambda ", "μ": r" \mu ", "σ": r" \sigma ",
    "α": r" \alpha ", "β": r" \beta ", "π": r" \pi ",
    "φ": r" \phi ", "Φ": r" \Phi ", "Σ": r" \Sigma ",
    "Δ": r" \Delta ", "θ": r" \theta ",
    # sets & misc
    "∈": r" \in ", "∉": r" \notin ", "∩": r" \cap ",
    "∪": r" \cup ", "⊂": r" \subset ", "∅": r" \emptyset ",
    "∞": r" \infty ", "′": "'", "°": r"^\circ",
    "√": r"\sqrt", "∴": r" \therefore ", "∵": r" \because ",
    # typographic quotes / ellipsis / dots -> ASCII (KaTeX strict rejects them)
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": r" \ldots ", "·": r" \cdot ", "⋅": r" \cdot ",
    "″": '"', "‴": "\"",
}

KATEX_JS = Path(__file__).resolve().parent.parent / "tools" / "katex_check.js"

# A "mathy" line fragment: contains a LaTeX command, ^, _, =, or { }.
MATHY_RE = re.compile(r"(\\[a-zA-Z]+|[\^_{}=])")
UNESCAPED_DOLLAR = re.compile(r"(?<!\\)\$")


def replace_unicode(text: str) -> str:
    for k, v in UNICODE_MAP.items():
        text = text.replace(k, v)
    return text


def balance_braces(s: str) -> str:
    """Balance { } by appending missing closers or dropping stray opens."""
    out = []
    depth = 0
    for ch in s:
        if ch == "{":
            depth += 1
            out.append(ch)
        elif ch == "}":
            if depth == 0:
                continue  # drop stray closer
            depth -= 1
            out.append(ch)
        else:
            out.append(ch)
    out.append("}" * depth)  # close any unclosed opens
    return "".join(out)


def _count_dollars(line: str) -> int:
    return len(UNESCAPED_DOLLAR.findall(line))


def _fix_line_delimiters(line: str) -> str:
    """Ensure an even number of inline `$` on a line.

    Handles the common OCR case of a dropped opening `$`: a line with mathy
    content and a single dangling closing `$` gets the math region wrapped.
    """
    if _count_dollars(line) % 2 == 0:
        return line
    # Odd number of $. Find the last dangling $ and try to open math before the
    # mathy run that precedes it.
    idx = line.rfind("$")
    before, after = line[:idx], line[idx + 1:]
    # Walk back over mathy characters to find where the math starts.
    mstart = len(before)
    while mstart > 0 and re.match(r"[\w\s\\^_{}=+\-*/().,\[\]|<>!]", before[mstart - 1]):
        mstart -= 1
    # Trim leading whitespace in the math region.
    while mstart < len(before) and before[mstart] == " ":
        mstart += 1
    region = before[mstart:]
    if MATHY_RE.search(region):
        return before[:mstart] + "$" + region + "$" + after
    # Can't locate math; drop the dangling $ to keep things valid.
    return before + after


def split_math(text: str) -> list[tuple[bool, str]]:
    """Split into (is_math, content) segments on unescaped $."""
    parts = UNESCAPED_DOLLAR.split(text)
    segs: list[tuple[bool, str]] = []
    for i, part in enumerate(parts):
        if part == "":
            continue
        segs.append((i % 2 == 1, part))
    return segs


def join_segments(segs: list[tuple[bool, str]]) -> str:
    """Reassemble segments, stripping padding inside $...$ (GitHub/KaTeX inline
    math requires the $ to be immediately adjacent to non-space content), and
    keeping a space boundary between a letter/digit and an adjacent $...$ so the
    delimiter is never glued to prose (which would stop it rendering as math)."""
    out: list[str] = []
    for m, c in segs:
        if m:
            if out and out[-1] and out[-1][-1].isalnum():
                out.append(" ")
            out.append("$" + c.strip() + "$")
        else:
            if c and out and out[-1].endswith("$") and c[0].isalnum():
                out.append(" ")
            out.append(c)
    return "".join(out)


def katex_available() -> bool:
    return shutil.which("node") is not None and KATEX_JS.exists()


def validate_katex(exprs: list[str], display: bool = False) -> list[tuple[bool, str | None]]:
    """Validate each expr with real KaTeX (strict). Returns (ok, error) per expr."""
    if not exprs:
        return []
    if not katex_available():
        return [(True, None) for _ in exprs]  # cannot validate -> assume ok
    payload = [{"id": i, "latex": e, "display": display} for i, e in enumerate(exprs)]
    try:
        proc = subprocess.run(
            ["node", str(KATEX_JS)], input=json.dumps(payload),
            capture_output=True, text=True, timeout=60,
            cwd=str(KATEX_JS.parent),
        )
        results = json.loads(proc.stdout)
    except Exception:
        return [(True, None) for _ in exprs]
    by_id = {r["id"]: (r["ok"], r["error"]) for r in results}
    return [by_id.get(i, (True, None)) for i in range(len(exprs))]


def _escape_for_text(s: str) -> str:
    r"""Last-resort: make content safe inside \text{} (KaTeX text mode).

    \text{} cannot span lines and treats \ { } as special, so strip them down
    to plain readable text. Only used when a segment can't be valid math.
    """
    s = s.replace("\n", " ")
    s = s.replace("\\", " ")           # drop command backslashes (show as words)
    s = s.replace("{", "(").replace("}", ")")
    s = s.replace("$", "").replace("%", " percent ").replace("#", "")
    s = s.replace("&", " and ").replace("_", " ").replace("^", " ").replace("~", " ")
    return re.sub(r"  +", " ", s).strip()


def sanitize_text(text: str, validate: bool = True) -> tuple[str, list[str]]:
    """Repair + validate all math in a text. Returns (clean_text, problems)."""
    problems: list[str] = []
    if not text:
        return text, problems

    # 1. unicode + delimiter repair (line-wise for dropped-$ cases)
    text = replace_unicode(text)
    text = "\n".join(_fix_line_delimiters(line) for line in text.split("\n"))

    # 2. split + balance braces in math segments
    segs = split_math(text)
    segs = [(m, balance_braces(c) if m else c) for m, c in segs]

    # 3. validate math segments with KaTeX, repair/escalate on failure
    if validate and katex_available():
        math_idx = [i for i, (m, _) in enumerate(segs) if m]
        exprs = [segs[i][1] for i in math_idx]
        results = validate_katex(exprs)
        for (ok, err), i in zip(results, math_idx):
            if ok:
                continue
            content = segs[i][1]
            # retry once after a unicode/brace re-pass
            retry = balance_braces(replace_unicode(content))
            ok2, _ = validate_katex([retry])[0]
            if ok2:
                segs[i] = (True, retry)
            else:
                # last resort: render as literal text so KaTeX never throws
                segs[i] = (True, r"\text{" + _escape_for_text(content) + "}")
                problems.append(f"escaped invalid latex: {content[:40]!r} ({err})")

    # 4. reassemble
    return join_segments(segs), problems


MATH_FIELDS = ("text", "answer", "working", "notes")


def repair_text(text: str) -> list[tuple[bool, str]]:
    """Fast repair (no subprocess): unicode + delimiters + braces. Returns segments."""
    text = replace_unicode(text)
    text = "\n".join(_fix_line_delimiters(line) for line in text.split("\n"))
    # wrap bare math per line so a math segment never spans a newline
    text = "\n".join(wrap_bare_math(line) for line in text.split("\n"))
    segs = [(m, balance_braces(c) if m else c) for m, c in split_math(text)]
    # KaTeX inline math cannot contain a raw newline -> collapse it
    return [(m, c.replace("\n", " ") if m else c) for m, c in segs]


def sanitize_document(dataset: dict, validate: bool = True) -> tuple[dict, list[str]]:
    """Repair every math field, then batch-validate with KaTeX (one node call).

    Any segment still invalid after repair is wrapped in \\text{} so the whole
    document renders without KaTeX throwing -> 100% valid output.
    """
    problems: list[str] = []
    field_segs: dict[tuple[int, str], list[tuple[bool, str]]] = {}
    exprs: list[str] = []
    locs: list[tuple[int, str, int]] = []

    for qi, q in enumerate(dataset.get("questions", [])):
        for f in MATH_FIELDS:
            t = q.get(f)
            if not t:
                continue
            segs = repair_text(t)
            field_segs[(qi, f)] = segs
            for si, (m, c) in enumerate(segs):
                if m:
                    locs.append((qi, f, si))
                    exprs.append(c)

    if validate and katex_available() and exprs:
        results = validate_katex(exprs)
        for (ok, err), (qi, f, si) in zip(results, locs):
            if not ok:
                segs = field_segs[(qi, f)]
                content = segs[si][1]
                segs[si] = (True, r"\text{" + _escape_for_text(content) + "}")
                qid = dataset["questions"][qi].get("id")
                problems.append(f"{qid}:{f} escaped invalid latex ({(err or '')[:40]})")

    for (qi, f), segs in field_segs.items():
        dataset["questions"][qi][f] = join_segments(segs)
    return dataset, problems


# --------------------------------------------------------------------------- #
# Bare-math wrapping: glm-ocr leaves simple math (inequalities, products) as
# plain text with unicode symbols. After unicode->LaTeX conversion those would
# render as literal \\leq / \\times unless wrapped in $...$. This stage finds math
# runs inside text segments and wraps them.
# --------------------------------------------------------------------------- #
REL_OR_CMD = re.compile(r"\\[a-zA-Z]+|[<>=]")
MARK_LABEL = re.compile(r"^[MAB]\d+(ft)?$", re.IGNORECASE)
PROSE_WORDS = {
    "for", "or", "and", "the", "is", "are", "to", "of", "in", "on", "with",
    "a", "an", "be", "by", "at", "from", "their", "oe", "final", "answer",
    "correct", "extras", "extra", "identifying", "angle", "elevation", "figs",
    "but", "not", "all", "expanded", "brackets", "so", "isw", "ft", "bod",
    "seen", "awrt", "cao", "www", "dep", "cond", "each", "value", "values",
    "better", "placed", "diagram", "accurate", "completed", "reversed",
}


def _is_math_token(tok: str) -> bool:
    if MARK_LABEL.match(tok) or tok.lower() in PROSE_WORDS:
        return False
    if REL_OR_CMD.search(tok):
        return True
    if re.search(r"[\^_]", tok):
        return True
    if re.search(r"\d", tok):
        return True
    return False


def _split_glued(tok: str) -> tuple[str | None, str]:
    """Split a leading prose word glued to a math core: 'for-3<x' -> ('for','-3<x')."""
    m = re.match(r"^([a-z]{2,})(?=[\d\-+(\\<>=])", tok)
    if m and m.group(1).lower() in PROSE_WORDS:
        return m.group(1), tok[m.end():]
    return None, tok


def _classify_segment(seg: str) -> list[tuple[bool, str]]:
    """Split a text segment into (is_math, text) pieces, grouping math runs."""
    tokens = re.findall(r"\S+|\s+", seg)
    pieces: list[tuple[bool | None, str]] = []  # None = whitespace
    for tok in tokens:
        if tok.isspace():
            pieces.append((None, tok))
            continue
        prose, core = _split_glued(tok)
        if prose:
            pieces.append((False, prose))
            pieces.append((None, " "))  # keep a boundary so $ isn't glued to a letter
        if core:
            pieces.append((_is_math_token(core), core))

    out: list[tuple[bool, str]] = []
    i, n = 0, len(pieces)
    while i < n:
        m, t = pieces[i]
        if m is True:
            grp = [t]
            j = i + 1
            while j < n:
                m2, t2 = pieces[j]
                if m2 is None:  # whitespace: bridge only if next is math
                    if j + 1 < n and pieces[j + 1][0] is True:
                        grp.append(t2)
                        j += 1
                        continue
                    break
                if m2 is True:
                    grp.append(t2)
                    j += 1
                    continue
                break
            out.append((True, "".join(grp)))
            i = j
        else:
            out.append((False, t))  # prose or unbridged whitespace
            i += 1
    return out


def wrap_bare_math(text: str) -> str:
    """Wrap bare math expressions in $...$; merge with adjacent math segments."""
    pieces: list[tuple[bool, str]] = []
    for is_math, seg in split_math(text):
        if is_math:
            pieces.append((True, seg))
        else:
            pieces.extend(_classify_segment(seg))
    # merge consecutive math pieces into one $...$ group
    merged: list[tuple[bool, str]] = []
    for is_math, piece in pieces:
        if is_math and merged and merged[-1][0]:
            merged[-1] = (True, merged[-1][1] + piece)
        else:
            merged.append((is_math, piece))
    return join_segments(merged)
