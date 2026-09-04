# PNG 无损压缩（纯 Pillow）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为画镜 ArtMirror 增加 PNG 无损压缩：image 单张 + gallery 多选批量，支持「存新图入库 / 覆盖原图」两种模式、可选保留内嵌工作流信息，压缩后变大则中止并提示。

**Architecture:** 新增一个纯 Pillow 的 service（读取→重写 PNG，像素不变），一个 compress 路由（单张 + 批量），复用现有 Setting KV 存「模式/保留工作流」两项设置；存新图复用现有「导入保存目录 + 后台扫描入库」通道，覆盖原图复用 `_move_to_trash` 备份。零新增第三方依赖。

**Tech Stack:** Python 3.12 · FastAPI · SQLModel(SQLite) · Pillow（已有）· Send2Trash（已有）

参考 Spec：`docs/superpowers/specs/2026-09-04-png-lossless-compress-design.md`

---

### Task 1: 核心压缩 service（纯 Pillow，无损）

**Files:**
- Create: `artmirror/services/compress.py`
- Test: `tests/test_compress.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compress.py
from io import BytesIO
from pathlib import Path

from PIL import Image, PngImagePlugin

from artmirror.services.compress import compress_png


def _make_png(path: Path, with_meta: bool = True) -> None:
    img = Image.new("RGB", (8, 8), (120, 90, 60))
    info = PngImagePlugin.PngInfo()
    info.add_text("Software", "test")
    if with_meta:
        info.add_text("workflow", '{"nodes":[]}')
    img.save(path, "PNG", pnginfo=info)


def test_lossless_pixels(tmp_path):
    p = tmp_path / "a.png"
    _make_png(p)
    data = compress_png(p, keep_meta=True)
    out = Image.open(BytesIO(data))
    ref = Image.open(p)
    assert list(out.getdata()) == list(ref.getdata())


def test_keeps_meta_when_requested(tmp_path):
    p = tmp_path / "m.png"
    _make_png(p)
    data = compress_png(p, keep_meta=True)
    assert "workflow" in Image.open(BytesIO(data)).info


def test_strips_meta_when_not_requested(tmp_path):
    p = tmp_path / "m.png"
    _make_png(p)
    data = compress_png(p, keep_meta=False)
    assert "workflow" not in Image.open(BytesIO(data)).info
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_compress.py -v`
Expected: FAIL with `ImportError: cannot import name 'compress_png'`

- [ ] **Step 3: Write minimal implementation**

```python
# artmirror/services/compress.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_compress.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add artmirror/services/compress.py tests/test_compress.py
git commit -m "feat: PNG 无损压缩 service（纯 Pillow，可保留/剥离文本块）"
```

---

### Task 2: compress 路由（单张 + 批量）

**Files:**
- Create: `artmirror/routers/compress.py`
- Modify: `artmirror/main.py:47-56`（把新路由加进 include 元组）
- Test: `tests/test_compress_api.py`

- [ ] **Step 1: Write the failing test**

参考 `tests/test_images_api.py` 的临时数据目录与 app 装配方式（`create_data_dir`/`reset_engine`、`app.include_router(...)`），新增：

```python
# tests/test_compress_api.py
import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from artmirror.main import create_app
from artmirror.database import get_engine, reset_engine
from artmirror.models import ImageAsset, Setting
from sqlmodel import Session, select


def _make_app(tmp_path):
    reset_engine(data_dir=str(tmp_path))
    app = create_app(data_dir=str(tmp_path))
    return app


def test_single_compress_new(tmp_path):
    app = _make_app(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (100, 100, 100)).save(buf, "PNG")
    import_dir = tmp_path / "import"
    import_dir.mkdir(exist_ok=True)
    src = import_dir / "a.png"
    src.write_bytes(buf.getvalue())
    with Session(get_engine()) as s:
        s.add(Setting(key="compress_mode", value="new"))
        s.add(Setting(key="compress_keep_meta", value="true"))
        s.add(ImageAsset(abs_path=str(src), file_name="a.png", width=8, height=8, file_size=src.stat().st_size, sha256="x"))
        s.commit()
        im = s.exec(select(ImageAsset)).first()
        image_id = im.id
    c = TestClient(app)
    r = c.post(f"/api/images/{image_id}/compress")
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["original"] > body["compressed"]


def test_single_compress_overwrite(tmp_path):
    app = _make_app(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (100, 100, 100)).save(buf, "PNG")
    src = tmp_path / "b.png"
    src.write_bytes(buf.getvalue())
    with Session(get_engine()) as s:
        s.add(Setting(key="compress_mode", value="overwrite"))
        s.add(Setting(key="compress_keep_meta", value="false"))
        s.add(ImageAsset(abs_path=str(src), file_name="b.png", width=8, height=8, file_size=src.stat().st_size, sha256="y"))
        s.commit()
        im = s.exec(select(ImageAsset)).first()
        image_id = im.id
    c = TestClient(app)
    r = c.post(f"/api/images/{image_id}/compress")
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["new_file"] == str(src)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_compress_api.py -v`
Expected: FAIL with 404 (路由不存在) 或 module 未定义

