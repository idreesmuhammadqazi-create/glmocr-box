"""Layout helpers: table region detection and diagram bbox collection.

Primary source is the model's layout_details (element labels + bboxes).
When the model reports no table bboxes, fall back to geometric detection
(OpenCV ruled-line analysis) so scanned/ruled tables are still rescued.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .client import LayoutElement, OCRResult

BBox = tuple[float, float, float, float]


def table_bboxes(result: OCRResult) -> list[BBox]:
    return [el.bbox_2d for el in result.elements if el.is_table()]


def image_bboxes(result: OCRResult) -> list[BBox]:
    return [el.bbox_2d for el in result.elements if el.is_image()]


def _merge_overlapping(boxes: list[BBox], iou_thresh: float = 0.2) -> list[BBox]:
    def iou(a: BBox, b: BBox) -> float:
        x0, y0 = max(a[0], b[0]), max(a[1], b[1])
        x1, y1 = min(a[2], b[2]), min(a[3], b[3])
        inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    merged: list[BBox] = []
    for box in boxes:
        placed = False
        for i, m in enumerate(merged):
            if iou(box, m) > iou_thresh:
                merged[i] = (
                    min(m[0], box[0]),
                    min(m[1], box[1]),
                    max(m[2], box[2]),
                    max(m[3], box[3]),
                )
                placed = True
                break
        if not placed:
            merged.append(box)
    return merged


def detect_tables_opencv(
    image: Image.Image,
    min_area_ratio: float = 0.01,
) -> list[BBox]:
    """Fallback: detect ruled table regions via line morphology.

    Returns pixel bboxes in the given image's coordinate space.
    """
    arr = np.array(image.convert("L"))
    h, w = arr.shape
    # Binarize (dark lines/text -> 1)
    _, bw = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Horizontal and vertical line kernels
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w // 40), 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // 40))))
    grid = cv2.add(horiz, vert)

    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[BBox] = []
    min_area = min_area_ratio * w * h
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw * ch >= min_area and cw > w * 0.1 and ch > h * 0.02:
            boxes.append((float(x), float(y), float(x + cw), float(y + ch)))
    return _merge_overlapping(boxes)


def resolve_table_bboxes(result: OCRResult, page_image: Image.Image) -> list[BBox]:
    """Model bboxes if present, else OpenCV fallback."""
    boxes = table_bboxes(result)
    if boxes:
        return _merge_overlapping(boxes)
    return detect_tables_opencv(page_image)
