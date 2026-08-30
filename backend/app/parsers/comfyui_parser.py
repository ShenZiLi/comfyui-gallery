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

# 主模型加载节点的 class_type 全集，兼容各种格式（safetensors/gguf/flux/split unet)
MAIN_MODEL_LOADERS = {
    "CheckpointLoaderSimple", "CheckpointLoader",
    "UnetLoader", "UnetLoaderGGUF",
    "fluxUnetLoaderGGUF", "flux.1UnetLoaderGGUF",
    "UNETLoader",
    "DiTLoader", "DiTLoaderGGUF",
}

# LoRA 加载节点兼容不同变种
LORA_LOADERS = {
    "LoraLoader", "LoraLoaderModelOnly",
    "LoraLoaderBlockWeight",
}

NEGATIVE_LINK = 1  # conditioning 数组下标 1 为 negative

# 提示词最小长度：真实提示词通常为中文/英文且长度超过 10；
# 更短的文本（模型名、文件名、占位标签、参数值等）一律忽略，避免误判为提示词。
MIN_PROMPT_LEN = 10


def _is_prompt_text(t) -> bool:
    """是否为有效提示词候选：去除首尾空白后长度超过 MIN_PROMPT_LEN。"""
    return len(str(t or "").strip()) > MIN_PROMPT_LEN


@dataclass
class ParseResult:
    """一次解析的结果。"""

    prompt_graph: Optional[dict] = None
    workflow: Optional[dict] = None
    prompt: str = ""
    negative_prompt: str = ""
    positive_prompts: list[str] = field(default_factory=list)  # 原生多提示词（正）
    negative_prompts: list[str] = field(default_factory=list)  # 原生多提示词（负）
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
    """从 API 图提取正面/负面提示词（多提示词取交集，兼容旧调用）。

    :return: (prompt, negative_prompt) —— 各取列表拼接后的文本
    """
    lists = extract_prompt_lists(graph)
    return _join(lists["positive"]), _join(lists["negative"])


# 采样器（含正负 conditioning，或经 guider 提供）与引导器
SAMPLER_POS_NEG = {
    "KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced",
}
GUIDER_NODES = {"CFGGuider", "PerpNeg", "DualCFGGuider"}

# 可承载文本的源节点（文本可能来自其 inputs 或为传递节点）
TEXT_SOURCE_NODES = {
    "CLIPTextEncode", "CLIPTextEncodeSDXL", "CLIPTextEncodeControlNet",
    "PrimitiveNode", "StringPrimitive", "easy getNode", "easy setNode",
    "CR Text", "ShowText", "ShowText|pysssss",
}

# 可穿越的传递/开关节点：沿其输入连线继续回溯文本源。
# 注意：不能对所有节点都穿透（否则 ConditioningZeroOut / ControlNet 应用等会把
# conditioning 输入误当文本源，导致负向链路错取正向提示词）；Note/Label 等纯备注
# 装饰节点不参与，避免把说明文字当提示词。
PASSTHROUGH_NODES = {
    "Any Switch", "Any Switch (rgthree)",
    "easy getNode", "easy setNode", "easy anythingEverywhere",
    "Fast Bypasser (rgthree)", "Bypasser (rgthree)", "Fast Groups Bypasser (rgthree)",
}


def extract_prompt_lists(graph: dict) -> dict:
    """提取提示词列表 {positive: [...], negative: [...]}，兼容 API/UI 两种图。

    - 优先从各采样器/引导器的 positive/negative 引脚回溯到文本源；
    - 再补充未被命中的 CLIPTextEncode / CR Text 等文本节点（启发式正负判定）；
    - 去重、保持出现顺序。
    """
    if isinstance(graph, dict) and isinstance(graph.get("nodes"), list):
        return _extract_prompt_lists_ui(graph)

    positives: list[str] = []
    negatives: list[str] = []
    pos_seen = set()
    neg_seen = set()

    def add_pos(t: str):
        t = (t or "").strip()
        if t and _is_prompt_text(t) and t not in pos_seen:
            pos_seen.add(t)
            positives.append(t)

    def add_neg(t: str):
        t = (t or "").strip()
        if t and _is_prompt_text(t) and t not in neg_seen:
            neg_seen.add(t)
            negatives.append(t)

    if not isinstance(graph, dict):
        return {"positive": [], "negative": []}

    # 1) 采样器 / 引导器的正负 conditioning
    cond_nodes = [
        (int(nid) if str(nid).isdigit() else 0, nid, n)
        for nid, n in graph.items()
        if n.get("class_type", "") in SAMPLER_POS_NEG or n.get("class_type", "") in GUIDER_NODES
    ]
    cond_nodes.sort(key=lambda x: x[0])
    for _rank, nid, n in cond_nodes:
        inputs = n.get("inputs", {})
        if n.get("class_type", "") in SAMPLER_POS_NEG:
            add_pos(_resolve_text(inputs.get("positive"), graph))
            add_neg(_resolve_text(inputs.get("negative"), graph))
        elif n.get("class_type", "") in GUIDER_NODES:
            add_pos(_resolve_text(inputs.get("positive"), graph))
            add_neg(_resolve_text(inputs.get("negative"), graph))

    # 2) 补充未被命中的文本节点（启发式正负）
    extra = sorted(graph.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0)
    for nid, n in extra:
        cls = n.get("class_type", "")
        if cls not in TEXT_SOURCE_NODES:
            continue
        inputs = n.get("inputs", {})
        t = _resolve_text(inputs.get("text"), graph) if isinstance(inputs, dict) else ""
        t = (t or "").strip()
        if not t:
            continue
        if t in pos_seen or t in neg_seen:
            continue
        if _looks_negative(str(nid), t):
            add_neg(t)
        else:
            add_pos(t)

    return {"positive": positives, "negative": negatives}


