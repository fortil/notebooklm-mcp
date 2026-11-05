"""Strip the "Gemini Notebook" badge from slide-deck PDFs after download.

NotebookLM slide decks are one full-page image per page plus a badge in the
bottom-right corner. This module re-renders every page with pypdfium2, covers
the badge with the local background color (median of the ring of pixels
around the box) and rebuilds the PDF at the same page size with Pillow. The
file is replaced in place, so callers keep the same path.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from statistics import median
from typing import Any, BinaryIO, cast

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

# Badge box as fractions of the page size, anchored at the bottom-right corner.
_RIGHT_INSET = 0.002
_BOTTOM_INSET = 0.005
_BOX_W = 0.105
_BOX_H = 0.042
_DPI = 150
_JPEG_QUALITY = 92


def _cover_badge(img: Image.Image) -> Image.Image:
    """Fill the badge box with the median color of the background ring around it."""
    w, h = img.size
    x1 = int(w * (1 - _RIGHT_INSET - _BOX_W))
    x2 = int(w * (1 - _RIGHT_INSET))
    y1 = int(h * (1 - _BOTTOM_INSET - _BOX_H))
    y2 = int(h * (1 - _BOTTOM_INSET))
    band = max(6, min(w, h) // 200)

    px = cast("Any", img.load())  # PIL's PixelAccess is not precisely typed
    ring: list[tuple[int, int, int]] = []
    for x in range(x1, x2, 2):  # band above the box
        for y in range(max(0, y1 - band), max(0, y1), 2):
            ring.append(px[x, y][:3])
    for y in range(y1, y2, 2):  # band left of the box
        for x in range(max(0, x1 - band), max(0, x1), 2):
            ring.append(px[x, y][:3])
    if not ring:
        return img
    fill = tuple(int(median(c[i] for c in ring)) for i in range(3))

    ImageDraw.Draw(img).rectangle([x1, y1, x2 - 1, y2 - 1], fill=fill)
    return img


def _save(pages: list[Image.Image], out: BinaryIO) -> None:
    pages[0].save(
        out,
        "PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=_DPI,
        quality=_JPEG_QUALITY,
    )


def strip_slide_deck_watermark(pdf_path: str | os.PathLike[str]) -> int:
    """Rewrite `pdf_path` with the badge covered on every page; return the new size in bytes.

    Raises if the file is not a readable PDF or rendering fails; the caller
    decides whether that is fatal.
    """
    src = Path(pdf_path)
    with pdfium.PdfDocument(str(src)) as doc:
        w_pts, h_pts = doc[0].get_size()
        pages: list[Image.Image] = []
        for page in doc:
            raster = page.render(scale=_DPI / 72).to_pil()
            if raster.mode != "RGB":
                raster = raster.convert("RGB")
            pages.append(_cover_badge(raster))

    fd, tmp_name = tempfile.mkstemp(
        dir=src.parent, prefix=f"{src.stem}-", suffix=".pdf"
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            _save(pages, fh)
        # Pillow derives the page size from the raster dpi; the round trip keeps
        # the original points (px / dpi * 72 == w_pts), but verify rather than trust.
        with pdfium.PdfDocument(tmp_name) as check:
            got_w, got_h = check[0].get_size()
        if abs(got_w - w_pts) > 1 or abs(got_h - h_pts) > 1:
            raise RuntimeError(
                f"page size changed during cleanup: {w_pts:.1f}x{h_pts:.1f} pts became "
                f"{got_w:.1f}x{got_h:.1f} pts"
            )
        os.replace(tmp_name, src)
    except BaseException:
        tmp = Path(tmp_name)
        if tmp.exists():
            tmp.unlink()
        raise
    return os.path.getsize(src)
