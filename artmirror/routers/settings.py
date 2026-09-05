"""系统设置与扫描路由。"""
import errno
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from ..config import settings as env_settings
from ..database import get_engine, get_session
from ..models import Setting
from ..services import scanner, watcher

router = APIRouter(prefix="/api/settings", tags=["settings"])

# 三个模型角色及其扩展字段（支持不同厂商混搭）
ROLES = ["text", "vision", "embed"]
ROLE_FIELDS = ["vendor", "base_url", "api_key", "model"]
# 已知厂商类型；每个角色可为每个厂商保留独立配置
VENDORS = ["deepseek", "qwen", "glm", "openai", "custom"]


def _vkey(role: str, vendor: str, field: str) -> str:
    return f"llm_{role}_{vendor}_{field}"


def _get(session: Session, key: str) -> str:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    return row.value if row else ""


def _set(session: Session, key: str, value: str) -> None:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def _compress_quality(session: Session) -> int:
    """读取 JPG 压缩质量（1–100，默认 80）。"""
    raw = _get(session, "compress_quality")
    try:
        q = int(raw or 80)
    except (TypeError, ValueError):
        q = 80
    return max(1, min(100, q))


# 支持的主题值；非法值归一化为 light
THEMES = ("light", "dark", "claude", "spacex")


def _normalize_theme(value) -> str:
    t = str(value or "light").strip().lower()
    return t if t in THEMES else "light"


def _compress_quality_from(value) -> int:
    """把前端传来的质量值归一化到 1–100，非法时用默认 80。"""
    try:
        q = int(value)
    except (TypeError, ValueError):
        q = 80
    return max(1, min(100, q))


def _role_config(session: Session, role: str) -> dict:
    """读取某个模型角色的配置。"""
    cfg = {}
    for f in ROLE_FIELDS:
        cfg[f] = _get(session, f"llm_{role}_{f}")
    return cfg


def _set_role_config(session: Session, role: str, cfg: dict) -> None:
    # 保存当前生效配置，并额外落一份到所属厂商名下（供切换厂商时回读）
    vendor = str(cfg.get("vendor") or "").strip()
    for f in ROLE_FIELDS:
        v = cfg.get(f)
        if v is not None:
            val = str(v).strip()
            _set(session, f"llm_{role}_{f}", val)
            if vendor in VENDORS:
                _set(session, _vkey(role, vendor, f), val)


def _role_vendor_config(session: Session, role: str, vendor: str) -> dict:
    """读取某个角色在某一厂商下已保存的配置。"""
    return {f: _get(session, _vkey(role, vendor, f)) for f in ROLE_FIELDS}


def _background_scan(root: str) -> None:
    """后台扫描单个根目录（独立会话），有变动则递增同步版本号。"""
    try:
        with Session(get_engine()) as session:
            stats = scanner.scan(session, Path(root))
            if stats.new or stats.updated or stats.removed:
                watcher.bump()
    except Exception:  # noqa: BLE001
        pass


@router.post("/roots")
def add_scan_root(
    body: dict,
    session: Session = Depends(get_session),
    bg: BackgroundTasks = BackgroundTasks(),
):
    """注册一个图片目录（仅登记引用路径），随后后台扫描入库，接口立即返回。"""
    path = (body.get("path") or "").strip()
    if not path:
        raise HTTPException(400, "缺少目录路径")
    root = Path(path).resolve()
    if not root.is_dir():
        raise HTTPException(400, "目录不存在或不可访问")

    roots = list(scanner.get_scan_roots(session))
    key = str(root)
    if key not in [str(r.resolve()) for r in roots]:
        roots.append(root)
        scanner.save_scan_roots(session, [str(r) for r in roots])

    bg.add_task(_background_scan, str(root))
    watcher.bump()
    return {
        "saved": True,
        "roots": [str(r) for r in scanner.get_scan_roots(session)],
        "scan": {"pending": True},
    }


@router.delete("/roots")
def remove_scan_root(body: dict, session: Session = Depends(get_session)):
    """移除已注册图片目录：软删其下图片并清理目录节点。"""
    path = (body.get("path") or "").strip()
    if not path:
        raise HTTPException(400, "缺少目录路径")
    root = Path(path).resolve()
    roots = [r for r in scanner.get_scan_roots(session) if str(r.resolve()) != str(root)]
    removed = scanner.unlink_root(session, root)
    scanner.save_scan_roots(session, [str(r) for r in roots])
    watcher.bump()
    return {
        "saved": True,
        "roots": [str(r) for r in scanner.get_scan_roots(session)],
        "removed": removed,
    }