def _resolve_text(val, graph: dict, depth: int = 0) -> str:
    """把 conditioning / text 引脚解析为最终文本（沿链路回溯）。"""
    if depth > 14:
        return ""
    if isinstance(val, str):
        return val.strip()
    if not (isinstance(val, list) and val and isinstance(val[0], str)):
        return ""
    node = graph.get(val[0])
    if not isinstance(node, dict):
        return ""
    return _node_text(node, graph, depth)


def _node_text(node: dict, graph: dict, depth: int) -> str:
    """从一个节点取最终文本；穿越文本源/传递节点/开关节点。"""
    inputs = node.get("inputs", {})
    if not isinstance(inputs, dict):
        return ""
    cls = node.get("class_type", "")

    if cls in TEXT_SOURCE_NODES:
        v = inputs.get("text")
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            r = _resolve_text(v, graph, depth + 1)
            if r:
                return r
        # 某些源节点用其它键存文本
        for key in ("string", "string_value", "text_value", "Constant"):
            k = inputs.get(key)
            if isinstance(k, str) and k.strip():
                return k.strip()
        return ""

    # 仅传递/开关节点沿输入引脚回溯；其余节点（如 ConditioningZeroOut、ControlNet
    # 应用）不穿透，避免负向链路误取正向文本
    if cls not in PASSTHROUGH_NODES:
        return ""
    for name, v in inputs.items():
        if isinstance(v, list) and v and isinstance(v[0], str):
            r = _resolve_text(v, graph, depth + 1)
            if r:
                return r
    return ""


# UI 图中真正承载提示词文本的节点类型（兜底启发式用；连接回溯优先于 widget 值）
UI_TEXT_NODES = {
    "CLIPTextEncode", "CLIPTextEncodeSDXL", "CLIPTextEncodeControlNet",
    "CR Text",
    "easy showAnything", "ShowText|pysssss",
}


def _ui_widget_texts(node: dict) -> list[str]:
    """取 UI 节点的提示词候选：widgets_values 首项为字符串或字符串数组。"""
    wv = node.get("widgets_values")
    if not isinstance(wv, list) or not wv:
        return []
    first = wv[0]
    if isinstance(first, str):
        return [first.strip()]
    if isinstance(first, list):
        return [str(x).strip() for x in first if isinstance(x, str) and x.strip()]
    return []