- [ ] **Step 3: Write minimal implementation**

```python
# artmirror/routers/compress.py
"""PNG 无损压缩路由：image 单张 + gallery 多选批量。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session

from ..config import settings as env_settings
from ..database import get_engine, get_session
from ..models import ImageAsset, Setting
from ..services import compress as compress_svc
from ..services import scanner, watcher
from .images import _move_to_trash

router = APIRouter(prefix="/api/images", tags=["compress"])


def _get(session: Session, key: str) -> str:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    return row.value if row else ""


def _background_scan(root: str) -> None:
    try:
        with Session(get_engine()) as session:
            stats = scanner.scan(session, Path(root))
            if stats.new or stats.updated or stats.removed:
                watcher.bump()
    except Exception:  # noqa: BLE001
        pass


def _unique_target(dir: Path, stem: str) -> Path:
    candidate = dir / f"{stem}_compressed.png"
    i = 1
    while candidate.exists():
        candidate = dir / f"{stem}_compressed-{i}.png"
        i += 1
    return candidate


def _compress_one(session: Session, im: ImageAsset):
    mode = _get(session, "compress_mode") or "new"
    keep = (_get(session, "compress_keep_meta") or "true") != "false"
    src = Path(im.abs_path)
    ext = src.suffix.lower()
    if ext != ".png":
        raise HTTPException(400, "仅支持 PNG 格式")
    if not src.is_file():
        raise HTTPException(404, "原文件不存在")
    old = src.stat().st_size
    data = compress_svc.compress_png(src, keep_meta=keep)
    if len(data) >= old:
        return {
            "id": im.id,
            "original": old,
            "compressed": len(data),
            "saved": False,
            "new_file": None,
            "reason": "压缩后反而更大，已跳过",
        }
    if mode == "overwrite":
        _move_to_trash(src)  # 先备份原图到废纸篓，再覆盖
        src.write_bytes(data)
        return {
            "id": im.id,
            "original": old,
            "compressed": len(data),
            "saved": True,
            "new_file": str(src),
            "reason": None,
        }
    # new：写入「导入保存目录」并可入库展示
    configured = _get(session, "import_dir").strip()
    if configured:
        target_dir = Path(configured).expanduser().resolve()
        if not target_dir.is_dir():
            raise HTTPException(400, f"导入保存目录不存在或不可访问：{target_dir}")
    else:
        target_dir = Path(env_settings.data_dir) / "import"
    target_dir.mkdir(parents=True, exist_ok=True)
    roots = list(scanner.get_scan_roots(session))
    key = str(target_dir)
    if key not in [str(r.resolve()) for r in roots]:
        roots.append(target_dir)
        scanner.save_scan_roots(session, [str(r) for r in roots])
    new = _unique_target(target_dir, src.stem)
    new.write_bytes(data)
    session.commit()
    _background_scan(str(target_dir))
    return {
        "id": im.id,
        "original": old,
        "compressed": len(data),
        "saved": True,
        "new_file": str(new),
        "reason": None,
    }


@router.post("/{image_id}/compress")
def compress_one(image_id: int, session: Session = Depends(get_session)):
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    return _compress_one(session, im)


@router.post("/batch-compress")
def compress_batch(
    body: dict,
    session: Session = Depends(get_session),
    bg: BackgroundTasks = BackgroundTasks(),
):
    raw = body.get("ids")
    if not isinstance(raw, list):
        raise HTTPException(400, "ids 需为数组")
    results, saved = [], 0
    for rid in raw:
        im = session.get(ImageAsset, int(rid))
        try:
            if im is None or im.is_deleted:
                raise HTTPException(404, "image not found")
            item = _compress_one(session, im)
        except HTTPException as exc:
            item = {
                "id": int(rid),
                "original": None,
                "compressed": None,
                "saved": False,
                "new_file": None,
                "reason": str(exc.detail),
            }
        if item.get("saved"):
            saved += 1
        results.append(item)
    return {"results": results, "total": len(results), "saved_count": saved}
```

- [ ] **Step 4: Register router in main.py**

在 `artmirror/main.py` 顶部把 `compress` 加入 routers import（保持现有 import 风格）：

```python
from .routers import (
    aggregate,
    compress,
    folders,
    fs,
    images,
    settings as settings_router,
    sync,
    tags,
)
```

并把下面 include 元组改为：

```python
    for r in (
        images.router,
        folders.router,
        tags.router,
        aggregate.router,
        settings_router.router,
        fs.router,
        sync.router,
        compress.router,
    ):
        app.include_router(r)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_compress_api.py -v`