@router.get("")
def get_settings(session: Session = Depends(get_session)):
    """读取设置（多个扫描路径 + 各模型角色配置 + 导入目录 + AI 提示词）。"""
    roots = [str(r) for r in scanner.get_scan_roots(session)]
    llm = {}
    for role in ROLES:
        cur = _role_config(session, role)
        per_vendor = {}
        for v in VENDORS:
            vc = _role_vendor_config(session, role, v)
            if any(vc.get(f) for f in ("base_url", "api_key", "model")):
                per_vendor[v] = vc
        llm[role] = {**cur, "vendors": per_vendor}
    # AI 提示词：已配置值 + 代码默认值（未配置时使用默认）
    from ..services import llm as llm_mod
    prompt_defaults = {
        "reverse": llm_mod.PROMPT_REVERSE,
        "tag": llm_mod.PROMPT_TAG,
        "score": llm_mod.PROMPT_SCORE,
        "translate": llm_mod.PROMPT_TRANSLATE,
    }
    prompts = {f: _get(session, f"prompt_{f}") for f in prompt_defaults}
    return {
        "scanRoots": roots,
        "llm": llm,
        "importDir": _get(session, "import_dir"),
        "prompts": prompts,
        "prompt_defaults": prompt_defaults,
        "compressMode": _get(session, "compress_mode") or "new",
        "compressQuality": _compress_quality(session),
        "theme": _normalize_theme(_get(session, "theme")),
    }


PROMPT_FEATURES = ("reverse", "tag", "score", "translate")


@router.post("")
def update_settings(body: dict, session: Session = Depends(get_session)):
    """保存设置（含各角色模型厂商、扫描多个根、导入保存目录），可触发扫描。"""
    llm = body.get("llm")
    if isinstance(llm, dict):
        for role in ROLES:
            _set_role_config(session, role, llm.get(role) or {})
    if body.get("prompts") is not None:
        prompts = body["prompts"] or {}
        for f in PROMPT_FEATURES:
            if f in prompts:
                _set(session, f"prompt_{f}", str(prompts[f] or ""))
    if body.get("scanRoots") is not None:
        scanner.save_scan_roots(session, [str(r) for r in body["scanRoots"]])
    if body.get("importDir") is not None:
        path = (body.get("importDir") or "").strip()
        if path:
            d = Path(path).expanduser().resolve()
            d.mkdir(parents=True, exist_ok=True)
            _set(session, "import_dir", str(d))
            # 让导入目录自动成为扫描根，浏览器导入的图片即可入库展示
            roots = list(scanner.get_scan_roots(session))
            key = str(d)
            if key not in [str(r.resolve()) for r in roots]:
                roots.append(d)
                scanner.save_scan_roots(session, [str(r) for r in roots])
        else:
            _set(session, "import_dir", "")
    if body.get("compressMode") is not None:
        _set(session, "compress_mode", "new" if str(body["compressMode"]).strip() == "new" else "overwrite")
    if body.get("compressQuality") is not None:
        _set(session, "compress_quality", str(_compress_quality_from(body["compressQuality"])))
    if body.get("theme") is not None:
        _set(session, "theme", _normalize_theme(body["theme"]))
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
        # 分别测试三个角色的连通性，逐个调用简单请求返回结果
        results = {}
        for role in ROLES:
            try:
                from ..services import llm
                cfg = body.get("llm", {}).get(role) or {}
                # 先存配置到数据库，让 llm 服务读取到最新配置
                _set_role_config(session, role, cfg)
                session.commit()
                # 简单探测调用
                if role == "text":
                    # 轻量探测连通与认证：GET /models，不发完整对话避免耗时/耗配额
                    from ..services.llm import _role_config
                    c = _role_config(session, "text")
                    base = (c.get("base_url") or "").strip()
                    key = (c.get("api_key") or "").strip()
                    model = (c.get("model") or "").strip()
                    if not (base and key and model):
                        raise llm.LLMNotConfigured("base_url/api_key/model 未配置完整")
                    import httpx
                    url = base.rstrip("/") + "/models"
                    headers = {"Authorization": f"Bearer {key}"}
                    # 直连不信任系统代理：代理出口 IP 可能被厂商限流导致误报 401
                    r = httpx.get(url, headers=headers, timeout=30, trust_env=False)
                    r.raise_for_status()
                    results[role] = {"ok": True, "message": "连接成功"}
                elif role == "vision":
                    # 视觉只探测连接与认证，不生成实际图片内容（避免消耗配额）
                    from ..services.llm import _role_config
                    c = _role_config(session, "vision")
                    base = (c.get("base_url") or "").strip()
                    key = (c.get("api_key") or "").strip()
                    model = (c.get("model") or "").strip()
                    if not (base and key and model):
                        raise llm.LLMNotConfigured("base_url/api_key/model 未配置完整")
                    # 只做 GET / 模型列表探测确认连通与认证
                    import httpx
                    url = base.rstrip("/") + "/models"
                    headers = {"Authorization": f"Bearer {key}"}
                    r = httpx.get(url, headers=headers, timeout=30, trust_env=False)
                    r.raise_for_status()
                    results[role] = {"ok": True, "message": "连接成功"}
                elif role == "embed":
                    # embedding 探测连通
                    from ..services.llm import _role_config
                    c = _role_config(session, "embed")
                    base = (c.get("base_url") or "").strip()
                    key = (c.get("api_key") or "").strip()
                    model = (c.get("model") or "").strip()
                    if not (base and key and model):
                        raise llm.LLMNotConfigured("base_url/api_key/model 未配置完整")
                    url = (
                        base
                        if base.rstrip("/").endswith("/embeddings")
                        else base.rstrip("/") + "/embeddings"
                    )
                    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                    payload = {"model": model, "input": "你好"}
                    r = httpx.post(url, headers=headers, json=payload, timeout=60, trust_env=False)
                    r.raise_for_status()
                    data = r.json()
                    if "data" not in data or not isinstance(data["data"], list) or not len(data["data"]):
                        raise llm.LLMError("embedding 返回格式异常")
                    results[role] = {"ok": True, "message": "连接成功"}
            except Exception as e:
                results[role] = {"ok": False, "message": str(e)}
        result["test"] = {"results": results}
    return result


