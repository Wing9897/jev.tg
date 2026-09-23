"""Write a small original tray icon (PNG + Windows ICO). No third-party artwork."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"


def draw(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_ctx = ImageDraw.Draw(image)
    margin = max(1, size // 16)
    radius = max(2, size // 5)
    draw_ctx.rounded_rectangle(
        (margin, margin, size - margin - 1, size - margin - 1),
        radius=radius,
        fill=(15, 118, 110, 255),
    )
    left = size * 0.28
    right = size * 0.72
    top = size * 0.30
    gap = size * 0.16
    bar_h = max(2, size // 12)
    for index, width in enumerate((1.0, 0.68, 0.40)):
        y = top + index * gap
        inset = (right - left) * (1 - width) / 2
        draw_ctx.rounded_rectangle(
            (left + inset, y, right - inset, y + bar_h),
            radius=max(1, bar_h / 2),
            fill=(255, 255, 255, 255),
        )
    return image


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icon = draw(64)
    icon.save(OUT_DIR / "tray.png")
    icon.save(
        OUT_DIR / "tray.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)],
    )


if __name__ == "__main__":
    main()
