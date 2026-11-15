"""Image prep for Instagram (aspect ratio 4:5 .. 1.91:1) and recap collage."""

import io

from PIL import Image, ImageOps

MIN_RATIO, MAX_RATIO = 4 / 5, 1.91


def prepare_for_instagram(raw: bytes, max_side: int = 1440) -> bytes:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    w, h = img.size
    ratio = w / h
    if ratio < MIN_RATIO:  # too tall: center-crop height
        new_h = int(w / MIN_RATIO)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    elif ratio > MAX_RATIO:  # too wide: center-crop width
        new_w = int(h * MAX_RATIO)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def collage(paths: list[str], size: int = 1080) -> bytes:
    """Square grid collage of up to 9 photos."""
    paths = paths[:9]
    n = len(paths)
    cols = 1 if n == 1 else 2 if n <= 4 else 3
    rows = -(-n // cols)
    cell_w, cell_h = size // cols, size // rows
    canvas = Image.new("RGB", (size, size), (238, 64, 36))
    for i, p in enumerate(paths):
        tile = ImageOps.fit(Image.open(p).convert("RGB"), (cell_w - 6, cell_h - 6))
        canvas.paste(tile, ((i % cols) * cell_w + 3, (i // cols) * cell_h + 3))
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=90)
    return out.getvalue()
