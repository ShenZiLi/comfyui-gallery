"""大模型服务（OpenAI 兼容）。

按「文本/视觉/Embedding」模型角色读取设置，提供统一的 chat 调用，
并封装「从工作流 JSON 分析用到的模型」这一业务能力。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from sqlmodel import Session, select

from ..database import engine
from ..models import Setting

logger = logging.getLogger(__name__)

ROLE_FIELDS = ("vendor", "base_url", "api_key", "model")


class LLMError(Exception):
    """大模型调用/业务失败。message 供前端展示。"""


class LLMNotConfigured(LLMError):
    """对应模型角色未配置。"""


def _setting(session: Session, key: str) -> str:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    return row.value if row else ""


def _role_config(session: Session, role: str) -> dict:
    return {f: _setting(session, f"llm_{role}_{f}") for f in ROLE_FIELDS}


def chat_text(prompt: str, session: Optional[Session] = None) -> str:
    """调用「文本」角色模型，返回回复文本。"""
    if session is None:
        with Session(engine) as s:
            return _chat(s, prompt)
    return _chat(session, prompt)


def _chat(session: Session, prompt: str) -> str:
    cfg = _role_config(session, "text")
    base = (cfg.get("base_url") or "").strip()
    key = (cfg.get("api_key") or "").strip()
    model = (cfg.get("model") or "").strip()
    if not (base and key and model):
        raise LLMNotConfigured("未配置文本大模型，请先在「设置-大模型」中配置")

    url = (
        base
        if base.rstrip("/").endswith("/chat/completions")
        else base.rstrip("/") + "/chat/completions"
    )
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    try:
        # 直连不信任系统代理，避免代理出口 IP 被厂商限流导致误报
        resp = httpx.post(url, headers=headers, json=payload, timeout=120, trust_env=False)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"大模型接口返回 {exc.response.status_code}: {exc.response.text[:200]}")
    except httpx.HTTPError as exc:
        raise LLMError(f"无法连接大模型: {exc}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError("大模型返回格式异常")


def _extract_json(content: str) -> dict:
    """从 LLM 回复中提取 JSON 对象（容忍 ``` 代码块与多余文本）。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("AI 未返回有效 JSON")
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"AI 返回 JSON 解析失败: {exc}")
    return obj if isinstance(obj, dict) else {}


def analyze_workflow(workflow_text: str, session: Session) -> dict:
    """让文本大模型完整解析工作流，返回结构化对象。

    返回结构：{workflow_id, models: {diffusion_models, text_encoders, vaes, loras, other},
    prompts: {positive, negative}, sampling, groups}
    主模型指实际渲染使用的 checkpoint/unet 模型；同时解析提示词。
    """
    prompt = _ANALYZE_PROMPT + "\n\n工作流 JSON：\n" + workflow_text
    content = chat_text(prompt, session)
    return _extract_json(content)


def chat_vision(image_data_b64: str, prompt: str, session: Optional[Session] = None) -> str:
    """调用「视觉」角色模型，传入 base64 图片做图文理解。"""
    if session is None:
        with Session(engine) as s:
            return _vi(s, image_data_b64, prompt)
    return _vi(session, image_data_b64, prompt)


def _vi(session: Session, image_data_b64: str, prompt: str) -> str:
    cfg = _role_config(session, "vision")
    base = (cfg.get("base_url") or "").strip()
    key = (cfg.get("api_key") or "").strip()
    model = (cfg.get("model") or "").strip()
    if not (base and key and model):
        raise LLMNotConfigured("未配置视觉大模型，请先在「设置-大模型」中配置")

    url = (
        base
        if base.rstrip("/").endswith("/chat/completions")
        else base.rstrip("/") + "/chat/completions"
    )
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    image_url = {"url": f"data:image/png;base64,{image_data_b64}"}
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": image_url},
                ],
            }
        ],
        "temperature": 0.6,
    }
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=180, trust_env=False)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"视觉模型接口返回 {exc.response.status_code}: {exc.response.text[:200]}")
    except httpx.HTTPError as exc:
        raise LLMError(f"无法连接视觉模型: {exc}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError("视觉模型返回格式异常")


def reverse_prompt_image(image_path, session: Session) -> str:
    """用视觉模型对图片反推提示词。"""
    import base64

    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    text = chat_vision(
        data,
        (
            "请仔细观察这张图片，用中文详细描述它的内容作为 AI 绘画提示词。"
            "需涵盖：主体、人物外貌与动作、服装、场景/背景、光线、影调、构图、镜头、画风、氛围、"
            "材质质感与摄影风格等。只输出提示词本身，不要前言与解释。"
        ),
        session,
    )
    return (text or "").strip()


def score_image(image_path, session: Session) -> dict:
    """用视觉模型给图片打分（0-100）并给理由。返回 {"score": int, "reason": str}。"""
    import base64

    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    text = chat_vision(
        data,
        (
            "你是一位专业的 AI 绘画图片评审。请从构图、光影、主体表现、细节完成度、整体美感与"
            "艺术性等维度打分，分数 0-100。只输出 JSON："
            '{"score": 82, "reason": "构图完整，光影层次丰富，主体突出，细节到位。"}'
        ),
        session,
    )
    obj = _extract_json(text)
    try:
        score = int(float(obj.get("score")))
    except (TypeError, ValueError):
        score = 0
    return {"score": max(0, min(100, score)), "reason": str(obj.get("reason") or "")}


_ANALYZE_PROMPT = """【角色】你是 ComfyUI 工作流解析器。用户会提供 ComfyUI 前端导出的 workflow JSON（含 nodes/links 数组），你的任务是从中提取全部模型资源、采样参数与提示词，**只输出 JSON，不输出任何解释文字**。

【模型节点识别规则】遍历 nodes，按 type 匹配：

| 类别 | 节点 type | 取文件字段 |
|---|---|---|
| 主模型 | UNETLoader / UnetLoaderGGUF / DiffusionModelLoader / CheckpointLoaderSimple / CheckpointLoaderAdvanced / UNETLoaderSVDQuant | widgets_values 第 0 项（文件路径） |
| 文本编码器 | CLIPLoader / CLIPLoaderGGUF / DualCLIPLoader / TripleCLIPLoader / CheckpointLoader* | 文件路径 + type 参数（如 flux2 / lumina2 / sd3） |
| VAE | VAELoader | 文件路径 |
| LoRA | LoraLoader / LoraLoaderModelOnly / LoraLoaderBlockWeight / 任意 type 含 "Lora" | 文件路径 + strength 强度值 |
| 其他模型 | 自定义 loader（如 SeedVR2LoadDiTModel / SeedVR2LoadVAEModel） | 文件路径，归入 other |
| 提示词 | CLIPTextEncode / 文本源节点（CR Text / easy setNode / Any Switch / ShowText 等） | text 字段或 widgets_values 文本项 |

【处理规则】
1. 文件字段优先取 widgets_values_named 中的文件名，其次取 widgets_values 数组首项；两者都无则记 null
2. 文件名含子目录时保留原路径（如 z-image\\Kook_Zimage_瑶光.safetensors）
3. mode=4（绕过）的节点照常提取，但 bypassed 置 true；mode=2（静音）正常提取
4. 同一文件多处加载 → 合并为一条，nodes 数组累积节点 id，LoRA 强度取首次出现值
5. 从文件名推断量化格式：Q4_K_M/Q5_K_M/Q8_0 → GGUF 量化；nvfp4 → NVFP4；fp8 → FP8；bf16/fp16 → 原精度；无法判断 → null
6. 采样参数：KSampler / SamplerCustomAdvanced / Flux2Scheduler / KSamplerSelect 中的 steps / cfg / sampler / scheduler / denoise / seed / 分辨率，归入 sampling 段
7. 提示词提取（新增）：
   a. 收集所有 CLIPTextEncode 节点及其文本；若其 text 输入来自上游字符串节点（CR Text / easy getNode / Any Switch / ShowText / LoadImage 反推等），沿 links 向上追溯直到找到文本源头，取最终字符串
   b. 正负判定：优先看链路——KSampler 的 positive(i1)/negative(i2) 输入、CFGGuider 的 positive(i1)/negative(i2) 输入；无法从链路判断时用启发式：含 "low quality / worst quality / artifacts / jpeg / watermark / extra fingers" 等负面特征词 → negative，否则 → positive
   c. 去重（去掉首尾空白与换行），按工作流出现顺序排列
8. 若输入不是合法 JSON 或解析失败，输出 {"error": "无法解析"}

【输出 JSON Schema】
{
  "workflow_id": "字符串或 null",
  "models": {
    "diffusion_models": [ { "file", "path", "quant", "params": {}} ],
    "text_encoders": [ 同结构，params 含 type ],
    "vaes": [ 同结构 ],
    "loras": [ 同结构，params 含 strength ],
    "other": [ 同结构 ]
  },
  "prompts": {
    "positive": [ "文本1", "文本2" ],
    "negative": [ "文本1" ]
  },
  "sampling": { "steps", "cfg", "sampler", "scheduler", "denoise", "seed", "width", "height" },
  "groups": [ "分组名列表" ]
}

【自校验】输出前检查：每个加载节点都被提取、无重复条目、strength/type 等参数未丢失、正负提示词未颠倒、每个 CLIPTextEncode 都有归属。宁缺毋滥，不确定的字段用 null。"""