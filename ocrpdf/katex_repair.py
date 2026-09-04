import asyncio
import json
import logging
import os
from pathlib import Path

from .mathmd import iter_math_segments

log = logging.getLogger("ocrpdf")

CHECK_JS = Path(__file__).resolve().parent.parent / "tools" / "katex_check.js"


def _find_node_modules() -> Path | None:
    env = os.environ.get("KATEX_NODE_MODULES")
    candidates = [
        Path(env) if env else None,
        Path.cwd() / "node_modules",
        Path.cwd() / ".katex-check" / "node_modules",
        CHECK_JS.parent.parent / ".katex-check" / "node_modules",
    ]
    for c in candidates:
        if c and (c / "katex").is_dir():
            return c.parent
    return None


class KatexRepairer:
    def __init__(self):
        self.disabled_reason = None
        self.node_modules = _find_node_modules()
        if self.node_modules is None:
            self.disabled_reason = "katex not installed (npm install katex, or set KATEX_NODE_MODULES)"
        elif not CHECK_JS.exists():
            self.disabled_reason = f"{CHECK_JS} missing"

    @property
    def available(self) -> bool:
        return self.disabled_reason is None

    async def _check_batch(self, items: list[dict]) -> list[str | None]:
        proc = await asyncio.create_subprocess_exec(
            "node", str(CHECK_JS),
            cwd=str(self.node_modules),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(json.dumps(items).encode()), timeout=180
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("katex_check.js timed out")
        if proc.returncode != 0:
            raise RuntimeError(f"katex_check.js failed: {err.decode()[:300]}")
        data = json.loads(out.decode())
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"katex_check.js: {data['error']}")
        return data

    def _candidates(self, tex: str) -> list[str]:
        cands: list[str] = []

        def add(t: str):
            if t and t not in cands:
                cands.append(t)

        stack: list[int] = []
        unmatched = set()
        for i, ch in enumerate(tex):
            if ch == "{":
                stack.append(i)
            elif ch == "}":
                if stack:
                    stack.pop()
                else:
                    unmatched.add(i)
        base = "".join(ch for i, ch in enumerate(tex) if i not in unmatched)
        add(base)
        bases = [base, base + "}", base + "}}"]
        for b in bases:
            add(b)
        for b in bases:
            anchors = [i for i, ch in enumerate(b) if ch in "{}"]
            for pos in reversed(anchors):
                add(b[:pos] + "}" + b[pos:])
        return cands[:80]

    async def repair_markdown(self, md: str) -> tuple[str, dict]:
        stats = {"checked": 0, "repaired": 0, "failed": 0}
        if not self.available:
            log.warning("KaTeX repair disabled: %s", self.disabled_reason)
            return md, stats

        segments = list(iter_math_segments(md))
        if not segments:
            return md, stats

        errors = await self._check_batch(
            [{"tex": inner, "display": display} for _, _, inner, display in segments]
        )
        stats["checked"] = len(segments)

        fixes = []
        candidates: list[dict] = []
        cand_groups: list[list[str]] = []
        for (start, end, inner, display), err in zip(segments, errors):
            if err is None:
                continue
            fixes.append((start, end, inner, display, err))
            cands = self._candidates(inner)
            cand_groups.append(cands)
            candidates.extend({"tex": c, "display": display} for c in cands)

        if not fixes:
            return md, stats

        cand_errors = await self._check_batch(candidates)
        chosen: dict[int, str] = {}
        idx = 0
        for fi, cands in enumerate(cand_groups):
            for c, e in zip(cands, cand_errors[idx:idx + len(cands)]):
                if e is None:
                    chosen[fi] = c
                    break
            idx += len(cands)

        result = []
        last = 0
        for fi, (start, end, inner, display, err) in enumerate(fixes):
            result.append(md[last:start])
            fixed = chosen.get(fi)
            if fixed is not None:
                stats["repaired"] += 1
                delim = "$$" if display else "$"
                result.append(delim + fixed + delim)
            else:
                stats["failed"] += 1
                log.error("unrepairable math segment: %r (%s)", inner[:80], err[:120])
                result.append(md[start:end])
            last = end
        result.append(md[last:])
        final = "".join(result)

        remaining = list(iter_math_segments(final))
        recheck = await self._check_batch(
            [{"tex": inner, "display": d} for _, _, inner, d in remaining]
        )
        stats["failed"] = sum(1 for e in recheck if e is not None)
        return final, stats

    async def verify_markdown(self, md: str) -> list[tuple[str, str]]:
        if not self.available:
            raise RuntimeError(self.disabled_reason)
        segments = list(iter_math_segments(md))
        errors = await self._check_batch(
            [{"tex": inner, "display": display} for _, _, inner, display in segments]
        )
        return [(inner, e) for (_, _, inner, _), e in zip(segments, errors) if e is not None]
