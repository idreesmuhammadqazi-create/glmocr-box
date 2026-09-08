"""ocrqp — IGCSE paper/markscheme PDF -> per-question JSON via GLM-OCR.

Pipeline
--------
PDF -> render pages (pass 1 @ page DPI) -> glm-ocr layout_parsing
    -> markdown + layout details (table/image bboxes)
    -> crop diagrams (image elements) -> PNG assets
    -> detect table regions -> re-render crops @ table DPI
    -> pass 2: glm-ocr each table crop -> clean LaTeX
    -> splice rescued tables over pass-1 tables
    -> segment into questions by number -> emit per-question JSON
"""

__version__ = "0.1.0"
