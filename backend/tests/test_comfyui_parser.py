"""comfyui_parser 单元测试（构造合成 PNG 与节点图）。"""
import json

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.parsers.comfyui_parser import (
    parse_bytes,
    parse_prompt_graph,
    extract_assets,
    extract_sampler_params,
    extract_prompt_lists,
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


def test_gguf_main_model_and_loras():
    """GGUF 主模型 + LoRA 链，主模型应回溯采样器链路命中 Unet 加载器。"""
    graph = {
        "331": {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": "z_image_turbo-Q4_K_M.gguf"},
        },
        "322": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["331", 0], "lora_name": "z-image/blur.safetensors"},
        },
        "323": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["322", 0], "lora_name": "faces.safetensors"},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {"model": ["323", 0], "positive": ["1", 0], "negative": ["2", 0]},
        },
    }
    assets = extract_assets(graph)
    assert assets["model_name"] == "z_image_turbo-Q4_K_M.gguf"
    assert assets["loras"] == ["z-image/blur.safetensors", "faces.safetensors"]


def test_extract_assets_ui_workflow_format():
    """UI workflow 图（nodes/links）也应能提取主模型与 LoRA。"""
    ui = {
        "nodes": [
            {
                "id": 331,
                "type": "UnetLoaderGGUF",
                "inputs": [],
                "widgets_values": ["z_image_turbo-Q4_K_M.gguf"],
            },
            {
                "id": 322,
                "type": "LoraLoaderModelOnly",
                "inputs": [
                    {"name": "model", "link": 1},
                ],
                "widgets_values": ["z-image/blur.safetensors", 1.0],
            },
            {
                "id": 3,
                "type": "KSampler",
                "inputs": [
                    {"name": "model", "link": 2},
                    {"name": "positive", "link": 3},
                    {"name": "negative", "link": 4},
                ],
            },
            {
                "id": 99,
                "type": "VAELoader",
                "inputs": [],
                "widgets_values": ["ae.safetensors"],
            },
        ],
        # [id, from_node, from_slot, to_node, to_slot, type]
        "links": [
            [1, 331, 0, 322, 0, "MODEL"],
            [2, 322, 0, 3, 0, "MODEL"],
        ],
    }
    assets = extract_assets(ui)
    assert assets["model_name"] == "z_image_turbo-Q4_K_M.gguf"
    assert assets["loras"] == ["z-image/blur.safetensors"]
    assert assets["vae"] == "ae.safetensors"


