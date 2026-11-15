"""Make printable ArUco markers for the places in app/vision/places.py (issue #55).

    cd server && uv run python -m app.vision.print_markers            # 15 cm, 300 dpi
    uv run python -m app.vision.print_markers --size-cm 20 --out /tmp/markers

Writes server/markers/ (git-ignored):
    <id>-<place>.png   one US Letter page per place, 300 dpi, marker centered, name below across the page
    markers.pdf        all pages in one file, for printing

HOW TO PRINT: print at 100% / "actual size" (turn OFF "fit to page"), then measure the
black square with a ruler. It should be 15.0 cm (or --size-cm). If it isn't, pass the
measured size to MarkerDetector(marker_size_m=...) or distances will be off by the same
ratio. Keep the white margin around the square: the detector needs it. Matte paper avoids
glare; tape it flat (curled paper bends the square) at about camera height (~40 cm).
A 15 cm marker reads from ~5 m with the iPhone 1x camera; print bigger for farther.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import cv2
import numpy as np

from app.vision import places as places_mod
from app.vision.markers import DEFAULT_DICTIONARY

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "markers"  # server/markers
PAGE_IN = (8.5, 11.0)  # US Letter, inches
CM_PER_IN = 2.54


def marker_page(
    marker_id: int,
    label: str,
    size_cm: float = 15.0,
    dpi: int = 300,
    dictionary: str = DEFAULT_DICTIONARY,
) -> np.ndarray:
    """One grayscale Letter page: the marker (black square exactly size_cm), its name below as wide as
    the page, then the small print."""
    aruco_dict = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
    cells = aruco_dict.markerSize + 2  # data bits plus the 1-cell black border
    cell_px = max(1, round(size_cm / CM_PER_IN * dpi / cells))
    side = cells * cell_px  # whole pixels per cell: crisp edges (within half a cell of size_cm)
    marker = cv2.aruco.generateImageMarker(aruco_dict, marker_id, side, borderBits=1)

    page_w, page_h = round(PAGE_IN[0] * dpi), round(PAGE_IN[1] * dpi)
    if side > page_w - dpi // 2:
        raise ValueError(f"a {size_cm} cm marker doesn't fit on a Letter page with margins")
    page = np.full((page_h, page_w), 255, np.uint8)
    x0, y0 = (page_w - side) // 2, round(0.6 * dpi)
    page[y0 : y0 + side, x0 : x0 + side] = marker

    # The place name, as wide as the page allows (readable across the room), then the small print.
    margin = round(0.4 * dpi)
    y = y0 + side + round(0.5 * dpi)  # a white gap at least half a cell wide around the marker
    y = _draw_label(page, label.upper(), (margin, y, page_w - margin, y + round(2.4 * dpi))) + round(0.3 * dpi)
    real_cm = side / dpi * CM_PER_IN
    small = [
        f"marker id {marker_id} ({dictionary})",
        f"Print at 100% (no 'fit to page'). Black square = {real_cm:.1f} cm.",
        "Measure it; if different, set marker_size_m to the measured size.",
    ]
    for text in small:
        scale, thickness = 1.0 * dpi / 300, max(1, round(2 * dpi / 300))
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        cv2.putText(page, text, ((page_w - tw) // 2, y + th), cv2.FONT_HERSHEY_SIMPLEX, scale, 0, thickness, cv2.LINE_AA)
        y += th + round(0.15 * dpi)
    return page


# Bold fonts to try for the place name (macOS, then common Linux); OpenCV's own font otherwise.
BOLD_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _draw_label(page: np.ndarray, text: str, box: tuple[int, int, int, int]) -> int:
    """Draw text in black, centered, as large as fits in box (x0, y0, x1, y1): full width unless the
    box's height runs out first (a very short name). Returns the y just below the drawn text."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    try:
        from PIL import Image, ImageDraw, ImageFont

        path = next(p for p in BOLD_FONTS if Path(p).exists())
        probe = ImageFont.truetype(path, 100)
        l, t, r, b = probe.getbbox(text)
        size = int(100 * min(w / (r - l), h / (b - t)))
        font = ImageFont.truetype(path, size)
        l, t, r, b = font.getbbox(text)
        img = Image.fromarray(page)
        ImageDraw.Draw(img).text((x0 + (w - (r - l)) // 2 - l, y0 - t), text, font=font, fill=0)
        page[:] = np.asarray(img)
        return y0 + (b - t)
    except (ImportError, StopIteration, OSError):
        thickness = max(1, h // 25)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, thickness)
        scale = min(w / tw, h / th)
        thickness = max(1, round(thickness * scale))
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        cv2.putText(page, text, (x0 + (w - tw) // 2, y0 + th), cv2.FONT_HERSHEY_SIMPLEX, scale, 0, thickness, cv2.LINE_AA)
        return y0 + th


def write_markers(
    out_dir: Path = DEFAULT_OUT,
    size_cm: float = 15.0,
    dpi: int = 300,
    dictionary: str = DEFAULT_DICTIONARY,
    mapping: dict[str, int] | None = None,
) -> list[Path]:
    """Write one PNG per place plus markers.pdf (if Pillow is available). Returns the files written."""
    mapping = places_mod.places() if mapping is None else mapping
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    pages = []
    for name, marker_id in sorted(mapping.items(), key=lambda kv: kv[1]):
        page = marker_page(marker_id, name, size_cm, dpi, dictionary)
        path = out_dir / f"{marker_id}-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}.png"
        try:
            from PIL import Image  # Pillow comes with ultralytics; it stores the DPI in the file

            img = Image.fromarray(page)
            img.save(path, dpi=(dpi, dpi))
            pages.append(img)
        except ImportError:
            cv2.imwrite(str(path), page)
        written.append(path)
    if pages:
        pdf = out_dir / "markers.pdf"
        pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=float(dpi))
        written.append(pdf)
    return written


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Make printable ArUco markers for the robot's places.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (default server/markers)")
    ap.add_argument("--size-cm", type=float, default=15.0, help="side of the black square (default 15)")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--dictionary", default=DEFAULT_DICTIONARY)
    args = ap.parse_args(argv)
    for path in write_markers(args.out, args.size_cm, args.dpi, args.dictionary):
        print(path)
    print(
        f"Print at 100% (no 'fit to page'); the black square should measure {args.size_cm:g} cm."
        " Tape each one flat at the place it names, about camera height."
    )


if __name__ == "__main__":
    main()