Expected: PASS（2 passed）

> 注意：若 `create_app` 签名与测试不符，以 `tests/test_images_api.py` 现有装配为准调整测试的 app 构造；不得改动生产代码去迁就测试。

- [ ] **Step 6: Commit**

```bash
git add artmirror/routers/compress.py artmirror/main.py tests/test_compress_api.py
git commit -m "feat: PNG 无损压缩路由（单张+批量，存新/覆盖，变大即跳过）"
```

---

### Task 3: 设置项（后端 KV + 前端保存/读取）

**Files:**
- Modify: `artmirror/routers/settings.py`（get 返回 + post 接收两项）
- Modify: `frontend/api.js:179-190`（getSettings 返回字段 + updateSettings 载荷）
- Modify: `frontend/settings.html`（新增两个开关并纳入保存）

- [ ] **Step 1: 后端 get 返回两项**

在 `artmirror/routers/settings.py` 的 `get_settings` 返回 dict（约 144-150 行）中加入：

```python
        "importDir": _get(session, "import_dir"),
        "compressMode": _get(session, "compress_mode") or "new",
        "compressKeepMeta": _get(session, "compress_keep_meta") or "true",
```

- [ ] **Step 2: 后端 post 接收两项**

`update_settings`（`session.commit()` 前）加入：

```python
    if body.get("compressMode") is not None:
        _set(session, "compress_mode", "new" if str(body["compressMode"]).strip() == "new" else "overwrite")
    if body.get("compressKeepMeta") is not None:
        _set(session, "compress_keep_meta", "true" if str(body["compressKeepMeta"]).lower() in ("true", "1") else "false")
```

- [ ] **Step 3: 前端 api.js**

`getSettings` 的 fallback `ok({...})` 追加 `compressMode: "new", compressKeepMeta: "true"`；`updateSettings` 已是透传 JSON，无需改签名。

- [ ] **Step 4: 前端 settings.html 新增压缩设置块**

在设置页合适位置（如「图片目录」卡片后）新增一块，沿用现有 Alpine `cfg` 绑定与保存回调（参考现有 `v-model="cfg.importDir"` / 保存按钮的 `save` 方法把整个 `cfg` 交给 `Api.updateSettings`）：

```html
<div class="card pad">
  <h3 style="margin-top:0">PNG 无损压缩</h3>
  <label class="field">
    <span>压缩结果处理</span>
    <select x-model="cfg.compressMode">
      <option value="new">存为新图（入库展示）</option>
      <option value="overwrite">覆盖原图</option>
    </select>
  </label>
  <label class="field">
    <span style="display:inline-flex;align-items:center;gap:8px">
      <input type="checkbox" x-model="cfg.compressKeepMeta" style="width:auto" />
      保留内嵌工作流信息（workflow / 提示词）
    </span>
    <span class="muted">关闭可压得更小，但会剥离文件内的工作流/提示词文本块（覆盖模式时尤需注意）。</span>
  </label>
</div>
```

已知 `cfg` 初始字段在 settings.html 中定义（约 line 229 `version:""` 附近）。在 init 读取设置处标上 `compressMode:"new", compressKeepMeta:"true"`。保存时 `Api.updateSettings(cfg)` 已透传全部字段 → 后端按 type Step2 读取。

- [ ] **Step 5: 全量路由冒烟**

Run: `uv run pytest -q`（应全过，忽略已知 Windows 临时目录锁的 3 个 `test_default_scan_root*` 环境性失败）

- [ ] **Step 6: Commit**

```bash
git add artmirror/routers/settings.py frontend/api.js frontend/settings.html
git commit -m "feat: 设置页新增 PNG 压缩模式与保留工作流两项"
```

---

### Task 4: 前端——图片详情页单张压缩

**Files:**
- Modify: `frontend/image.html`（详情大图头部按钮 + Detail 方法）
- Modify: `frontend/api.js`（`compressImage`）

- [ ] **Step 1: api.js 新增方法**（放在 `updatePrompt` 附近）

```javascript
    compressImage: function (id) {
      return req("api/images/" + id + "/compress", { method: "POST" }).catch(function (e) {
        throw e;
      });
    },
```

- [ ] **Step 2: image.html 头部加「压缩」按钮**（在「返回图库」之前，约 line 45 区域）

```html
            <button class="btn sm" @click="compress()" :disabled="compressing">
              <span x-text="compressing ? '压缩中…' : '压缩'"></span>
            </button>
```

- [ ] **Step 3: Detail 对象加状态与方法**

state 区（约 line 197）加 `compressing: false`；方法区加：

