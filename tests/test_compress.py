from io import BytesIO
from pathlib import Path

from PIL import Image, PngImagePlugin

from artmirror.services.compress import compress_png


def _make_png(path: Path, with_meta: bool = True) -> None:
    img = Image.new("RGB", (8, 8), (120, 90, 60))
    info = PngImagePlugin.PngInfo()
    info.add_text("Software", "test")
    if with_meta:
        info.add_text("workflow", '{"nodes":[]}')
    img.save(path, "PNG", pnginfo=info)


def test_lossless_pixels(tmp_path):
    p = tmp_path / "a.png"
    _make_png(p)
    data = compress_png(p, keep_meta=True)
    out = Image.open(BytesIO(data))
    ref = Image.open(p)
    assert list(out.getdata()) == list(ref.getdata())


def test_keeps_meta_when_requested(tmp_path):
    p = tmp_path / "m.png"
    _make_png(p)
    data = compress_png(p, keep_meta=True)
    assert "workflow" in Image.open(BytesIO(data)).info


def test_strips_meta_when_not_requested(tmp_path):
    p = tmp_path / "m.png"
    _make_png(p)
    data = compress_png(p, keep_meta=False)
    assert "workflow" not in Image.open(BytesIO(data)).info