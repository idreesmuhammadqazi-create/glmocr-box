"""Segment page markdown into per-question records.

Heuristic and intentionally modular: IGCSE papers number questions ``1 2 3``
with parts ``(a) (b)`` / ``(i) (ii)`` and marks like ``[2]`` or ``(2 marks)``.
Marking schemes use the same numbering in a table. Tune the regexes below
against real GLM output once sample docs are available.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A top-level question number at the start of a line: "1", "1.", "1 ", "Q1".
QUESTION_RE = re.compile(r"^\s*(?:Q(?:uestion)?\s*)?(\d{1,2})\b[\s.)]*", re.IGNORECASE)
# A part label: "(a)", "(b)", "(i)", "(ii)", "a)", "b)".
PART_RE = re.compile(r"^\s*\(?([a-z]|\b(?:i{1,3}|iv|v)\b)\s*\)\s*", re.IGNORECASE)
# Marks: "[2]", "(2)", "(2 marks)", "2 marks".
MARKS_RE = re.compile(r"\[(\d{1,2})\]|\((\d{1,2})\s*marks?\)|\b(\d{1,2})\s*marks?\b", re.IGNORECASE)


@dataclass
class QuestionPart:
    id: str
    marks: int | None
    text: str
    diagrams: list[str] = field(default_factory=list)
    page: int = 0


@dataclass
class Question:
    number: str
    parts: list[QuestionPart] = field(default_factory=list)


def _marks(text: str) -> int | None:
    m = MARKS_RE.search(text)
    if not m:
        return None
    for g in m.groups():
        if g is not None:
            return int(g)
    return None


def split_questions(markdown: str) -> list[tuple[str, str]]:
    """Split markdown into (question_number, block_text) pairs."""
    lines = markdown.splitlines()
    blocks: list[tuple[str, list[str]]] = []
    current_num: str | None = None
    current_lines: list[str] = []
    for line in lines:
        m = QUESTION_RE.match(line)
        # Treat as a new question only for a short numeric token (avoid years etc.)
        if m and len(m.group(1)) <= 2 and not PART_RE.match(line):
            if current_num is not None:
                blocks.append((current_num, current_lines))
            current_num = m.group(1)
            current_lines = [line[m.end():].strip()]
        else:
            if current_num is not None:
                current_lines.append(line)
    if current_num is not None:
        blocks.append((current_num, current_lines))
    return [(num, "\n".join(ls).strip()) for num, ls in blocks]


def split_parts(question_number: str, block_text: str, page: int) -> list[QuestionPart]:
    """Split a question block into parts; a part-less question yields one part."""
    lines = block_text.splitlines()
    parts: list[tuple[str, list[str]]] = []
    current_label: str | None = None
    current_lines: list[str] = []
    for line in lines:
        m = PART_RE.match(line)
        if m:
            if current_label is not None:
                parts.append((current_label, current_lines))
            current_label = m.group(1).lower()
            current_lines = [line[m.end():].strip()]
        else:
            if current_label is None:
                current_label = ""  # preamble before first part label
            current_lines.append(line)
    if current_label is not None:
        parts.append((current_label, current_lines))

    # No explicit parts -> single part keyed by the question number.
    if len(parts) == 1 and parts[0][0] == "":
        text = "\n".join(parts[0][1]).strip()
        return [QuestionPart(id=question_number, marks=_marks(text), text=text, page=page)]

    out: list[QuestionPart] = []
    for label, ls in parts:
        text = "\n".join(ls).strip()
        pid = f"{question_number}({label})" if label else question_number
        out.append(QuestionPart(id=pid, marks=_marks(text), text=text, page=page))
    return out


def segment_page(markdown: str, page: int) -> list[QuestionPart]:
    """Segment one page's markdown into a flat list of question parts."""
    parts: list[QuestionPart] = []
    for number, block in split_questions(markdown):
        parts.extend(split_parts(number, block, page))
    return parts


def attach_diagrams(
    parts: list[QuestionPart],
    image_bboxes: list[tuple[float, float, float, float]],
    asset_paths: list[str],
    page_height: float,
) -> None:
    """Attach cropped diagram assets to question parts on the same page.

    Heuristic (refine with real docs): diagrams are sorted top-to-bottom and
    distributed across the page's parts by vertical position. With one part on
    the page, all diagrams attach to it.
    """
    if not parts or not asset_paths:
        return
    order = sorted(range(len(image_bboxes)), key=lambda i: image_bboxes[i][1])
    if len(parts) == 1:
        parts[0].diagrams.extend(asset_paths[i] for i in order)
        return
    n = len(parts)
    for i in order:
        y_mid = (image_bboxes[i][1] + image_bboxes[i][3]) / 2.0
        frac = min(max(y_mid / max(page_height, 1.0), 0.0), 0.999)
        parts[int(frac * n)].diagrams.append(asset_paths[i])
