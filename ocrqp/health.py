"""Per-document health report so batch runs are self-checking.

The goal: you should NOT have to eyeball every markscheme. This inspects the
dataset and flags anything suspicious; you only look when it warns.
"""
from __future__ import annotations

import re

from .latex import split_math, validate_katex

# A sane question id: 1, 2(a), 5(c)(ii), 3(a)(iii) ...
QID_RE = re.compile(r"^\d{1,2}(\([a-z]+\))*(\((?:i{1,3}|iv|v)\))*$")


def validate_dataset(dataset: dict, validate_katex_flag: bool = True) -> dict:
    qs = dataset.get("questions", [])
    anomalies: list[str] = []

    # --- structural checks ------------------------------------------------ #
    seen: dict[str, int] = {}
    for q in qs:
        seen[q["id"]] = seen.get(q["id"], 0) + 1
    for qid, n in seen.items():
        if n > 1:
            anomalies.append(f"duplicate id: {qid} (x{n})")

    for q in qs:
        if not QID_RE.match(q.get("id", "")):
            anomalies.append(f"suspicious id: {q.get('id')!r}")
        if q.get("marks") is None:
            anomalies.append(f"missing marks: {q.get('id')}")
        if not (q.get("text") or "").strip() and not (q.get("answer") or "").strip():
            anomalies.append(f"empty content: {q.get('id')}")

    # --- LaTeX validity --------------------------------------------------- #
    segs = [
        c
        for q in qs
        for f in ("text", "answer", "working", "notes")
        for m, c in split_math(q.get(f) or "")
        if m
    ]
    katex_invalid = 0
    if validate_katex_flag and segs:
        results = validate_katex(segs)
        katex_invalid = sum(1 for ok, _ in results if not ok)

    fallbacks = len(dataset.get("latex_repairs", []) or [])

    # --- verdict ------------------------------------------------------------ #
    if katex_invalid or any("suspicious id" in a or "duplicate" in a for a in anomalies):
        verdict = "FAIL"
    elif anomalies or fallbacks:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return {
        "paper": dataset.get("paper", ""),
        "kind": dataset.get("kind", ""),
        "questions": len(qs),
        "total_marks": sum((q.get("marks") or 0) for q in qs),
        "katex_segments": len(segs),
        "katex_invalid": katex_invalid,
        "fallbacks": fallbacks,
        "anomalies": anomalies,
        "verdict": verdict,
    }


def format_report(rep: dict) -> str:
    lines = [
        f"[{rep['verdict']}] {rep['paper']} ({rep['kind']}): "
        f"{rep['questions']} questions, {rep['total_marks']} marks, "
        f"KaTeX {rep['katex_segments'] - rep['katex_invalid']}/{rep['katex_segments']} valid, "
        f"{rep['fallbacks']} fallbacks",
    ]
    for a in rep["anomalies"][:12]:
        lines.append(f"    ! {a}")
    if len(rep["anomalies"]) > 12:
        lines.append(f"    ... +{len(rep['anomalies']) - 12} more")
    return "\n".join(lines)
