"""Digital-PDF text-layer fallbacks for gaps in OCR output.

glm-ocr drops isolated margin elements (question numbers, marks brackets)
and sometimes entire sparse pages (answer-space-only pages). For *digital*
PDFs the text layer still has all of it, so we patch before/after
segmentation:

  * question_numbers / inject_question_numbers - re-add missing numbers
  * question_marks / apply_textlayer_marks - re-add missing [N] marks
  * textlayer_page_text - rebuild a page when OCR dropped it entirely
  * clean_junk - drop placeholder/footer lines
"""
from __future__ import annotations

import re

NL = chr(10)

WORD_RE = re.compile(r"^\d{1,2}$")
MARKS_WORD_RE = re.compile(r"^\[(\d{1,2})\]$")
# OCR text that already starts with a question number (optionally dotted).
LEADING_NUM_RE = re.compile(r"^\s*(?:\[.*?\]\s*)?\(?\d{1,2}\b[.\s]?\)?")
# Cover / blank-page markers (never on question content pages).
FRONT_MATTER_RE = re.compile(r"CANDIDATE NAME|BLANK PAGE", re.IGNORECASE)
# glm-ocr image placeholder lines, optionally wrapped in $..$ by the sanitizer.
MARKER_LINE_RE = re.compile(
    r"^\$?\s*!\[\]\(page=\d+(?:,bbox=\[[^\]]*\])?\)\s*\$?$"
)
FOOTER_LINE_RE = re.compile(
    r"Cambridge University Press|\[Turn over\]|Licensed for hosting|Trace ID",
    re.IGNORECASE,
)
# Running header/footer words a text-layer rebuild must drop.
HEADER_FOOTER_WORD_RE = re.compile(
    r"CANDIDATE|CENTRE|Cambridge|University|Press|Assessment|Turn over"
    r"|Licensed|Trace|Downloaded|PapaCambridge|^[0-9]{1,3}$|9709/?",
    re.IGNORECASE,
)


def is_front_matter(markdown: str) -> bool:
    """Cover pages, blank pages and other front matter - no questions here."""
    return bool(FRONT_MATTER_RE.search(markdown))


def _page_words(page) -> list:
    try:
        return page.get_text("words")  # x0,y0,x1,y1,word,...
    except Exception:
        return []


def question_numbers(page) -> list[tuple[int, list[float]]]:
    """Question numbers on a page with their point bboxes.

    A CIE question number is a 1-2 digit word in the narrow left margin
    (first 12% of page width), not at the very bottom, rendered large enough
    to be a real number (not a footnote digit).
    """
    out: list[tuple[int, list[float]]] = []
    words = _page_words(page)
    if not words:
        return out
    try:
        pw, ph = page.rect.width, page.rect.height
    except Exception:
        return out
    for w in words:
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], (w[4] or "").strip()
        if not WORD_RE.match(text):
            continue
        if not (x0 < 0.12 * pw and y1 < 0.92 * ph):
            continue
        if (y1 - y0) < 6:  # footnote-size digits, not question numbers
            continue
        out.append((int(text), [x0, y0, x1, y1]))
    return out


def inject_question_numbers(markdown: str, numbers: list[tuple[int, list[float]]]) -> str:
    """Prepend the topmost missing question number to the markdown.

    Only fires when the OCR text does not already begin with a question
    number; pages where glm-ocr kept the number pass through unchanged, as
    do front matter and continuation pages.
    """
    if not numbers:
        return markdown
    stripped = markdown.lstrip()
    if not stripped:
        return markdown
    if is_front_matter(stripped):
        return markdown
    # Drop leading placeholder/footer lines FIRST so the already-numbered
    # check below sees the real content (else a page starting with a marker
    # gets double-numbered: "3. 3 The variables...").
    lines = stripped.splitlines()
    while lines and (
        MARKER_LINE_RE.match(lines[0].strip())
        or FOOTER_LINE_RE.search(lines[0])
        or not lines[0].strip()
    ):
        lines.pop(0)
    stripped = NL.join(lines).lstrip()
    if not stripped:
        return markdown
    if LEADING_NUM_RE.match(stripped):
        return markdown
    first = min(numbers, key=lambda t: t[1][1])  # topmost number
    return str(first[0]) + ". " + stripped