```javascript
    compress() {
      var self = this;
      if (!this.im || this.compressing) return;
      this.compressing = true;
      Api.compressImage(this.im.id).then(function (r) {
        self.compressing = false;
        if (r && r.saved) {
          App.toast("压缩成功：原 " + App.fmtSize(r.original) + " → " + App.fmtSize(r.compressed));
        } else {
          App.toast((r && r.reason) || "压缩未生效");
        }
      }).catch(function (e) {
        self.compressing = false;
        App.toast("压缩失败：" + ((e && e.message) || e));
      });
    },
```

> `App.fmtSize` 为全局可用（app.js）。`req` 已处理 JSON。reduced-motion 无关。

- [ ] **Step 4: Commit**

```bash
git add frontend/api.js frontend/image.html
git commit -m "feat: 图片详情页单张 PNG 无损压缩（含变大跳过提示）"
```

---

### Task 5: 前端——图库多选批量压缩

**Files:**
- Modify: `frontend/api.js`（`batchCompress`）
- Modify: `frontend/gallery.html`（工具栏批量按钮 + Gallery 方法）

- [ ] **Step 1: api.js 新增方法**

```javascript
    batchCompress: function (ids) {
      return req("api/images/batch-compress", { method: "POST", body: { ids: ids } }).catch(function (e) {
        throw e;
      });
    },
```

- [ ] **Step 2: gallery.html 批量按钮**（在批量删除按钮旁，约 line 81-85 区域，`x-show`/`x-cloak` 与现有批量删除一致）

```html
        <button class="icon-btn" data-tip="批量压缩选中图片" x-show="mode!=='aggregate'" x-cloak
                :class="{active: selCount()>0}" :disabled="selCount()===0" @click="batchCompress()">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5"/><rect x="3" y="17" width="18" height="4" rx="1"/></svg>
        </button>
```

- [ ] **Step 3: Gallery 方法**

```javascript
    batchCompress() {
      var ids = this.selIds.slice();
      if (!ids.length) return;
      var self = this;
      App.toast("正在压缩 " + ids.length + " 张…");
      Api.batchCompress(ids).then(function (r) {
        var saved = (r && r.saved_count) || 0;
        var total = (r && r.total) || ids.length;
        self.clearSel();
        App.toast("压缩完成：成功 " + saved + " / " + total);
        // 存新图模式有新文件入库，刷新图库可见
        if (saved && self.mode !== "aggregate") self.manualRefresh();
      }).catch(function (e) {
        self.clearSel();
        App.toast("压缩失败：" + ((e && e.message) || e));
      });
    },
```

- [ ] **Step 4: Commit**

```bash
git add frontend/api.js frontend/gallery.html
git commit -m "feat: 图库多选批量 PNG 无损压缩（汇总提示+刷新）"
```

---

### Task 6: 文档、全量测试、重启验证

**Files:**
- Modify: `docs/功能清单.md`（新增一条更新记录）

- [ ] **Step 1: 更新功能清单**

在「更新记录」表首行插入：

```
| 2026-09-04 | PNG 无损压缩 | 新增：image 单张 + gallery 多选批量 PNG 无损压缩（纯 Pillow 零依赖）；设置 `compress_mode`(存新图/覆盖) 与 `compress_keep_meta`(保留工作流 info)，存新图写入导入目录并入库，覆盖前原图入废纸篓；压缩后变大则中止并提示 |
```

- [ ] **Step 2: 全量测试**

Run: `uv run pytest -q`
Expected: 除 `test_default_scan_root*` 3 例（Windows 临时目录 DB 文件锁的环境性问题，与本功能无关）外全部通过；新增 `test_compress*` 全过。

- [ ] **Step 3: 重启服务并验证健康**

```bash
git commit 已由前序步骤完成，此处仅重启：
# 按 AGENTS 重启命令重启 uvicorn :8000，并 curl /api/health 应返回 ok 且 version=1.0.0
```

- [ ] **Step 4: 提交文档**

```bash
git add docs/功能清单.md
git commit -m "docs: 记录 PNG 无损压缩功能"
```

---

## Self-Review 记录

- Spec 覆盖：设置两项（Task3）、单张/批量（Task2/4/5）、变大中止（Task2 `_compress_one`）、存新图入库/覆盖备份（Task2）、保留工作流（Task1 keep_meta + Task3 开关）、前端提示（Task4/5）。无遗漏。
- 类型一致：`compress_png(src: Path, keep_meta: bool) -> bytes`；`_compress_one` 返回 dict 含 `id/original/compressed/saved/new_file/reason`；`batch` 复用。接口路径 `/api/images/{id}/compress` 与 `/api/images/batch-compress` 前后端一致。
- 无占位：所有步骤含真实代码或精确路径；前端 settings 块沿用现有 `cfg`/`v-model` 模式，若 `cfg` 具体结构有出入，engine 依既有 `settings.html` 定义处对齐即可。