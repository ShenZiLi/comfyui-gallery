"""系统设置与扫描路由。"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import settings as env_settings
from ..database import get_session
from ..models import Setting
from ..services import scanner

router = APIRouter(prefix="/api/settings", tags=["settings"])

LLM_KEYS = ["llm_base_url", "llm_api_key", "llm_vision_model", "llm_text_model", "llm_embed_model"]


def _get(session: Session, key: str) -> str:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    return row.value if row else ""


def _set(session: Session, key: str, value: str) -> None:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


@router.get("")
def get_settings(session: Session = Depends(get_session)):
    """读取设置（扫描路径 + LLM 配置）。"""
    scan_root = _get(session, "scan_root") or env_settings.scan_root or ""
    llm = {
        "baseUrl": _get(session, "llm_base_url") or env_settings.llm_base_url,
        "apiKey": _get(session, "llm_api_key") or env_settings.llm_api_key,
        "visionModel": _get(session, "llm_vision_model") or env_settings.llm_vision_model,
        "textModel": _get(session, "llm_text_model") or env_settings.llm_text_model,
        "embedModel": _get(session, "llm_embed_model") or env_settings.llm_embed_model,
    }
    return {"scanRoot": scan_root, "llm": llm}


class SettingsBody:
    """接收设置更新。"""

    def __init__(
        self,
        scanRoot: str | None = None,
        llm_base_url: str | None = None,
        llm_api_key: str | None = None,
        llm_vision_model: str | None = None,
        llm_text_model: str | None = None,
        llm_embed_model: str | None = None,
        save: bool = False,
        scan: bool = False,
        test: bool = False,
    ) -> None:
        self.scanRoot = scanRoot
        self.llm_base_url = llm_base_url
        self.llm_api_key = llm_api_key
        self.llm_vision_model = llm_vision_model
        self.llm_text_model = llm_text_model
        self.llm_embed_model = llm_embed_model
        self.save = save
        self.scan = scan
        self.test = test


@router.post("")
def update_settings(body: dict, session: Session = Depends(get_session)):
    """保存设置并可触发扫描。"""
    for key in LLM_KEYS:
        if body.get(key) is not None:
            _set(session, key, str(body[key]).strip())
    if body.get("scanRoot") is not None:
        _set(session, "scan_root", str(body["scanRoot"]).strip())
    session.commit()

    result = {"saved": True}
    if body.get("scan"):
        root = _get(session, "scan_root") or env_settings.scan_root
        if not root or not Path(root).is_dir():
            raise HTTPException(400, "请先配置有效的扫描目录")
        stats = scanner.scan(session, Path(root))
        result["scan"] = {
            "new": stats.new,
            "updated": stats.updated,
            "skipped": stats.skipped,
            "removed": stats.removed,
            "parsed": stats.parsed,
            "errors": stats.errors,
        }
    if body.get("test"):
        # M3 才接真实 LLM，暂返回连通性占位
        result["test"] = {"ok": False, "message": "LLM 测试将在 AI 能力接入后可用"}
    return result