ALLOWED_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@router.post("/upload")
def upload_image(
    file: UploadFile = File(...),
    path: str = Form(""),  # 可选相对子路径（目录导入保留目录结构），防穿越
    session: Session = Depends(get_session),
    bg: BackgroundTasks = BackgroundTasks(),
):
    """浏览器/拖拽导入图片：将文件保存到「导入保存目录」（绝对路径），并入库展示。

    目标目录优先取设置里的 import_dir；未配置时回退到应用数据目录下的自管导入区，
    以保证总能写入。path 提供时按相对子路径落盘（保留目录导入的目录结构）。
    """
    configured = _get(session, "import_dir").strip()
    if configured:
        target_dir = Path(configured).expanduser().resolve()
        if not target_dir.is_dir():
            raise HTTPException(400, f"导入保存目录不存在或不可访问：{target_dir}")
    else:
        target_dir = Path(env_settings.data_dir) / "import"
    target_dir.mkdir(parents=True, exist_ok=True)

    # 将导入目录纳入扫描根，导入图片即可实时入库展示
    roots = list(scanner.get_scan_roots(session))
    key = str(target_dir)
    if key not in [str(r.resolve()) for r in roots]:
        roots.append(target_dir)
        scanner.save_scan_roots(session, [str(r) for r in roots])

    name = Path(file.filename or "").name
    if not name:
        raise HTTPException(400, "缺少文件名")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_IMG_EXTS:
        raise HTTPException(400, f"仅支持图片格式: {', '.join(sorted(ALLOWED_IMG_EXTS))}")

    rel = (path or "").strip().replace("\\", "/")
    if rel:
        # 防穿越：解析后的子路径必须仍位于导入保存目录内
        sub = (target_dir / rel).resolve()
        if not sub.is_relative_to(target_dir.resolve()):
            raise HTTPException(400, "非法子路径")
        target_path = sub
        # 目录导入：把导入的顶层子目录（即用户所选目录名，来自 webkitRelativePath 首段）
        # 一并注册为扫描根，使其显示在设置页「已注册的图片目录」
        top = rel.split("/", 1)[0]
        if top:
            top_dir = (target_dir / top).resolve()
            if top_dir.is_relative_to(target_dir.resolve()):
                top_roots = list(scanner.get_scan_roots(session))
                if str(top_dir) not in [str(r.resolve()) for r in top_roots]:
                    top_roots.append(top_dir)
                    scanner.save_scan_roots(session, [str(r) for r in top_roots])
                # 嵌套注册根的子树由自己扫描（父根 scan 会跳过），立即后台扫描使图片尽快入库
                bg.add_task(_background_scan, str(top_dir))
    else:
        target_path = target_dir / name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target_path, "wb") as f:
            f.write(file.file.read())
    except OSError as exc:
        # 区分权限类错误，返回 403 供前端弹出授权引导
        if exc.errno in (errno.EACCES, errno.EPERM):
            raise HTTPException(
                403, f"写入图片失败：无写入权限，请授权运行本服务的终端访问「{target_dir}」后重试"
            )
        raise HTTPException(500, f"写入图片失败：{exc}")

    bg.add_task(_background_scan, str(target_dir))
    return {"saved": True, "path": str(target_path), "name": name}