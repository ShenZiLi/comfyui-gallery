"""系统设置与扫描路由。"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import settings as env_settings
from ..database import get_session
from ..models import Setting
from ..services import scanner

router = APIRouter(prefix="/api/settings", tags=["settings"])

# 三个模型角色及其扩展字段（支持不同厂商混搭）
ROLES = ["text", "vision", "embed"]
ROLE_FIELDS = ["vendor", "base_url", "api_key", "model"]


def _get(session: Session, key: str) -> str:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    return row.value if row else ""


def _set(session: Session, key: str, value: str) -> None:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def _role_config(session: Session, role: str) -> dict:
    """读取某个模型角色的配置。"""
    cfg = {}
    for f in ROLE_FIELDS:
        cfg[f] = _get(session, f"llm_{role}_{f}")
    return cfg


def _set_role_config(session: Session, role: str, cfg: dict) -> None:
    for f in ROLE_FIELDS:
        v = cfg.get(f)
        if v is not None:
            _set(session, f"llm_{role}_{f}", str(v).strip())


@router.get("")
def get_settings(session: Session = Depends(get_session)):
    """读取设置（多个扫描路径 + 各模型角色配置）。"""
    roots = [str(r) for r in scanner.get_scan_roots(session)]
    llm = {role: _role_config(session, role) for role in ROLES}
    return {"scanRoots": roots, "llm": llm}


@router.post("")
def update_settings(body: dict, session: Session = Depends(get_session)):
    """保存设置（含各角色模型厂商、扫描多个根），可触发扫描。"""
    llm = body.get("llm")
    if isinstance(llm, dict):
        for role in ROLES:
            _set_role_config(session, role, llm.get(role) or {})
    if body.get("scanRoots") is not None:
        scanner.save_scan_roots(session, [str(r) for r in body["scanRoots"]])
    session.commit()

    result = {"saved": True}
    if body.get("scan"):
        roots = scanner.get_scan_roots(session)
        invalid = [str(r) for r in roots if not Path(r).is_dir()]
        if not roots:
            raise HTTPException(400, "请先配置有效的图片目录")
        stats = scanner.scan_all(session, roots)
        result["scan"] = {
            "new": stats.new,
            "updated": stats.updated,
            "skipped": stats.skipped,
            "removed": stats.removed,
            "parsed": stats.parsed,
            "invalid": invalid,
            "errors": stats.errors,
        }
    if body.get("test"):
        # M3 才接真实 LLM，暂返回连通性占位
        result["test"] = {"ok": False, "message": "LLM 测试将在 AI 能力接入后可用"}
    return result