def _extract_prompt_lists_ui(graph: dict) -> dict:
    """UI workflow 图（nodes/links）提取提示词列表（去重保序 + 长度过滤 + 启发式正负）。

    - 主路径：从采样器/引导器的 positive/negative 连线，沿 conditioning 源节点再经
      text 输入连线回溯 STRING 源（穿越 Any Switch / easy getNode 等），取真实生效的提示词；
    - 兜底：未命中的 CLIPTextEncode / CR Text / easy showAnything 等文本节点的 widget 值
      （含数组），启发式判定正负。
    """
    positives: list[str] = []
    negatives: list[str] = []
    pos_seen = set()
    neg_seen = set()

    def add_pos(t: str):
        t = (t or "").strip()
        if t and _is_prompt_text(t) and t not in pos_seen:
            pos_seen.add(t)
            positives.append(t)

    def add_neg(t: str):
        t = (t or "").strip()
        if t and _is_prompt_text(t) and t not in neg_seen:
            neg_seen.add(t)
            negatives.append(t)

    nodes = graph.get("nodes") or []
    links = graph.get("links") or []
    # links: [id, from_node, from_slot, to_node, to_slot, type]
    link_from = {
        int(ln[0]): ln[1]
        for ln in links
        if isinstance(ln, list) and len(ln) >= 2
    }
    by_id: dict = {}
    for n in nodes:
        if isinstance(n, dict):
            by_id[str(n.get("id", ""))] = n

    # 1) 主路径：采样器 / 引导器的正负 conditioning 链路回溯
    for n in nodes:
        ntype = n.get("type", "")
        if ntype not in SAMPLER_POS_NEG and ntype not in GUIDER_NODES:
            continue
        add_pos(_ui_trace_text(n, "positive", by_id, link_from))
        add_neg(_ui_trace_text(n, "negative", by_id, link_from))

    # 2) 兜底：未命中的文本节点（widget 值，含数组），启发式正负
    ordered = sorted(
        (n for n in nodes if isinstance(n, dict) and n.get("type", "") in UI_TEXT_NODES),
        key=lambda n: int(n.get("id", 0) or 0),
    )
    for n in ordered:
        for t in _ui_widget_texts(n):
            if t in pos_seen or t in neg_seen:
                continue
            if _looks_negative(str(n.get("id", 0)), t):
                add_neg(t)
            else:
                add_pos(t)

    return {"positive": positives, "negative": negatives}


def _ui_trace_text(node: dict, input_name: str, by_id: dict, link_from: dict, depth: int = 0) -> str:
    """从 UI 节点的某输入连线回溯文本源（返回首个有效提示词文本）。"""
    if depth > 14:
        return ""
    for inp in node.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        if inp.get("name") != input_name or inp.get("link") is None:
            continue
        src_id = link_from.get(int(inp["link"]))
        if src_id is None:
            return ""
        return _ui_node_text(by_id.get(str(src_id)), by_id, link_from, depth)
    return ""


def _ui_node_text(node, by_id: dict, link_from: dict, depth: int = 0) -> str:
    """UI 图节点文本：文本源优先 text 输入连线，其次 widget 值；传递节点沿首个可解析输入回溯。"""
    if not node or depth > 14:
        return ""
    ntype = node.get("type", "")
    inputs = node.get("inputs") or []

    # 文本源节点：若 text 输入被连线接管（如 CR Text → Any Switch → CLIPTextEncode.text），
    # 沿连线取真正生效的文本；否则取 widget 值
    if ntype in UI_TEXT_NODES:
        for inp in inputs:
            if not isinstance(inp, dict):
                continue
            if inp.get("name") in ("text", "string", "text_value") and inp.get("link") is not None:
                src_id = link_from.get(int(inp["link"]))
                if src_id is not None:
                    r = _ui_node_text(by_id.get(str(src_id)), by_id, link_from, depth + 1)
                    if r:
                        return r
        for t in _ui_widget_texts(node):
            if t:
                return t
        return ""

    # 传递 / 开关节点（Any Switch、easy getNode 等）沿输入回溯；其余节点（如
    # ConditioningZeroOut、ControlNet 应用）不穿透，避免负向链路误取正向文本
    if ntype not in PASSTHROUGH_NODES:
        return ""
    for inp in inputs:
        if not isinstance(inp, dict) or inp.get("link") is None:
            continue
        src_id = link_from.get(int(inp["link"]))
        if src_id is None:
            continue
        r = _ui_node_text(by_id.get(str(src_id)), by_id, link_from, depth + 1)
        if r:
            return r
    return ""


def _looks_negative(node_id: str, text: str) -> bool:
    """启发式判断该节点/文本更可能承载负向提示词。"""
    low = (node_id or "").lower()
    if "negative" in low:
        return True
    markers = ("lowres", "worst", "extra fingers", "extra legs", "missing fingers",
               "bad anatomy", "bad hands", "blurry", "jpeg artifacts", "watermark",
               "poorly drawn", "deformed", "out of frame", "artifacts")
    return any(m in (text or "").lower() for m in markers)


def _join(bucket: list[str]) -> str:
    return "\n".join(x for x in bucket if x and x.strip())


def _model_input(node: dict) -> str:
    """取主模型加载节点的模型名输入键值（兼容各加载器命名；UI 图 inputs 为数组）。"""
    inputs = node.get("inputs", {})
    if not isinstance(inputs, dict):
        return ""
    for key in ("ckpt_name", "unet_name", "model_name", "loader_name"):
        val = inputs.get(key)
        if val:
            return str(val)
    return ""


