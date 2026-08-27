"""ComfyUI 工作流 meta 解析器。

ComfyUI 在每张生成的 PNG 中写入两个文本 chunk：
- ``workflow``：UI 完整图 JSON（含节点坐标/连线，可拖回画布复现）
- ``prompt``：API 格式节点图 JSON（含 class_type / inputs）

chunk 内容通常为 base64 → latin-1 转码后的字符串，读取时需
``base64.b64decode(raw.encode('latin-1'))`` 再 ``json.loads``。
解析口径遵循设计文档 4.1 节：
正面/负面提示词按 KSampler 的正负 conditioning 连接关系区分；
模型 / LoRA / VAE 按节点 class_type 提取；参数从 KSampler 提取。
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from PIL import Image

logger = logging.getLogger(__name__)

POSITIVE_NODES = {
    "CLIPTextEncode",
    "CLIPTextEncodeSDXL",
    "CLIPTextEncodeControlNet",
}
LOADER_NODES = {"CheckpointLoaderSimple", "CheckpointLoader"}
NEGATIVE_LINK = 1  # conditioning 数组下标 1 为 negative


@dataclass
class ParseResult:
    """一次解析的结果。"""

    prompt_graph: Optional[dict] = None
    workflow: Optional[dict] = None
    prompt: str = ""
    negative_prompt: str = ""
    model_name: str = ""
    loras: list[str] = field(default_factory=list)
    vae: str = ""
    seed: Optional[int] = None
    steps: Optional[int] = None
    cfg: Optional[float] = None
    sampler: str = ""
    scheduler: str = ""
    denoise: Optional[float] = None
    width: int = 0
    height: int = 0
    error: str = ""


def _load_json(raw: str) -> Optional[Any]:
    """解析 PNG chunk 内容，兼容留底原始 JSON 与 base64-latin1 两种格式。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    # 1) 直接 JSON
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    # 2) ComfyUI 常用：base64 编码 JSON，按 latin-1 可逆存储
    try:
        return json.loads(base64.b64decode(raw.encode("latin-1")).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _text_of(node: dict) -> str:
    """取节点输入文本。"""
    value = node.get("inputs", {}).get("text", "")
    return value if isinstance(value, str) else str(value or "")


def _resolve(node_id: str, pin: Any, graph: dict) -> dict | None:
    """从连接引脚解析源节点。引脚形如 [node_id, output_index]。"""
    if not (isinstance(pin, list) and pin and isinstance(pin[0], str)):
        return None
    return graph.get(pin[0])


def _collect_ksamplers(graph: dict) -> list[dict]:
    """收集采样节点（含首尾空白键的兼容写法）。"""
    return [
        n
        for n in graph.values()
        if n.get("class_type", "").startswith("KSampler")
    ]


def parse_prompt_graph(graph: dict) -> tuple[str, str]:
    """从 API 图提取正面/负面提示词。

    :return: (prompt, negative_prompt)
    """
    if not isinstance(graph, dict):
        return "", ""

    nodes = graph
    prompt = negative = ""

    for n in _collect_ksamplers(nodes):
        inputs = n.get("inputs", {})
        pos_node = _resolve("", inputs.get("positive"), nodes)
        neg_node = _resolve("", inputs.get("negative"), nodes)
        # 兼容 KSamplerAdvanced: positive => 取 positive 输出
        if pos_node:
            prompt = _text_of(pos_node)
        if neg_node:
            negative = _text_of(neg_node)
        break  # 首个采样器为准

    # 回退：连接关系缺失时启发式归类
    if not prompt and not negative:
        texts = [
            (node_id, _text_of(n))
            for node_id, n in nodes.items()
            if n.get("class_type") in POSITIVE_NODES
        ]
        if texts:
            # 默认首条为正面；含 negative 关键字或补充负采样器名的归为负向
            pos_bucket: list[str] = []
            neg_bucket: list[str] = []
            for node_id, t in texts:
                if _looks_negative(node_id, t) and not neg_slot_unused(neg_bucket):
                    neg_bucket.append(t)
                else:
                    pos_bucket.append(t)
            prompt = _join(pos_bucket)
            negative = _join(neg_bucket)
    return prompt, negative


def _looks_negative(node_id: str, text: str) -> bool:
    """启发式判断该节点更可能承载负向提示词。"""
    low = (node_id or "").lower()
    if "negative" in low:
        return True
    # SDXL 负向提示通常较短，结合关键字
    markers = ("lowres", "worst", "extra", "poor", "blurry", "jpeg artifacts")
    return any(m in (text or "").lower() for m in markers)


def neg_slot_unused(bucket: list[str]) -> bool:
    """负向桶尚未占位（供启发式使用）。"""
    return len(bucket) < 1


def _join(bucket: list[str]) -> str:
    return ", ".join(x for x in bucket if x and x.strip())


def extract_assets(graph: dict) -> dict:
    """提取模型 / LoRA / VAE 名称。"""
    model = ""
    loras: list[str] = []
    vae = ""
    for n in graph.values():
        cls = n.get("class_type", "")
        inputs = n.get("inputs", {})
        if cls in LOADER_NODES:
            ck = inputs.get("ckpt_name") or inputs.get("unet_name") or inputs.get("model_name")
            if ck:
                model = str(ck)
            if not vae:
                v = inputs.get("vae_name")
                if v:
                    vae = str(v)
        elif cls == "LoraLoader" or cls == "LoraLoaderModelOnly":
            lora = inputs.get("lora_name")
            if lora:
                loras.append(str(lora))
        elif cls == "VAELoader":
            v = inputs.get("vae_name")
            if v:
                vae = str(v)
    return {
        "model_name": model,
        "loras": list(dict.fromkeys(loras)),
        "vae": vae,
    }


def extract_sampler_params(graph: dict) -> dict:
    """提取采样参数。"""
    for n in _collect_ksamplers(graph):
        i = n.get("inputs", {})
        return {
            "seed": _to_int(i.get("seed")),
            "steps": _to_int(i.get("steps")),
            "cfg": _to_float(i.get("cfg")),
            "sampler": str(i.get("sampler_name") or ""),
            "scheduler": str(i.get("scheduler") or ""),
            "denoise": _to_float(i.get("denoise")),
        }
    return {}


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_bytes(data: bytes) -> ParseResult:
    """解析 PNG 字节流中的 ComfyUI 工作流 meta。"""
    result = ParseResult()
    try:
        with Image.open(__import__("io").BytesIO(data)) as img:
            result.width, result.height = img.size
            chunks = getattr(img, "text", None) or {}
            if not chunks:
                # 较新 Pillow text() 为方法时兜底
                chunks = getattr(img, "info", {}) or {}
    except Exception as exc:  # noqa: BLE001
        result.error = f"open image failed: {exc}"
        return result

    workflow = _load_json(chunks.get("workflow", ""))
    prompt_graph = _load_json(chunks.get("prompt", ""))
    result.workflow = workflow if isinstance(workflow, dict) else None
    result.prompt_graph = prompt_graph if isinstance(prompt_graph, dict) else None

    if prompt_graph:
        result.prompt, result.negative_prompt = parse_prompt_graph(prompt_graph)
        result.__dict__.update(extract_assets(prompt_graph))
        result.__dict__.update(extract_sampler_params(prompt_graph))
    elif workflow:
        # 部分图像仅含 UI workflow，尽力解析文本节点
        texts = [
            n.get("widgets_values", [])
            for n in workflow.get("nodes", [])
            if n.get("type", "") in POSITIVE_NODES
        ]
        flat = [str(x) for t in texts for x in (t if isinstance(t, list) else [t])]
        result.prompt = ", ".join(flat) if flat else ""
        result.workflow = workflow
    else:
        result.error = "no comfyui meta found"
    return result