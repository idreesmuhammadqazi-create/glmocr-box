import re
from typing import List, Optional, Tuple

SENTINEL = "<!--TABLE-->"

_PIPE_LINE = re.compile(r"^\s*\|")
_HTML_TABLE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n|\n?```\s*$")


def strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```[a-zA-Z]*\s*\n([\s\S]*?)\n?```\s*$", text)
    if m:
        return m.group(1).strip()
    return text


def find_table_block(text: str) -> Optional[Tuple[int, int]]:
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if _PIPE_LINE.match(line):
            if start is None:
                start = i
        elif start is not None:
            return _span(lines, start, i - 1)
    if start is not None:
        return _span(lines, start, len(lines) - 1)
    m = _HTML_TABLE.search(text)
    if m:
        return m.start(), m.end()
    return None


def _span(lines: List[str], first: int, last: int) -> Tuple[int, int]:
    start = sum(len(l) + 1 for l in lines[:first])
    end = start + sum(len(l) + 1 for l in lines[first:last + 1]) - 1
    return start, end


def splice_tables(page_md: str, rescued: List[str]) -> Tuple[str, int]:
    if not rescued:
        return page_md, 0

    replaced = 0
    segments = page_md.split(SENTINEL)
    if len(segments) > 1:
        out = [segments[0]]
        for i, seg in enumerate(segments[1:]):
            if i < len(rescued):
                span = find_table_block(seg)
                if span:
                    seg = seg[:span[0]] + rescued[i] + seg[span[1]:]
                else:
                    seg = "\n" + rescued[i] + "\n" + seg
                replaced += 1
            out.append(seg)
        result = SENTINEL.join(out)
        if len(rescued) > len(segments) - 1:
            extra = rescued[len(segments) - 1:]
            result += "\n\n<!-- rescued tables beyond pass-1 markers -->\n\n" + "\n\n".join(extra)
            replaced += len(extra)
        return result, replaced

    spans = list(_HTML_TABLE.finditer(page_md))
    blocks = [(m.start(), m.end()) for m in spans]
    pipe_blocks = _all_pipe_blocks(page_md)
    if not blocks:
        blocks = pipe_blocks

    if len(blocks) == len(rescued):
        for (start, end), table in sorted(zip(blocks, rescued), reverse=True):
            page_md = page_md[:start] + table + page_md[end:]
            replaced += 1
        return page_md, replaced

    result = page_md + "\n\n<!-- rescued tables (position uncertain) -->\n\n" + "\n\n".join(rescued)
    return result, 0


def _all_pipe_blocks(text: str) -> List[Tuple[int, int]]:
    lines = text.split("\n")
    blocks = []
    start = None
    for i, line in enumerate(lines):
        if _PIPE_LINE.match(line):
            if start is None:
                start = i
        else:
            if start is not None:
                blocks.append(_span(lines, start, i - 1))
                start = None
    if start is not None:
        blocks.append(_span(lines, start, len(lines) - 1))
    return blocks