def _widget_val(node: dict, idx: int) -> str:
    wv = node.get("widgets_values")
    if isinstance(wv, list) and idx < len(wv):
        v = wv[idx]
        if isinstance(v, str):
            return v
    return ""


def _cls(node: dict) -> str:
    return str(node.get("class_type", "") or node.get("type", ""))


def _model_src_node_id(node: dict, is_ui: bool, link_from: Optional[dict]) -> str:
    """取某节点 model 输入的来源节点 id（兼容 UI/API 两种格式）。"""
    if is_ui:
        for inp in node.get("inputs") or []:
            if isinstance(inp, dict) and inp.get("name") == "model":
                lid = inp.get("link")
                if lid is not None and link_from:
                    return str(link_from.get(int(lid), ""))
        return ""
    pin = node.get("inputs", {}).get("model")
    if isinstance(pin, str):
        return pin
    if isinstance(pin, list) and pin and isinstance(pin[0], str):
        return pin[0]
    return ""


def _trace_model(sampler: dict, is_ui: bool, id_map: dict, link_from: Optional[dict]) -> str:
    """沿 model 输入链回溯到主模型加载器节点。"""
    cur = _model_src_node_id(sampler, is_ui, link_from)
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        node = id_map.get(cur)
        if not node:
            break
        if _cls(node) in MAIN_MODEL_LOADERS:
            return _model_input(node) or _widget_val(node, 0)
        cur = _model_src_node_id(node, is_ui, link_from)
    return ""


def extract_assets(graph: dict) -> dict:
    """提取主模型 / LoRA / VAE 名称。

    兼容两种 ComfyUI 构图格式：
    - UI workflow 图：``{"nodes": [...], "links": [...]}``，连线在 links 数组；
    - API prompt 图：``{node_id: {"class_type", "inputs"}}``，连线在内联 pin。

    主模型优先取「连通到主采样器 model 输入的加载器」，从而在多阶段
    （文生图→细节增强→超分）工作流里精准命中真正的主渲染模型；
    LoRA 采集工作流内全部 LoRA 变种。
    """
    is_ui = isinstance(graph, dict) and isinstance(graph.get("nodes"), list)
    if is_ui:
        pairs = [
            (str(n.get("id", "")), n)
            for n in graph["nodes"]
            if isinstance(n, dict)
        ]
        link_from: Optional[dict] = {}
        for ln in graph.get("links") or []:
            if isinstance(ln, list) and len(ln) >= 6:
                link_from[int(ln[0])] = ln[1]
    else:
        pairs = list(graph.items())
        link_from = None
    id_map = {nid: n for nid, n in pairs}

    loader_names: list[str] = []
    loras: list[str] = []
    vae = ""

    for _nid, n in pairs:
        cls = _cls(n)
        if cls in MAIN_MODEL_LOADERS:
            name = _model_input(n) or _widget_val(n, 0)
            if name:
                loader_names.append(str(name))
        elif cls in LORA_LOADERS:
            lora = n.get("inputs", {}).get("lora_name") if not is_ui else None
            lora = lora or _widget_val(n, 0)
            if lora:
                loras.append(str(lora))
        elif cls == "VAELoader":
            val = _widget_val(n, 0)
            if not val and not is_ui:
                val = str(n.get("inputs", {}).get("vae_name") or "")
            vae = val or vae

    # 主模型：优先走主采样器链路；找不到再回退首个加载器
    model = ""
    for prefix in ("KSampler", "SamplerCustom"):
        if model:
            break
        for _nid, n in pairs:
            if _cls(n).startswith(prefix):
                model = _trace_model(n, is_ui, id_map, link_from)
                if model:
                    break
    if not model and loader_names:
        model = loader_names[0]

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
        plist = extract_prompt_lists(prompt_graph)
        result.positive_prompts = plist["positive"]
        result.negative_prompts = plist["negative"]
        result.prompt = _join(plist["positive"])
        result.negative_prompt = _join(plist["negative"])
        result.__dict__.update(extract_assets(prompt_graph))
        result.__dict__.update(extract_sampler_params(prompt_graph))
    elif workflow:
        # 部分图像仅含 UI workflow，尽力解析文本与模型/LoRA
        result.__dict__.update(extract_assets(workflow))
        plist = extract_prompt_lists(workflow)
        result.positive_prompts = plist["positive"]
        result.negative_prompts = plist["negative"]
        result.prompt = _join(plist["positive"])
        result.negative_prompt = _join(plist["negative"])
        result.workflow = workflow
    else:
        result.error = "no comfyui meta found"
    return result