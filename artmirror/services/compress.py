"""PNG 无损压缩（纯 Pillow，零新增依赖）。像素级无损，不改变格式。"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path


def compress_png(src: Path, keep_meta: bool) -> bytes:
    """读取 src PNG，无损重压并返回字节。

    keep_meta=True 时保留文本块（含 ComfyUI 内嵌的 workflow/prompt）；
    keep_meta=False 时剥离这些文本块使体积更小。
    """
    from PIL import Image, PngImagePlugin

    img = Image.open(src, "r")
    img.load()

    pnginfo = PngImagePlugin.PngInfo()
    if keep_meta:
        meta: dict = {}
        for k, v in (img.info or {}).items():
            if isinstance(v, str):
                meta.setdefault(k, v)
        if hasattr(img, "text") and img.text:
            meta.update(img.text)
        for k, v in meta.items():
            pnginfo.add_text(k, str(v))

    buf = BytesIO()
    img.save(buf, "PNG", optimize=True, compress_level=9, pnginfo=pnginfo)
    return buf.getvalue()