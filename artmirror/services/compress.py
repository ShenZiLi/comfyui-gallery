"""JPG 有损压缩（纯 Pillow，零新增依赖）。统一输出 .jpg。"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image


def _to_rgb_white(img: Image.Image) -> Image.Image:
    """转 RGB；含透明通道时合成到白底（透明区域→白色）。"""
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (
        img.mode == "P" and "transparency" in img.info
    )
    if has_alpha:
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


def to_jpg(src: Path, quality: int = 80) -> bytes:
    """读取 src 图片，转为 JPG（有损）并返回字节。src 需为可被 Pillow 读取的图片。"""
    img = Image.open(src, "r")
    img.load()
    flat = _to_rgb_white(img)
    buf = BytesIO()
    flat.save(buf, "JPEG", quality=int(quality))
    return buf.getvalue()