# HANDOFF — ocrqp: IGCSE/A-Level paper → per-question JSON pipeline

Last updated: after live validation of 8 datasets (5 markschemes + 3 question
papers) against real CIE PDFs via the GLM-OCR API.

## 1. What this project is

Turns CIE past-paper PDFs (question papers **and** mark schemes) into a JSON
dataset of **individual questions** — id, marks, text/LaTeX, cropped diagram
assets — so the user's downstream app can render each question as a card, let
the user pick some, and build a custom paper (`ocrqp/builder.py` already does
MD + self-contained HTML with embedded images + MathJax).

Core pipeline: PDF → render pages @200 DPI → glm-ocr `layout_parsing` (pass 1,
markdown + layout bboxes) → crop diagrams (PNG assets) → re-OCR table crops
@300 DPI (pass 2 rescue) → splice + segment into questions → per-question
JSON, LaTeX sanitized and validated by real KaTeX.

## 2. Environment / where things are

- Workspace: `/home/idrees/Downloads/workspace`; venv `.venv/` (Python 3.12).
  Run everything via `.venv/bin/python -m ocrqp ...`
- API key in `.env` (`ZAI_API_KEY`, gateway `api.z.ai`, model `glm-ocr`).
  Working as of the last live run.
- KaTeX validator installed: `tools/node_modules` (needs node).
- OCR cache `.ocrqp-cache/` — **re-runs of the same PDFs are free**; deleting
  it forces real API calls (~2–4 s/page).
- Samples: `samples/` (ms set), `samples_qp/` (real qps). Not a git repo yet.

## 3. What WORKS (validated live on real PDFs, this machine)

### Mark schemes — solved
| Paper | Questions | Marks (official) | KaTeX |
|---|---|---|---|
| 0580/41 IGCSE P4 (w25 ms) | 46 | 100/100 | 347/347, 0 fallbacks |
| 9709/22 Pure 2 (s26 ms) | 12 | 50/50 | 229/229 |
| 9709/42 Mechanics (s26 ms) | 14 | 50/50 | 475/475 |
| 9709/61 Prob&Stats (s26 ms) | 17 | 50/50 | 207/207 |
| 0580/42 IGCSE (s26 ms) | 39 | 100/100 | 287/287 |

- Rowspan-aware table parsing, "Available marks:" A-Level footer rows,
  multi-method ("Or…" rows) max-not-sum, IGCSE + A-Level header conventions.
- Equations inside markscheme tables come out as clean LaTeX — the original
  hard problem (see `SAMPLE_OUTPUT.md`).

### Question papers — mostly working
| Paper | Parts found | Marks |
|---|---|---|
| 9709/22 qp | 11 of 12 | every found part exactly matches the ms (46/50) |
| 9709/42 qp | 13 of 14 | PASS, all marks correct (47/50), 0 fallbacks |
| 0580/42 igcse qp | 35 | 87/100; 32/39 marks exactly match the ms |

- Diagrams: 16 real figure crops in `assets_qp/`, attached to the correct
  questions (Q3 log graph, Q8(a) geometry, Q19(b) stats chart …).
- Text-layer fallbacks recover what glm-ocr drops on digital PDFs (§5).
- Cover/blank pages yield no question parts.
- Custom paper builder (`ocrqp build --select PAPER:ID ...`) → MD + HTML;
  storage.to upload works (`ocrqp upload ... --collection`).
- Health report self-checks each dataset: `ocrqp report --json-dir ...`.
- 20 tests, all passing.

## 4. What DOESN'T work / known gaps

1. **Dropped content blocks (biggest gap).** glm-ocr sometimes drops a whole
   content block (9709/22 question 5(a) "Solve the inequality…" — a 4-marker;
   9709/42 3(b)). The text-layer marks band still records the missing marks,
   so the dataset total flags short (46/50, 47/50), but the question text
   itself is absent from the output.
2. **Marks band off-by-ones** on 0580/42: 17(a)=2 (should be 1), 8(a)=4
   (should be 3), 8(b)=3 (should be 4) — brackets near question-number
   y-positions land in the wrong part's band. Worst on IGCSE-style papers
   where parts sit closer together.
3. **Intermittent PNG 400s** from the gateway on pass-2 crops. Client
   auto-retries with JPEG and logs `[glm] PNG rejected …` to stderr — harmless
   but noisy; root cause unknown (payload size?).
4. **Scanned / photographed PDFs untested.** Everything validated is digital
   PDFs. The OpenCV table-detection fallback exists but never fired live, and
   the pdftext fallbacks do nothing for scans.
