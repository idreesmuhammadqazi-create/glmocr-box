"""Segment page markdown into per-question records.

Two routes:
  * Marking schemes  -> the page is one big ``<table>`` with columns
    ``Question | Answer | Marks | Partial Marks``. Questions span multiple rows
    via ``rowspan`` (worked solutions), and the Marks column holds mark-types
    (``M1``/``M2``/``A1``/``B2``) or a plain total. We parse the table with a
    rowspan-aware grid expander and group rows per question.
  * Question papers  -> prose with ``1 (a) ... (b) ...`` numbering; regex-based
    segmentation (heuristic, tune against real output).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# --- prose segmentation regexes (question papers) -------------------------- #
QUESTION_RE = re.compile(r"^\s*(?:Q(?:uestion)?\s*)?(\d{1,2})\b[\s.)]*", re.IGNORECASE)
PART_RE = re.compile(r"^\s*\(?([a-z]|\b(?:i{1,3}|iv|v)\b)\s*\)\s*", re.IGNORECASE)
MARKS_RE = re.compile(
    r"\[(\d{1,2})\]|\((\d{1,2})\s*marks?\)|\b(\d{1,2})\s*marks?\b", re.IGNORECASE
)
TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
NUM_RE = re.compile(r"\d+")
# a row whose Answer starts with Or/Either/Alternative begins a new method
METHOD_START_RE = re.compile(r"^\s*(?:or|either|alternative|alternatively|method\b)", re.IGNORECASE)


@dataclass
class QuestionPart:
    id: str
    marks: int | None
    text: str
    diagrams: list[str] = field(default_factory=list)
    page: int = 0
    answer: str = ""
    working: str = ""
    notes: str = ""


# --------------------------------------------------------------------------- #
# Rowspan-aware HTML table parsing (marking schemes)
# --------------------------------------------------------------------------- #
class _Cell:
    __slots__ = ("text", "rowspan", "colspan")

    def __init__(self, text: str, rowspan: int = 1, colspan: int = 1):
        self.text, self.rowspan, self.colspan = text, rowspan, colspan


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_Cell]] = []
        self._row: list[_Cell] | None = None
        self._span = (1, 1)
        self._buf: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            a = dict(attrs)
            try:
                self._span = (int(a.get("rowspan", 1)), int(a.get("colspan", 1)))
            except ValueError:
                self._span = (1, 1)
            self._buf = []
        elif tag == "br" and self._buf is not None:
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._buf is not None:
            if self._row is not None:
                self._row.append(_Cell("".join(self._buf).strip(), *self._span))
            self._buf = None

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)


def _expand_grid(rows: list[list[_Cell]]) -> list[list[str]]:
    """Expand rowspan/colspan into a fully-aligned 2D grid of strings."""
    ncols = max((sum(c.colspan for c in r) for r in rows), default=0)
    grid: list[list[str]] = []
    carry: dict[int, list] = {}  # col -> [rows_left, text]
    for row in rows:
        # A row that carries its own question cell (full width) starts a new
        # question -- clear any stale rowspan carry left by an overcounted
        # rowspan on a previous question (a common glm-ocr off-by-one).
        if sum(c.colspan for c in row) >= ncols:
            carry.clear()
        line: list[str] = []
        col = 0
        cells = iter(row)
        while col < ncols:
            if col in carry and carry[col][0] > 0:
                line.append(carry[col][1])
                carry[col][0] -= 1
                col += 1
                continue
            cell = next(cells, None)
            if cell is None:
                line.append("")
                col += 1
                continue
            line.append(cell.text)
            if cell.rowspan > 1:
                carry[col] = [cell.rowspan - 1, cell.text]
            for _ in range(cell.colspan - 1):
                col += 1
                line.append("")
            col += 1
        grid.append(line)
    return grid


def parse_html_table(table_html: str) -> list[list[str]]:
    p = _TableParser()
    p.feed(table_html)
    return _expand_grid(p.rows)


def extract_tables(markdown: str) -> list[tuple[str, tuple[int, int]]]:
    return [(m.group(0), m.span()) for m in TABLE_RE.finditer(markdown)]


def is_markscheme_table(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    header = [c.lower() for c in rows[0]]
    return any("question" in c for c in header) and any("answer" in c for c in header)


def _col_index(header: list[str], *names: str) -> int | None:
    for name in names:
        for i, h in enumerate(header):
            if name in h:
                return i
    return None


def _parse_marks(cell: str) -> int:
    """'M1'->1, 'B2'->2, '3'->3, ''->0 (sum all numbers found)."""
    return sum(int(m) for m in NUM_RE.findall(cell))


AVAIL_ROW_RE = re.compile(r"^\s*available marks\b", re.IGNORECASE)


def _avail_total(answer_cell: str, marks_cell: str) -> int | None:
    """Total from an 'Available marks' footer row.

    Handles both forms:
      * one cell:  "Available marks: 3"
      * split:    answer cell "Available marks:", marks cell "3"
    """
    m = re.search(r"available marks?\s*[:=]?\s*(\d+)", answer_cell, re.IGNORECASE)
    if m:
        return int(m.group(1))
    digits = NUM_RE.findall(marks_cell)
    if digits:
        return int(digits[-1])
    return None


def parts_from_markscheme_table(rows: list[list[str]], page: int) -> list[QuestionPart]:
    if not rows:
        return []
    header = [c.lower() for c in rows[0]]
    qi = _col_index(header, "question")
    ai = _col_index(header, "answer")
    mi = _col_index(header, "marks", "mark")
    pi = _col_index(header, "partial", "guidance")

    def cell(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    # Group consecutive rows by question id (rowspan already expanded).
    groups: list[tuple[str, list[list[str]]]] = []
    for row in rows[1:]:
        qid = cell(row, qi)
        if not qid:
            continue
        if groups and groups[-1][0] == qid:
            groups[-1][1].append(row)
        else:
            groups.append((qid, [row]))

    parts: list[QuestionPart] = []
    for qid, grows in groups:
        # Content rows only. 'Available marks' footer rows carry the question
        # TOTAL (A-Level style) — never content, and they override any summed
        # mark-type total.
        avail_total: int | None = None
        content_rows: list[list[str]] = []
        for r in grows:
            a = cell(r, ai)
            if AVAIL_ROW_RE.match(a):
                t = _avail_total(a, cell(r, mi))
                if t is not None:
                    avail_total = t
                continue
            if a:
                content_rows.append(r)
        # Old style: a trailing row with empty answer + plain-integer marks
        # is the question TOTAL (not an extra mark-type).
        total_rows = [r for r in grows
                      if not cell(r, ai) and not AVAIL_ROW_RE.match(cell(r, ai))
                      and cell(r, mi).isdigit()]
        if avail_total is not None:
            marks: int | None = avail_total
        elif total_rows:
            marks = int(cell(total_rows[-1], mi))
        else:
            # A question may list several alternative methods, each worth the
            # same marks. Split at "Or"/"Either" boundaries and take the max
            # method total (never the sum across methods).
            methods: list[list[list[str]]] = [[]]
            for r in content_rows:
                if METHOD_START_RE.match(cell(r, ai)) and methods[-1]:
                    methods.append([])
                methods[-1].append(r)
            method_sums = [sum(_parse_marks(cell(r, mi)) for r in m) for m in methods]
            mmax = max(method_sums) if method_sums else 0
            marks = mmax if mmax > 0 else None
        answers = [cell(r, ai) for r in content_rows]
        notes = [cell(r, pi) for r in grows if cell(r, pi)]
        working = "\n".join(answers)
        answer = answers[-1] if answers else ""
        parts.append(
            QuestionPart(
                id=qid,
                marks=marks,
                text=working,
                page=page,
                answer=answer,
                working=working,
                notes="\n".join(notes),
            )
        )
    return parts


# --------------------------------------------------------------------------- #
# Prose segmentation (question papers)
# --------------------------------------------------------------------------- #
def _marks(text: str) -> int | None:
    m = MARKS_RE.search(text)
    if not m:
        return None
    for g in m.groups():
        if g is not None:
            return int(g)
    return None


def split_questions(markdown: str) -> list[tuple[str, str]]:
    lines = markdown.splitlines()
    blocks: list[tuple[str, list[str]]] = []
    current_num: str | None = None
    current_lines: list[str] = []
    for line in lines:
        m = QUESTION_RE.match(line)
        if m and len(m.group(1)) <= 2 and not PART_RE.match(line):
            if current_num is not None:
                blocks.append((current_num, current_lines))
            current_num = m.group(1)
            current_lines = [line[m.end():].strip()]
        elif current_num is not None:
            current_lines.append(line)
    if current_num is not None:
        blocks.append((current_num, current_lines))
    return [(num, "\n".join(ls).strip()) for num, ls in blocks]


def split_parts(question_number: str, block_text: str, page: int) -> list[QuestionPart]:
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
                current_label = ""
            current_lines.append(line)
    if current_label is not None:
        parts.append((current_label, current_lines))

    if len(parts) == 1 and parts[0][0] == "":
        text = "\n".join(parts[0][1]).strip()
        return [QuestionPart(id=question_number, marks=_marks(text), text=text, page=page)]

    out: list[QuestionPart] = []
    for label, ls in parts:
        text = "\n".join(ls).strip()
        pid = f"{question_number}({label})" if label else question_number
        out.append(QuestionPart(id=pid, marks=_marks(text), text=text, page=page))
    return out


def segment_prose(markdown: str, page: int) -> list[QuestionPart]:
    parts: list[QuestionPart] = []
    for number, block in split_questions(markdown):
        parts.extend(split_parts(number, block, page))
    return parts


# --------------------------------------------------------------------------- #
# Combined page segmentation
# --------------------------------------------------------------------------- #
def segment_page(markdown: str, page: int) -> list[QuestionPart]:
    """Markscheme tables are parsed as rows; remaining prose is segmented.

    Front matter (cover pages, blank pages) yields no question parts.
    """
    from .pdftext import is_front_matter

    if is_front_matter(markdown):
        return []
    parts: list[QuestionPart] = []
    ms_spans: list[tuple[int, int]] = []
    for table_html, span in extract_tables(markdown):
        rows = parse_html_table(table_html)
        if is_markscheme_table(rows):
            parts.extend(parts_from_markscheme_table(rows, page))
            ms_spans.append(span)

    # Prose-segment whatever is left (markscheme tables removed).
    prose = markdown
    for s, e in sorted(ms_spans, reverse=True):
        prose = prose[:s] + "\n" + prose[e:]
    parts.extend(segment_prose(prose, page))
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


def is_stem_id(qid: str) -> bool:
    """True for a bare question id ("8") with no lettered part ("8(a)")."""
    return bool(re.match(r"^\d{1,2}$", qid or ""))

AVAIL_RE = re.compile(r"available marks\s*[:=]?\s*(\d+)", re.IGNORECASE)


def merge_question_parts(parts: list[QuestionPart]) -> list[QuestionPart]:
    """Merge parts that share a question id (a question spanning page breaks,


    - text: longest non-empty (qp prose wins over fragments)
    - working/notes: concatenated across pages
    - answer: last non-empty answer
    - marks: explicit 'Available marks: N' total if present, else the max
      (never the sum -- alternative methods each carry a full scheme)
    """
    order: list[str] = []
    groups: dict[str, list[QuestionPart]] = {}
    for p in parts:
        if p.id not in groups:
            groups[p.id] = []
            order.append(p.id)
        groups[p.id].append(p)

    merged: list[QuestionPart] = []
    for qid in order:
        gs = groups[qid]
        if len(gs) == 1:
            merged.append(gs[0])
            continue
        texts = [g.text for g in gs if g.text.strip()]
        workings = [g.working for g in gs if g.working]
        notes = [g.notes for g in gs if g.notes]
        answers = [g.answer for g in gs if g.answer]
        diagrams = [d for g in gs for d in g.diagrams]
        total = None
        for g in gs:
            for txt in (g.answer, g.text, g.notes):
                m = AVAIL_RE.search(txt or "")
                if m:
                    total = int(m.group(1))
        mark_vals = [g.marks for g in gs if g.marks is not None]
        marks = total if total is not None else (max(mark_vals) if mark_vals else None)
        main_text = max(texts, key=len) if texts else "\n".join(workings)
        merged.append(
            QuestionPart(
                id=qid,
                marks=marks,
                text=main_text,
                diagrams=diagrams,
                page=gs[0].page,
                answer=answers[-1] if answers else "",
                working="\n".join(workings),
                notes="\n".join(notes),
            )
        )
    return merged
