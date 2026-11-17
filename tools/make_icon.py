"""生成应用图标 assets/app.ico（Pillow 手绘，不依赖外部素材）"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
NAVY = (31, 78, 121, 255)
WHITE = (255, 255, 255, 255)
GREY = (185, 208, 230, 255)


def make(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=NAVY)

    # 三根递增柱：小尺寸下也能辨认
    base = int(size * 0.80)
    bar_w = int(size * 0.155)
    gap = int(size * 0.085)
    heights = [0.30, 0.46, 0.62]
    x = int((size - (bar_w * 3 + gap * 2)) / 2)
    for hh in heights:
        h = int(size * hh)
        d.rounded_rectangle([x, base - h, x + bar_w, base], radius=int(bar_w * 0.3), fill=WHITE)
        x += bar_w + gap
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [make(s) for s in sizes]
    out = ASSETS / "app.ico"
    imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes])
    imgs[-1].save(ASSETS / "app.png")
    print(f"图标已生成：{out}（{', '.join(str(s) for s in sizes)}）")
    print(f"预览图：{ASSETS / 'app.png'}")


if __name__ == "__main__":
    main()