def test_extract_prompt_lists_api_multiple():
    """多个采样器/引导器应产出多条正负提示词。"""
    graph = {
        "3": {"class_type": "KSampler", "inputs": {"positive": ["5", 0], "negative": ["6", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat on the beach"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, worst quality, extra fingers"}},
        "103": {"class_type": "CFGGuider", "inputs": {"positive": ["105", 0], "negative": ["106", 0]}},
        "105": {"class_type": "CLIPTextEncode", "inputs": {"text": "cinematic lighting, detail"}},
        "106": {"class_type": "CLIPTextEncode", "inputs": {"text": "watermark, jpeg artifacts"}},
    }
    lists = extract_prompt_lists(graph)
    assert lists["positive"] == ["a cat on the beach", "cinematic lighting, detail"]
    assert lists["negative"] == ["blurry, worst quality, extra fingers", "watermark, jpeg artifacts"]


def test_extract_prompt_lists_ui_ignores_placeholders():
    """UI 图应只收集真实提示词，忽略 easy getNode 等占位节点标签。"""
    ui = {
        "nodes": [
            {"id": 1, "type": "CLIPTextEncode", "widgets_values": ["a serene lake, golden hour"]},
            {"id": 2, "type": "CLIPTextEncode", "widgets_values": ["blurry, worst quality"]},
            {"id": 3, "type": "easy getNode", "widgets_values": ["提示词"]},
            {"id": 4, "type": "CR Text", "widgets_values": ["a portrait of a girl"]},
        ],
        "links": [],
    }
    lists = extract_prompt_lists(ui)
    assert "提示词" not in lists["positive"]
    assert lists["positive"] == ["a serene lake, golden hour", "a portrait of a girl"]
    assert lists["negative"] == ["blurry, worst quality"]


def test_no_meta():
    assert "no comfyui meta" in parse_bytes(_plain()).error


def _plain() -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    return buf.getvalue()


def test_ui_prompt_follows_text_link_and_isolates_zeroout():
    """UI 图：CLIPTextEncode widget 为空但 text 经 Any Switch 连到 CR Text →
    取真实生效提示词；负向经 ConditioningZeroOut 不应泄漏正向文本。"""
    ui = {
        "nodes": [
            {"id": 7, "type": "CLIPTextEncode", "widgets_values": [""],
             "inputs": [{"name": "text", "link": 133}]},
            {"id": 13, "type": "ConditioningZeroOut",
             "inputs": [{"name": "conditioning", "link": 12}]},
            {"id": 55, "type": "KSampler",
             "inputs": [{"name": "positive", "link": 84}, {"name": "negative", "link": 85}]},
            {"id": 67, "type": "CR Text",
             "widgets_values": ["a serene lake at golden hour, cinematic lighting, ultra detailed"]},
            {"id": 79, "type": "Any Switch (rgthree)",
             "inputs": [{"name": "input1", "link": 131}]},
        ],
        "links": [
            [12, 7, 0, 13, 0, "CONDITIONING"],
            [84, 7, 0, 55, 0, "CONDITIONING"],
            [85, 13, 0, 55, 1, "CONDITIONING"],
            [131, 67, 0, 79, 0, "STRING"],
            [133, 79, 0, 7, 1, "STRING"],
        ],
    }
    lists = extract_prompt_lists(ui)
    assert lists["positive"] == ["a serene lake at golden hour, cinematic lighting, ultra detailed"]
    assert lists["negative"] == []


def test_ui_array_text_and_short_text_filtered():
    """easy showAnything 数组文本提取；短文本（≤10 字符）一律忽略。"""
    ui = {
        "nodes": [
            {"id": 1, "type": "CLIPTextEncode",
             "widgets_values": ["a portrait of a young woman in soft window light, film grain"]},
            {"id": 2, "type": "CLIPTextEncode", "widgets_values": ["blurry, lowres, bad hands"]},
            {"id": 3, "type": "easy showAnything",
             "widgets_values": [["cinematic cityscape at night, neon reflections",
                                 "close-up portrait of a man"]]},
            {"id": 4, "type": "CR Text", "widgets_values": ["short"]},
        ],
        "links": [],
    }
    lists = extract_prompt_lists(ui)
    assert "short" not in lists["positive"]  # 长度 ≤10 被忽略
    assert lists["positive"] == [
        "a portrait of a young woman in soft window light, film grain",
        "cinematic cityscape at night, neon reflections",
        "close-up portrait of a man",
    ]
    assert lists["negative"] == ["blurry, lowres, bad hands"]


def test_api_short_prompt_ignored():
    """API 图：长度 ≤10 的提示词候选被忽略。"""
    graph = {
        "3": {"class_type": "KSampler", "inputs": {"positive": ["5", 0], "negative": ["6", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "ok"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, lowres"}},
    }
    lists = extract_prompt_lists(graph)
    assert lists["positive"] == []
    assert lists["negative"] == ["blurry, lowres"]


def test_api_zeroout_not_leaked_to_negative():
    """API 图：负向经 ConditioningZeroOut 空 conditioning，不应泄漏正向文本。"""
    graph = {
        "3": {"class_type": "KSampler", "inputs": {"positive": ["5", 0], "negative": ["13", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "a detailed scene, sunlight, soft shadows"}},
        "13": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
    }
    lists = extract_prompt_lists(graph)
    assert lists["positive"] == ["a detailed scene, sunlight, soft shadows"]
    assert lists["negative"] == []