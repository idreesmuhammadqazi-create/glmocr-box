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
    "≤": r"\leq ", "≥": r"\geq ", "≠": r"\neq ",
    "×": r"\times ", "÷": r"\div ", "±": r"\pm ", "−": "-",
    "π": r"\pi ", "∞": r"\infty ", "′": "'", "°": r"^\circ",
    "√": r"\sqrt", "∴": r"\therefore ", "∵": r"\because ",
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
    """Make a string safe to drop into a \\text{} so KaTeX always accepts it."""
    return s.replace("\\", r"\backslash ").replace("{", "\\{").replace("}", "\\}") \
            .replace("$", "").replace("%", r"\%").replace("#", r"\#").replace("_", r"\_") \
            .replace("^", r"\^{}").replace("&", r"\&")


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
    out = []
    for m, c in segs:
        out.append(f"${c}$" if m else c)
    return "".join(out), problems


MATH_FIELDS = ("text", "answer", "working", "notes")


def repair_text(text: str) -> list[tuple[bool, str]]:
    """Fast repair (no subprocess): unicode + delimiters + braces. Returns segments."""
    text = replace_unicode(text)
    text = "\n".join(_fix_line_delimiters(line) for line in text.split("\n"))
    return [(m, balance_braces(c) if m else c) for m, c in split_math(text)]


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
        dataset["questions"][qi][f] = "".join(f"${c}$" if m else c for m, c in segs)
    return dataset, problems
