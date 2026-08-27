"""comfyui_parser 单元测试（构造合成 PNG 与节点图）。"""
import json

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.parsers.comfyui_parser import (
    parse_bytes,
    parse_prompt_graph,
    extract_assets,
    extract_sampler_params,
)

WORKFLOW_GRAPH = {
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "dreamshaper_8.safetensors"},
    },
    "5": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a cat on the beach, golden hour", "clip": ["4", 1]},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "blurry, lowres, deformed", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 12345,
            "steps": 28,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "positive": ["5", 0],
            "negative": ["6", 0],
        },
    },
}


def _encode(obj: dict) -> str:
    return json.dumps(obj)


def _make_png_base64() -> bytes:
    """构造嵌入 workflow/prompt 的 PNG。chunk 值以 base64→latin1 编码。"""
    import base64

    import io

    pnginfo = PngInfo()
    # 按 ComfyUI 存储方式：base64 编码 JSON 后按字节映射为 latin-1
    pnginfo.add_text("workflow", base64.b64encode(_encode(WORKFLOW_GRAPH).encode()).decode("latin-1"))
    pnginfo.add_text("prompt", base64.b64encode(_encode(WORKFLOW_GRAPH).encode()).decode("latin-1"))

    buf = io.BytesIO()
    Image.new("RGB", (512, 768), "white").save(buf, format="PNG", pnginfo=pnginfo)
    return buf.getvalue()


def test_decode_and_extract():
    result = parse_bytes(_make_png_base64())
    assert result.error == ""
    assert result.width == 512 and result.height == 768
    assert result.prompt == "a cat on the beach, golden hour"
    assert result.negative_prompt == "blurry, lowres, deformed"
    assert result.model_name == "dreamshaper_8.safetensors"
    assert result.steps == 28
    assert result.cfg == 7.0
    assert result.seed == 12345
    assert result.sampler == "euler"
    assert result.scheduler == "normal"


def test_extract_assets():
    assets = extract_assets(WORKFLOW_GRAPH)
    assert assets["model_name"] == "dreamshaper_8.safetensors"
    assert assets["loras"] == []
    assert assets["vae"] == ""


def test_prompt_graph_pos_neg():
    prompt, negative = parse_prompt_graph(WORKFLOW_GRAPH)
    assert prompt == "a cat on the beach, golden hour"
    assert negative == "blurry, lowres, deformed"


def test_sampler_params():
    params = extract_sampler_params(WORKFLOW_GRAPH)
    assert params["steps"] == 28
    assert params["cfg"] == 7.0
    assert params["scheduler"] == "normal"


def test_no_meta():
    assert "no comfyui meta" in parse_bytes(_plain()).error


def _plain() -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    return buf.getvalue()