def question_marks(page) -> dict[int, list[int]]:
    """Marks brackets "[N]" per question number, in reading order.

    A question's marks sit vertically between its question number's
    y-position and the next question number's. Brackets often share the
    # first line with the question number (number.y1 == bracket.y1), so
    bands compare word TOPs, not bottoms.
    """
    nums = question_numbers(page)
    if not nums:
        return {}
    marks_words: list[tuple[int, float]] = []
    for w in _page_words(page):
        m = MARKS_WORD_RE.match((w[4] or "").strip())
        if m:
            marks_words.append((int(m.group(1)), float(w[1])))
    if not marks_words:
        return {}
    nums_sorted = sorted(nums, key=lambda t: t[1][1])
    out: dict[int, list[int]] = {}
    for idx, (n, bb) in enumerate(nums_sorted):
        y_start = bb[1]
        y_end = nums_sorted[idx + 1][1][1] if idx + 1 < len(nums_sorted) else float("inf")
        out[n] = [mk for mk, y in marks_words if y_start <= y < y_end]
    return out


def orphan_marks(page) -> list[int]:
    """Marks brackets on a page with no margin question numbers.

    Continuation pages (a question spilling over) carry part marks like
    "[3]" but no margin number, so the band logic has nothing to anchor to.
    """
    if question_numbers(page):
        return []
    out: list[int] = []
    for w in _page_words(page):
        m = MARKS_WORD_RE.match((w[4] or "").strip())
        if m:
            out.append(int(m.group(1)))
    return out


def apply_textlayer_marks(parts: list, marks_map: dict[int, list[int]]) -> None:
    """Fill missing part marks from the text-layer marks brackets.

    Brackets belong to lettered parts in reading order. When there are
    more brackets than unmarked lettered parts, the extra leading brackets
    belong to the question-level (stem) part, which then holds the total.
    """
    if not marks_map:
        return
    from collections import defaultdict

    groups = defaultdict(list)
    for p in parts:
        m = re.match(r"^(\d{1,2})", p.id or "")
        if m:
            groups[m.group(0)].append(p)
    for qnum, qs in groups.items():
        band = marks_map.get(int(qnum))
        if not band:
            continue
        lettered = [p for p in qs if re.search(r"\([a-z]\)$", p.id or "")]
        stems = [p for p in qs if p not in lettered]
        unmarked = [p for p in lettered if p.marks is None]
        # Single bracket + unmarked stem (no lettered parts): the stem itself
        # is the answerable question (e.g. plain "1 [4]").
        if not unmarked and len(band) == 1 and stems and stems[0].marks is None:
            stems[0].marks = band[0]
            continue
        if not unmarked:
            continue
        begin = max(len(band) - len(unmarked), 0)
        if len(band) - begin < len(unmarked):
            begin = 0
        it = iter(band[begin:])
        for p in unmarked:
            p.marks = next(it, None)


def textlayer_page_text(page, drop_dots: bool = True) -> str:
    """Reconstruct page text from the PDF text layer, top-to-bottom.

    Excludes running header/footer words and the dotted answer-space lines.
    Returns '' when nothing meaningful remains.
    """
    words = _page_words(page)
    if not words:
        return ""
    lines: dict[float, list] = {}
    for w in words:
        x0, y0, text = w[0], w[1], (w[4] or "")
        if not text.strip():
            continue
        if HEADER_FOOTER_WORD_RE.match(text.strip()):
            continue
        lines.setdefault(round(float(y0), 1), []).append((float(x0), text))
    out_lines = []
    for y in sorted(lines):
        joined = " ".join(t for _, t in sorted(lines[y])).strip()
        if not joined:
            continue
        if drop_dots and set(joined) <= {".", " "}:
            continue
        out_lines.append(joined)
    return NL.join(out_lines)


def clean_junk(markdown: str) -> str:
    """Drop glm-ocr placeholder marker lines and page-footer junk."""
    lines = markdown.splitlines()
    kept = [
        ln
        for ln in lines
        if not MARKER_LINE_RE.match(ln.strip()) and not FOOTER_LINE_RE.search(ln)
    ]
    return NL.join(kept)
