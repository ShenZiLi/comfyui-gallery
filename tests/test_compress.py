from io import BytesIO
from pathlib import Path

from PIL import Image

from artmirror.services.compress import to_jpg


def _make_png(path: Path, transparent: bool = False) -> None:
    img = Image.new("RGBA" if transparent else "RGB", (8, 8), (120, 90, 60))
    if transparent:
        # 左上 4x4 全透明，右下 4x4 不透明，用于验证透明→白底
        px = img.load()
        for y in range(4):
            for x in range(4):
                px[x, y] = (120, 90, 60, 0)
    img.save(path, "PNG")


def test_jpg_decode_and_size(tmp_path):
    p = tmp_path / "a.png"
    _make_png(p)
    data = to_jpg(p, quality=80)
    out = Image.open(BytesIO(data))
    assert out.format == "JPEG"
    assert out.size == (8, 8)
    assert len(data) > 0


def test_quality_affects_size(tmp_path):
    p = tmp_path / "q.png"
    _make_gradient(p)
    low = len(to_jpg(p, quality=30))
    high = len(to_jpg(p, quality=95))
    assert low < high


def test_transparent_becomes_white(tmp_path):
    p = tmp_path / "t.png"
    _make_png(p, transparent=True)
    data = to_jpg(p, quality=80)
    out = Image.open(BytesIO(data)).convert("RGB")
    # 左上角（原透明区）应接近白色，而非透明残留为黑
    px = out.getpixel((0, 0))
    assert px[0] >= 240 and px[1] >= 240 and px[2] >= 240


def _make_gradient(path: Path) -> None:
    small = Image.new("RGB", (4, 4))
    px = small.load()
    for y in range(4):
        for x in range(4):
            px[x, y] = (x * 70, y * 70, (x + y) * 35)
    img = small.resize((256, 256), Image.BILINEAR)
    img.save(str(path), "PNG", compress_level=0)