5. **Other exam boards / subjects untested** — only CIE maths (0580, 9709).
6. **Residual markup ugliness** — `$\operatorname{c o s e c}$`-style spaced
   words render fine but look odd; 0580/42 qp has 12 KaTeX fallbacks (wrapped

## 5. Architecture pointers

- `ocrqp/pdftext.py` — **digital-PDF text-layer fallbacks** (new, crucial):
  `question_numbers` / `inject_question_numbers` (prepend missing margin
  numbers before segmentation), `question_marks` (bands of `[N]` brackets per
  question by y-position), `apply_textlayer_marks` (positional fill after
  segmentation), `textlayer_page_text` (rebuild a page when OCR returned only
  header markers), `clean_junk` (drop `![](page=..)` lines + footers).
- `ocrqp/segment.py` — markscheme table parsing, prose qp segmentation,
  `merge_question_parts`, `is_stem_id`. Part ids: "6(b)"; stem: "6".
- `ocrqp/ocr.py` — orchestration; `carry_num` passes question numbers across
  continuation pages; empty-page fallback fires when pass-1 markdown has
  <20 real chars.
- `ocrqp/client.py` — glm client, PNG→JPEG retry, `normalize_response`,
  mock backend for offline tests.
- `ocrqp/latex.py` — repairs + strict KaTeX via `tools/katex_check.js`.
- `json_out.py` (dataset assembly, stem drop), `health.py` (self-check),
  `builder.py` (custom paper), `storage.py` (storage.to).
- Debug aids: `tools/inspect_cache.py`, `tools/probe_dpi.py`.

## 6. Commands cheat-sheet

```bash
cd /home/idrees/Downloads/workspace
.venv/bin/python -m pytest tests/ -q                  # 20 passing
.venv/bin/python -m ocrqp ocr samples_qp/0580_s26_qp_42.pdf --out out_qp --assets assets_qp
.venv/bin/python -m ocrqp report --json-dir out_qp
.venv/bin/python -m ocrqp build --json-dir out_qp --select 0580/42:8 --out x.md --html x.html
.venv/bin/python examples/demo_mock.py                # offline demo
PYTHONPATH=. .venv/bin/python tools/inspect_cache.py <pdf> <pages>
```

## 7. Next steps (priority order)

1. **Text-layer content rebuild** for dropped blocks (gap 1): when a question
   has band marks but no extracted text, rebuild the block from PDF words
   within its y-band. Test cases: 9709/22 5(a), 9709/42 3(b). Note scans have
   no text layer — gate on `page.get_text()` being non-empty.
2. **Band tolerance** (gap 2): anchor brackets to part-label y-positions
   instead of question-number bands. Test: 0580/42 17(a)=1, 8(a)=3, 8(b)=4.
3. Polish: collapse `\operatorname{c o s e c}` spaced-words; review
   0580/42's 12 fallbacks.
4. Test more subjects/series — 1,116 PDFs exist under
   `~/CAIE_PastPaperOpener/Past Papers/` (0580, 9709, plus physics/chem…).
   Watch for formula-sheet inserts (`_in_` files) and label conventions.
5. Test one scanned PDF (OpenCV fallback path).
6. `git init` + push — the workspace is NOT a git repo yet.

## 8. Validation notes

- Iterate on segmentation/pdftext heuristics **for free**: the OCR cache
  persists; only delete `out*/` and re-run `ocrqp ocr` (no new API calls).
- Regression pairs (parts found + per-part marks vs ms):
  - `out_qp/9709_s26_qp_22.json` ↔ `out/9709_s26_ms_22.json`
  - `out_qp/9709_s26_qp_42.json` ↔ `out/9709_s26_ms_42.json`
  - `out_qp/0580_s26_qp_42.json` ↔ `out_qp/0580_s26_ms_42.json`
- Don't change the JSON schema lightly — the downstream renderer expects
  `paper`, `kind`, `questions[]` with `id/marks/text/diagrams/page` (+
  `answer/working/notes` for ms).
- Editing hazard: backslashes/quotes in inline heredocs can get mangled by
  the remote-command layer. Prefer the file-editor tool or `python3 file.py`
  scripts, and `ast.parse` every edited `.py` before running.
   in `\text{}` — render, but not as math).
7. **Stem intro text is dropped when lettered parts exist** (by design, to
   avoid double-counting marks), but stems sometimes carry context the parts
   need ("The diagram shows…" before (a)/(b)).