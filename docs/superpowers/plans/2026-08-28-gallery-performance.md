# 图库页一万张图片性能优化 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一万张图片下图库首屏 < 1s、接口 < 100ms：后端分页 + 批量查询，前端无限滚动 + 提示条 + 补页恢复。

**Architecture:** 后端消灭 `to_card` N+1（整页固定 5 次批量查询），`GET /api/images` 与聚合接口改分页协议 `{items, total, limit, offset, hasMore}`；聚合成员懒加载。前端 Alpine 无限滚动（IntersectionObserver 哨兵 + re-arm），轮询变化改为提示条，详情页返回补页恢复滚动。规格见 `docs/superpowers/specs/2026-08-28-gallery-performance-design.md`。

**Tech Stack:** FastAPI + SQLModel(SQLite) + pytest + TestClient；前端 Alpine.js 无构建静态页。

**注意：**
- git 身份未配置时提交用：`git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit ...`
- 后端命令一律在 `backend/` 目录执行：`uv run pytest -q`
- 每个任务完成后按 AGENTS.md 重启服务验证：`lsof -ti:8000 | xargs kill -9 2>/dev/null; sleep 1; cd backend && (uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/am.log 2>&1 &)`
- Task 5（聚合后端）与 Task 6（聚合前端）之间聚合模式短暂不可用，属预期中间态

---

### Task 1: 后端批量组装 `to_cards` + 完整版 `to_card`

**Files:**
- Modify: `backend/app/routers/images.py`
- Test: `backend/tests/test_images_api.py`（新建）

- [ ] **Step 1: 新建测试文件（先写失败测试）**

```python
"""图片列表接口测试（批量组装 / 分页 / 卡片瘦身 / 缩略图缓存头）。

只挂载 images 路由（避免 watcher 与静态托管副作用），DB 为独立 SQLite 文件。
"""
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.database import get_session
from app.models import (
    ImageAsset, ImageTag, PromptTranslation, RatingRecord, ReversePrompt, Tag, WorkflowMeta,
)
from app.routers import images


def _setup(tmp: Path):
    settings.data_dir = str(tmp)
    settings.ensure_dirs()
    engine = create_engine(
        f"sqlite:///{tmp / 't.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(images.router)

    def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return TestClient(app), engine


def _seed(session: Session, n: int = 3) -> list[ImageAsset]:
    """造 n 张图：meta / 两条反推（最新生效）/ 译文 / AI 评分理由 / 标签。"""
    ims = []
    for i in range(n):
        im = ImageAsset(
            file_name=f"i{i}.png", file_path=f"/x/i{i}.png", abs_path=f"/x/i{i}.png",
            sha256=f"{i:064x}", width=64, height=64, file_size=100,
        )
        session.add(im)
        session.flush()
        session.add(WorkflowMeta(
            image_id=im.id, prompt=f"p{i} masterpiece", negative_prompt="neg",
            origin_prompts_json='["pa","pb"]', steps=20, cfg=7, seed=i,
        ))
        session.add(ReversePrompt(image_id=im.id, text="rev-old"))
        session.add(ReversePrompt(image_id=im.id, text="rev-new"))
        session.add(PromptTranslation(image_id=im.id, prompt_kind="origin", lang="zh", text="译文"))
        session.add(RatingRecord(image_id=im.id, rating_type="ai", score=90, reason="好看"))
        ims.append(im)
    tag = Tag(name="model-x", category="model")
    session.add(tag)
    session.flush()
    for im in ims:
        session.add(ImageTag(image_id=im.id, tag_id=tag.id))
    session.commit()
    return ims


def test_to_cards_batch_and_full_card():
    with tempfile.TemporaryDirectory() as td:
        _, engine = _setup(Path(td))
        with Session(engine) as s:
            ims = _seed(s, 2)
            from app.routers.images import to_card, to_cards
            cards = to_cards(s, ims)
            assert [c["id"] for c in cards] == [im.id for im in ims]
            c = cards[0]
            assert c["reversePrompt"] == "rev-new"          # 取最新一条
            assert c["tags"] == [{"name": "model-x", "category": "model"}]
            assert c["originPrompts"] == ["pa", "pb"]
            assert c["thumb"] == f"/api/images/{c['id']}/thumb"
            for absent in ("negative", "negativePrompts", "aiNegative", "aiReason", "translationZH", "params"):
                assert absent not in c                      # 列表瘦身字段
            full = to_card(s, ims[0])
            for present in ("negative", "negativePrompts", "aiNegative", "aiReason", "translationZH", "params"):
                assert present in full
            assert full["translationZH"] == "译文"
            assert full["aiReason"] == "好看"
            assert full["params"]["steps"] == 20
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_images_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'to_cards'`

- [ ] **Step 3: 实现 `to_cards`（images.py 中 `to_card` 上方插入，并重写 `to_card`）**

在 [images.py](file:///workspace/backend/app/routers/images.py) 中，将现有 `to_card` 函数（`def to_card(session, im)` 整个函数体）替换为：

```python
def to_cards(session: Session, images: list[ImageAsset]) -> list[dict]:
    """批量组装图库卡片（列表页瘦身版：整页固定 5 次查询，消除逐图 N+1）。"""
    if not images:
        return []
    ids = [im.id for im in images]

    meta_by = {
        m.image_id: m
        for m in session.exec(
            select(WorkflowMeta).where(WorkflowMeta.image_id.in_(ids))
        ).all()
    }

    # 同图多条时取最新：按 id 升序遍历，后写覆盖
    reverse_by: dict[int, ReversePrompt] = {}
    for r in session.exec(
        select(ReversePrompt)
        .where(ReversePrompt.image_id.in_(ids))
        .order_by(ReversePrompt.id)
    ).all():
        reverse_by[r.image_id] = r

    trans_by: dict[int, str] = {}
    for t in session.exec(
        select(PromptTranslation).where(
            PromptTranslation.image_id.in_(ids),
            PromptTranslation.prompt_kind == "origin",
            PromptTranslation.lang == "zh",
        )
    ).all():
        trans_by[t.image_id] = t.text

    ai_reason_by: dict[int, str] = {}
    for r in session.exec(
        select(RatingRecord)
        .where(RatingRecord.image_id.in_(ids), RatingRecord.rating_type == "ai")
        .order_by(RatingRecord.id)
    ).all():
        ai_reason_by[r.image_id] = r.reason or ""

    tags_by: dict[int, list[dict]] = {i: [] for i in ids}
    for link, tag in session.exec(
        select(ImageTag, Tag)
        .join(Tag, Tag.id == ImageTag.tag_id)
        .where(ImageTag.image_id.in_(ids), ImageTag.is_deleted == 0)
    ).all():
        if link.image_id in tags_by:
            tags_by[link.image_id].append(
                {"name": _basename(tag.name), "category": tag.category}
            )

    cards = []
    for im in images:
        meta = meta_by.get(im.id)
        reverse = reverse_by.get(im.id)
        cards.append({
            "id": im.id,
            "folderId": im.folder_id,
            "name": im.file_name,
            "width": im.width,
            "height": im.height,
            "fileSize": im.file_size,
            "rating": im.rating,
            "aiRating": im.ai_rating,
            "prompt": meta.prompt if meta else "",
            "originPrompts": _load_str_list(meta.origin_prompts_json if meta else "") or ([meta.prompt] if meta and meta.prompt else []),
            "aiPrompts": _load_str_list(meta.ai_prompts_json if meta else "") or ([meta.ai_prompt] if meta and meta.ai_prompt else []),
            "aiPrompt": meta.ai_prompt if meta else "",
            "reversePrompt": reverse.text if reverse else None,
            "tags": tags_by.get(im.id, []),
            "thumb": f"/api/images/{im.id}/thumb",
        })
    return cards


def to_card(session: Session, im: ImageAsset) -> dict:
    """单图完整卡片（详情页 / 单图接口用）：批量瘦身版 + 详情补充字段。"""
    card = to_cards(session, [im])[0]
    meta = session.exec(
        select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)
    ).first()
    trans = session.exec(
        select(PromptTranslation).where(
            PromptTranslation.image_id == im.id,
            PromptTranslation.prompt_kind == "origin",
            PromptTranslation.lang == "zh",
        )
    ).first()
    card["negative"] = meta.negative_prompt if meta else ""
    card["negativePrompts"] = _load_str_list(meta.negative_prompts_json if meta else "")
    card["aiNegative"] = meta.ai_negative_prompt if meta else ""
    card["aiReason"] = _latest_ai_reason(session, im.id)
    card["translationZH"] = trans.text if trans else None
    card["params"] = {
        "steps": meta.steps if meta else None,
        "cfg": meta.cfg if meta else None,
        "sampler": meta.sampler if meta else None,
        "scheduler": meta.scheduler if meta else None,
        "seed": meta.seed if meta else None,
        "denoise": meta.denoise if meta else None,
    }
    return card
```

说明：`to_detail` / 评分 / 删除等单图接口继续调用完整版 `to_card`，行为与旧版一致（[image.html](file:///workspace/frontend/image.html) 依赖这些字段）。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && uv run pytest tests/test_images_api.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/routers/images.py backend/tests/test_images_api.py
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "perf: 图片卡片批量组装 to_cards，消除逐图 N+1 查询"
```

---

### Task 2: 列表接口分页协议 + 卡片瘦身

**Files:**
- Modify: `backend/app/routers/images.py`（`_query_images` 与 `list_images`）
- Test: `backend/tests/test_images_api.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
def test_list_pagination_defaults_and_caps():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s, 5)
        body = client.get("/api/images").json()
        assert body["total"] == 5 and len(body["items"]) == 5 and body["hasMore"] is False
        assert body["limit"] == 60 and body["offset"] == 0
        body = client.get("/api/images?limit=2").json()
        assert len(body["items"]) == 2 and body["hasMore"] is True
        body = client.get("/api/images?limit=2&offset=4").json()
        assert len(body["items"]) == 1 and body["hasMore"] is False
        assert client.get("/api/images?limit=9999").json()["limit"] == 200  # 上限截断


def test_list_filter_sort_and_slim():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s, 3)
        body = client.get("/api/images?q=p1").json()  # 命中 1 张
        assert body["total"] == 1 and body["items"][0]["prompt"] == "p1 masterpiece"
        ids = [c["id"] for c in client.get("/api/images?sort=time").json()["items"]]
        assert ids == sorted(ids, reverse=True)
        c = client.get("/api/images").json()["items"][0]
        for absent in ("negative", "negativePrompts", "aiNegative", "aiReason", "translationZH", "params"):
            assert absent not in c


def test_detail_keeps_full_fields():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            ims = _seed(s, 1)
        d = client.get(f"/api/images/{ims[0].id}").json()
        for present in ("negative", "params", "aiReason", "translationZH", "workflow", "translations"):
            assert present in d
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_images_api.py -v`
Expected: 新增 3 例 FAIL（响应仍是裸数组 / limit 参数不存在）

- [ ] **Step 3: 实现分页**

images.py 顶部导入区追加：

```python
from sqlalchemy import func
```

将 `_query_images` 与 `list_images` 两个函数替换为：

```python
def _filter_images(session: Session, folder_id, tag, q):
    """构建过滤后的基础查询（不含排序/分页）。"""
    stmt = select(ImageAsset).where(ImageAsset.is_deleted == 0)
    hidden = _hidden_folders(session)
    if hidden:
        stmt = stmt.where(
            ImageAsset.folder_id.is_(None)
            | (~ImageAsset.folder_id.in_(list(hidden)))
        )
    if folder_id:
        stmt = stmt.where(ImageAsset.folder_id == folder_id)
    if tag:
        stmt = stmt.join(
            ImageTag, ImageTag.image_id == ImageAsset.id
        ).join(Tag, Tag.id == ImageTag.tag_id).where(Tag.name == tag)
    if q:
        like = f"%{q}%"
        stmt = stmt.join(
            WorkflowMeta, WorkflowMeta.image_id == ImageAsset.id, isouter=True
        ).where(
            (WorkflowMeta.prompt.like(like))
            | (WorkflowMeta.negative_prompt.like(like))
            | (ImageAsset.file_name.like(like))
        ).distinct()
    return stmt


def _order_for(sort: str):
    if sort == "manual":
        return ImageAsset.rating.desc().nullslast()
    if sort == "time":
        return ImageAsset.id.desc()
    return ImageAsset.ai_rating.desc().nullslast()


@router.get("")
def list_images(
    folderId: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    sort: str = "ai",
    limit: int = 60,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """列出图片卡片（分页：过滤 + 排序由后端唯一负责）。"""
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    base = _filter_images(session, folderId, tag, q)
    total = session.exec(select(func.count()).select_from(base.subquery())).one()
    imgs = session.exec(
        base.order_by(_order_for(sort)).offset(offset).limit(limit)
    ).all()
    return {
        "items": to_cards(session, imgs),
        "total": total,
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(imgs) < total,
    }
```

- [ ] **Step 4: 运行确认通过（含全量回归）**

Run: `cd backend && uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/routers/images.py backend/tests/test_images_api.py
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "feat: 图片列表分页协议 items/total/hasMore + 卡片瘦身"
```

---

### Task 3: 缩略图缓存头

**Files:**
- Modify: `backend/app/routers/images.py`（`thumb` 函数）
- Test: `backend/tests/test_images_api.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
def test_thumb_cache_control():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            ims = _seed(s, 1)
        from PIL import Image
        p = settings.thumbs_dir / f"{ims[0].sha256}.webp"
        Image.new("RGB", (8, 8)).save(str(p), "WEBP")
        r = client.get(f"/api/images/{ims[0].id}/thumb")
        assert r.status_code == 200
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_images_api.py::test_thumb_cache_control -v`
Expected: FAIL（无 cache-control 头）

- [ ] **Step 3: 实现**

`thumb` 函数中 `return FileResponse(path)` 改为：

```python
        return FileResponse(
            path,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
```

（缩略图按 sha256 内容寻址，天然不可变；不影响前端静态资源 no-cache 策略。）

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && uv run pytest tests/test_images_api.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/routers/images.py backend/tests/test_images_api.py
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "perf: 缩略图响应加 immutable 缓存头"
```

---

### Task 4: 前端列表数据层 + 无限滚动

**Files:**
- Modify: `frontend/api.js`（`listImages`）
- Modify: `frontend/gallery.html`（Gallery 状态与加载逻辑、哨兵元素）
- Modify: `frontend/style.css`（追加样式）

- [ ] **Step 1: api.js — `listImages` 改分页协议 + Mock 包装**

将 [api.js](file:///workspace/frontend/api.js) 中 `listImages` 替换为：

```javascript
    listImages: function (opts) {
      opts = opts || {};
      var qs = [];
      if (opts.folderId) qs.push("folderId=" + opts.folderId);
      if (opts.tag) qs.push("tag=" + encodeURIComponent(opts.tag));
      if (opts.q) qs.push("q=" + encodeURIComponent(opts.q));
      qs.push("sort=" + (opts.sort || "ai"));
      qs.push("limit=" + (opts.limit || 60));
      qs.push("offset=" + (opts.offset || 0));
      return req("api/images?" + qs.join("&")).catch(function () {
        Api._fallback = true;
        var all = window.Mock.getImages();
        var off = opts.offset || 0, lim = opts.limit || 60;
        return ok({
          items: all.slice(off, off + lim),
          total: all.length,
          limit: lim,
          offset: off,
          hasMore: off + lim < all.length
        });
      });
    },
```

- [ ] **Step 2: gallery.html — 状态字段**

`window.Gallery` 对象的状态声明替换为（新增 `limit/total/hasMore/loadingMore/_reqSeq/_io/_gio/_resumePages`，其余保持原值）：

```javascript
  window.Gallery = {
    folders: [], images: [], groups: [], groupCount: 0, tags: [], q: "", mode: "flat", currentFolder: "",
    folderOpen: false, sortOpen: false,
    selectedTag: null, sort: "time", loading: true, summary: "", showWorkflow: false, wfText: "",
    delTarget: null, _ver: -1, _restoreScroll: 0, _resumePages: 0, _reqSeq: 0, _io: null, _gio: null,
    limit: 60, total: 0, hasMore: false, loadingMore: false,
    permModal: false, permMsg: "", permFiles: null,
```

- [ ] **Step 3: gallery.html — init 中初始化观察器**

`init()` 末尾（`setInterval(...)` 之前）插入：

```javascript
      this._initObservers();
```

并在 `init()` 方法后新增三个方法：

```javascript
    _initObservers() {
      var self = this;
      if (!("IntersectionObserver" in window)) return;
      this._io = new IntersectionObserver(function (ents) {
        if (ents[0].isIntersecting) self.loadMore();
      }, { rootMargin: "600px" });
      this._gio = new IntersectionObserver(function (ents) {
        if (ents[0].isIntersecting) self.loadMoreGroups();
      }, { rootMargin: "600px" });
    },
    // 重新观察哨兵：observe() 会立即回调当前交叉状态，
    // 覆盖「列表重置后哨兵仍处于交叉态、不再触发回调」的场景
    _rearm(which) {
      var io = which === "groups" ? this._gio : this._io;
      var el = document.getElementById(which === "groups" ? "am-group-sentinel" : "am-sentinel");
      if (io && el) { io.unobserve(el); io.observe(el); }
    },
    _afterRender(fn) {
      requestAnimationFrame(function () { requestAnimationFrame(fn); });
    },
```

- [ ] **Step 4: gallery.html — 重写 `loadImages`，新增 `loadMore` / `_initCards`**

将 `loadImages()` 整个方法替换为（注意：删除了前端二次排序，排序由后端唯一负责；保留原有滚动恢复双 rAF 定位块）：

```javascript
    _initCards(list) {
      // 初始化卡片状态；默认源：有原生优先原生，否则反推
      list.forEach(function (im) {
        im._exp = false;
        im._src = (im.prompt && im.prompt !== "") ? "origin" : "reverse";
        im._aiParse = false; im._rParse = false; im._wantSrc = ""; im._pErr = ""; im._mErr = "";
      });
    },
    loadImages() {
      this.loading = true;
      var self = this, seq = ++this._reqSeq;
      Api.listImages({ folderId: this.currentFolder || null, tag: this.selectedTag, q: this.q,
                       sort: this.sort, limit: this.limit, offset: 0 })
        .then(function (page) {
          if (seq !== self._reqSeq) return; // 过期响应丢弃
          self._initCards(page.items);
          self.images = page.items;
          self.total = page.total;
          self.hasMore = page.hasMore;
          self.summary = "已显示 " + page.items.length + " / 共 " + page.total + " 张";
          self.loading = false;
          self._afterRender(function () { self._rearm("list"); });
          // 从详情页返回：先不可见，等 Alpine 渲染出完整布局（双 rAF）再定位并一次性显示
          if (self._restoreScroll) {
            var y = self._restoreScroll;
            self._restoreScroll = 0;
            (function pin() {
              requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                  window.scrollTo(0, y);
                  window.scrollTo(0, Math.min(y, document.documentElement.scrollHeight - window.innerHeight));
                  document.documentElement.classList.remove("am-restore");
                });
              });
            })();
          }
        });
    },
    loadMore() {
      if (this.mode === "aggregate") return;
      if (this.loading || this.loadingMore || !this.hasMore) return;
      var self = this, seq = this._reqSeq;
      this.loadingMore = true;
      Api.listImages({ folderId: this.currentFolder || null, tag: this.selectedTag, q: this.q,
                       sort: this.sort, limit: this.limit, offset: this.images.length })
        .then(function (page) {
          self.loadingMore = false;
          if (seq !== self._reqSeq) return; // 过期响应丢弃
          self._initCards(page.items);
          self.images = self.images.concat(page.items);
          self.total = page.total;
          self.hasMore = page.hasMore;
          self.summary = "已显示 " + self.images.length + " / 共 " + page.total + " 张";
          self._afterRender(function () { self._rearm("list"); });
        })
        .catch(function () { self.loadingMore = false; });
    },
    loadMoreGroups() {
      if (this.mode !== "aggregate") return; // Task 6 实现具体逻辑
    },
```

- [ ] **Step 5: gallery.html — 哨兵元素**

在聚合模式容器（`<!-- 聚合 -->` 的 `<div x-show="mode==='aggregate'" x-cloak>` 结束标签 `</div>` 之后、`</div><!-- /.page -->` 之前）插入：

```html
    <!-- 无限滚动哨兵：平铺/沉浸 -->
    <div id="am-sentinel" class="loading-more" x-show="mode!=='aggregate' && hasMore" x-cloak>
      <span class="muted" x-show="loadingMore">加载中…</span>
    </div>
    <!-- 无限滚动哨兵：聚合组列表（Task 6 启用） -->
    <div id="am-group-sentinel" class="loading-more" x-show="mode==='aggregate' && false" x-cloak>
      <span class="muted">加载中…</span>
    </div>
```

- [ ] **Step 6: style.css — 末尾追加**

```css
/* 无限滚动哨兵 */
.loading-more { padding: 16px; text-align: center; }
```

- [ ] **Step 7: 重启服务并浏览器验证**

```bash
lsof -ti:8000 | xargs kill -9 2>/dev/null; sleep 1
cd backend && (uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/am.log 2>&1 &)
curl -s http://127.0.0.1:8000/api/health
```

浏览器（强刷 `Cmd+Shift+R`）打开 `http://127.0.0.1:8000/gallery.html`：
- 首屏只加载 60 张，摘要显示「已显示 60 / 共 N 张」
- 滚动到底部自动追加下一页
- 切换目录 / 排序 / 搜索 / 标签后列表重置为第一页
- 控制台无报错

- [ ] **Step 8: 提交**

```bash
git add frontend/api.js frontend/gallery.html frontend/style.css
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "feat: 图库无限滚动 + 列表分页适配（竞态防护）"
```

---

### Task 5: 聚合接口分页 + 成员懒加载（后端）

**Files:**
- Modify: `backend/app/routers/aggregate.py`
- Test: `backend/tests/test_aggregate_api.py`（新建）

- [ ] **Step 1: 新建测试文件（失败测试）**

```python
"""聚合接口测试（组列表分页 / coverThumbs / 成员懒加载 / 页内相似聚类）。"""
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.database import get_session
from app.models import ImageAsset, WorkflowMeta
from app.routers import aggregate


def _setup(tmp: Path):
    settings.data_dir = str(tmp)
    settings.ensure_dirs()
    engine = create_engine(
        f"sqlite:///{tmp / 't.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(aggregate.router)

    def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return TestClient(app), engine


def _seed_texts(session: Session, texts: list[str]) -> None:
    n = 0
    for text in texts:
        n += 1
        im = ImageAsset(
            file_name=f"g{n}.png", file_path=f"/x/g{n}.png", abs_path=f"/x/g{n}.png",
            sha256=f"{n:064x}", width=64, height=64, file_size=10, ai_rating=float(n),
        )
        session.add(im)
        session.flush()
        session.add(WorkflowMeta(image_id=im.id, prompt=text))
    session.commit()


def _seed(session: Session) -> None:
    # A 组 8 张（验证封面截断）、B 组 2 张、C 组 1 张
    _seed_texts(session, ["prompt alpha common"] * 8 + ["prompt beta common"] * 2 + ["prompt gamma common"])


def test_by_prompt_paged_groups():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s)
        body = client.get("/api/aggregate/by-prompt?limit=2").json()
        assert set(body) >= {"items", "total", "limit", "offset", "hasMore"}
        assert body["total"] == 3 and len(body["items"]) == 2 and body["hasMore"] is True
        g = body["items"][0]
        assert set(g) == {"id", "title", "kind", "count", "maxScore", "coverThumbs"}
        assert g["count"] == 1 and g["title"] == "prompt gamma common"  # maxScore 最大者在前
        body2 = client.get("/api/aggregate/by-prompt?limit=2&offset=2").json()
        assert len(body2["items"]) == 1 and body2["hasMore"] is False


def test_cover_thumbs_capped_at_six():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s)
        items = client.get("/api/aggregate/by-prompt?limit=10").json()["items"]
        big = next(g for g in items if g["count"] == 8)
        assert len(big["coverThumbs"]) == 6
        assert all(m["thumb"].startswith("/api/images/") for m in big["coverThumbs"])


def test_group_members_paged():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s)
        items = client.get("/api/aggregate/by-prompt?limit=10").json()["items"]
        big = next(g for g in items if g["count"] == 8)
        m = client.get("/api/aggregate/by-prompt/members", params={"group": big["id"], "limit": 5}).json()
        assert m["total"] == 8 and len(m["items"]) == 5 and m["hasMore"] is True
        m2 = client.get("/api/aggregate/by-prompt/members", params={"group": big["id"], "limit": 5, "offset": 5}).json()
        assert len(m2["items"]) == 3 and m2["hasMore"] is False
        r = client.get("/api/aggregate/by-prompt/members", params={"group": "nope"})
        assert r.status_code == 404


def test_similar_clusters_within_page():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed_texts(s, [
                "a beautiful scenic mountain landscape",
                "a beautiful scenic mountain landscapes",
                "totally different city street photo",
            ])
        body = client.get("/api/aggregate/by-prompt?kind=similar&limit=10").json()
        assert body["total"] == 3  # exact 组仍为 3
        assert len(body["items"]) == 2  # 前两条相似（ratio≈0.985 ≥ 0.92）合并
        merged = next(g for g in body["items"] if g["kind"] == "similar")
        assert merged["count"] == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_aggregate_api.py -v`
Expected: FAIL（响应仍是裸数组、无 members 接口）

- [ ] **Step 3: 重写 aggregate.py**

将 [aggregate.py](file:///workspace/backend/app/routers/aggregate.py) 中 `aggregate_by_prompt` 与 `_cluster_similar` 两个函数整体替换为（`_normalize` / `_first_prompt` 保留不动）：

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models import ImageAsset, Tag, ImageTag, WorkflowMeta
from .images import to_cards


def _group_all(session: Session) -> list[dict]:
    """按提示词首条分组（内存 O(n)），按 maxScore 降序返回组列表。"""
    rows = session.exec(
        select(ImageAsset, WorkflowMeta)
        .join(WorkflowMeta, WorkflowMeta.image_id == ImageAsset.id)
        .where(
            ImageAsset.is_deleted == 0,
            WorkflowMeta.prompt != "",
        )
    ).all()

    groups: dict[str, list] = {}
    titles: dict[str, str] = {}
    for im, meta in rows:
        fp = _first_prompt(meta)
        if not fp:
            continue
        key = _normalize(fp)
        groups.setdefault(key, []).append(im)
        titles[key] = fp

    ordered = sorted(groups.items(), key=lambda kv: -max(
        (im.ai_rating or 0) for im in kv[1]
    ))
    out = []
    for key, members in ordered:
        sorted_members = sorted(members, key=lambda m: -(m.ai_rating or 0))
        out.append({"key": key, "title": titles.get(key) or "", "members": sorted_members})
    return out


def _group_payload(g: dict) -> dict:
    """组卡片：封面行直接可渲染，不携带全部成员。"""
    return {
        "id": g["key"],
        "title": g["title"],
        "kind": "exact",
        "count": len(g["members"]),
        "maxScore": g["members"][0].ai_rating or 0,
        "coverThumbs": [
            {"id": m.id, "name": m.file_name, "thumb": f"/api/images/{m.id}/thumb"}
            for m in g["members"][:6]
        ],
    }


@router.get("/by-prompt")
def aggregate_by_prompt(
    kind: str = "exact",
    limit: int = 20,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """按提示词分组（分页返回组列表；exact=相同，similar=页内相似聚类）。"""
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    all_groups = _group_all(session)
    total = len(all_groups)
    page = all_groups[offset:offset + limit]
    items = [_group_payload(g) for g in page]
    if kind == "similar":
        items = _cluster_page(items)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(page) < total,
    }


@router.get("/by-prompt/members")
def group_members(
    group: str,
    limit: int = 24,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """某提示词组的成员（展开组时懒加载、分页）。"""
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    for g in _group_all(session):
        if g["key"] != group:
            continue
        members = g["members"]
        page = members[offset:offset + limit]
        return {
            "items": to_cards(session, page),
            "total": len(members),
            "limit": limit,
            "offset": offset,
            "hasMore": offset + len(page) < len(members),
        }
    raise HTTPException(404, "group not found")


def _cluster_page(items: list[dict]) -> list[dict]:
    """页内相似聚类：仅对当前页的组两两比较（页 ≤ 100 组，毫秒级）。

    相似簇的 id 取首个子组键；members 懒加载只返回该键的成员（UI 当前仅用 exact）。
    """
    import difflib

    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    threshold = 0.92
    for i in range(n):
        for j in range(i + 1, n):
            ratio = difflib.SequenceMatcher(None, items[i]["title"], items[j]["title"]).ratio()
            if ratio >= threshold:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    out = []
    for idxs in clusters.values():
        first = items[idxs[0]]
        if len(idxs) == 1:
            out.append(first)
            continue
        thumbs = []
        for i in idxs:
            thumbs.extend(items[i]["coverThumbs"])
        out.append({
            "id": first["id"],
            "title": first["title"],
            "kind": "similar",
            "count": sum(items[i]["count"] for i in idxs),
            "maxScore": max(items[i]["maxScore"] for i in idxs),
            "coverThumbs": thumbs[:6],
        })
    out.sort(key=lambda g: -g["maxScore"])
    return out
```

同时删除文件顶部旧的 `from .images import to_card` 导入（已在上面的新导入中替换为 `to_cards`），并确认 `HTTPException` 已导入。

- [ ] **Step 4: 运行确认通过（含全量回归）**

Run: `cd backend && uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交（聚合 UI 在 Task 6 恢复）**

```bash
git add backend/app/routers/aggregate.py backend/tests/test_aggregate_api.py
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "feat: 聚合接口分页 + 组成员懒加载 + 页内相似聚类"
```

---

### Task 6: 聚合模式前端懒加载 UI

**Files:**
- Modify: `frontend/api.js`（`aggregateByPrompt`、新增 `aggregateMembers`）
- Modify: `frontend/gallery.html`（聚合状态、组卡片 HTML）

- [ ] **Step 1: api.js — 聚合接口适配**

将 `aggregateByPrompt` 替换为，并在其后新增 `aggregateMembers`：

```javascript
    aggregateByPrompt: function (opts) {
      opts = opts || {};
      var qs = [
        "kind=" + (opts.kind || "exact"),
        "limit=" + (opts.limit || 20),
        "offset=" + (opts.offset || 0)
      ];
      return req("api/aggregate/by-prompt?" + qs.join("&")).catch(function () {
        Api._fallback = true;
        var g = buildMockGroups(opts.kind === "similar");
        var off = opts.offset || 0, lim = opts.limit || 20;
        return ok({
          items: g.slice(off, off + lim),
          total: g.length,
          limit: lim,
          offset: off,
          hasMore: off + lim < g.length
        });
      });
    },

    aggregateMembers: function (group, opts) {
      opts = opts || {};
      var qs = [
        "group=" + encodeURIComponent(group),
        "limit=" + (opts.limit || 24),
        "offset=" + (opts.offset || 0)
      ];
      return req("api/aggregate/by-prompt/members?" + qs.join("&")).catch(function () {
        Api._fallback = true;
        var g = buildMockGroups(false).filter(function (x) { return x.id === group; })[0] || { members: [] };
        var off = opts.offset || 0, lim = opts.limit || 24;
        return ok({
          items: g.members.slice(off, off + lim),
          total: g.members.length,
          limit: lim,
          offset: off,
          hasMore: off + lim < g.members.length
        });
      });
    },
```

- [ ] **Step 2: gallery.html — 聚合状态与加载逻辑**

状态区追加（放在 `permModal` 行之前）：

```javascript
    groupTotal: 0, groupHasMore: false, groupLoading: false, _gSeq: 0,
```

将 `reloadGroups()` 整个方法替换为，并新增 `loadMoreGroups` / `toggleGroup` / `loadGroupMembers`（放在 `reloadGroups` 之后）：

```javascript
    reloadGroups() {
      var self = this, seq = ++this._gSeq;
      this.groupLoading = true;
      Api.aggregateByPrompt({ kind: "exact", limit: 20, offset: 0 }).then(function (page) {
        if (seq !== self._gSeq) return; // 过期响应丢弃
        self._initGroups(page.items);
        self.groups = page.items;
        self.groupTotal = page.total;
        self.groupHasMore = page.hasMore;
        self.groupLoading = false;
        self.groupCount = page.total;
        self.summary = "已显示 " + page.items.length + " / 共 " + page.total + " 组提示词";
        self._afterRender(function () { self._rearm("groups"); });
      });
    },
    loadMoreGroups() {
      if (this.mode !== "aggregate") return;
      if (this.groupLoading || !this.groupHasMore) return;
      var self = this, seq = this._gSeq;
      this.groupLoading = true;
      Api.aggregateByPrompt({ kind: "exact", limit: 20, offset: this.groups.length }).then(function (page) {
        self.groupLoading = false;
        if (seq !== self._gSeq) return;
        self._initGroups(page.items);
        self.groups = self.groups.concat(page.items);
        self.groupHasMore = page.hasMore;
        self.groupCount = page.total;
        self.summary = "已显示 " + self.groups.length + " / 共 " + page.total + " 组提示词";
        self._afterRender(function () { self._rearm("groups"); });
      }).catch(function () { self.groupLoading = false; });
    },
    _initGroups(list) {
      list.forEach(function (g) {
        g._open = false; g._members = null; g._mHasMore = false; g._mLoading = false;
      });
    },
    toggleGroup(g) {
      g._open = !g._open;
      if (g._open && g._members === null) this.loadGroupMembers(g);
    },
    loadGroupMembers(g) {
      if (g._mLoading) return;
      var self = this;
      g._mLoading = true;
      var offset = g._members === null ? 0 : g._members.length;
      Api.aggregateMembers(g.id, { limit: 24, offset: offset }).then(function (page) {
        self._initCards(page.items);
        g._members = (g._members || []).concat(page.items);
        g._mHasMore = page.hasMore;
        g._mLoading = false;
      }).catch(function () { g._mLoading = false; });
    },
```

- [ ] **Step 3: gallery.html — 组卡片 HTML 重写**

聚合容器中，「按相同提示词聚合」行替换为：

```html
      <div class="muted mb" style="display:flex;align-items:center;gap:8px">
        按相同提示词聚合：<b x-text="groupTotal"></b> 组
        <span class="muted" x-show="groupLoading" style="font-size:12px">加载中…</span>
      </div>
```

`<template x-for="g in visibleGroups()">` 整块替换为：

```html
      <template x-for="g in visibleGroups()" :key="g.id">
        <div class="card group-card">
          <div class="cover-row">
            <template x-for="m in g.coverThumbs" :key="m.id">
              <img :src="m.thumb" @click="open(m.id)" :title="m.name" loading="lazy" />
            </template>
          </div>
          <div class="g-title">
            <h4><span x-html="mark(g.title)"></span></h4>
          </div>
          <div class="g-body">
            <div class="muted" style="display:flex;justify-content:space-between;font-size:12px">
              <span x-text="g.count+' 张图片'"></span>
              <span x-text="'最高 AI '+g.maxScore"></span>
            </div>
            <button class="btn sm mt" @click="toggleGroup(g)" x-text="g._open?'收起':'展开'"></button>
            <div class="member-grid" x-show="g._open">
              <template x-for="m in (g._members||[])" :key="m.id">
                <img :src="m.thumb" @click="open(m.id)" :title="m.name" loading="lazy" />
              </template>
              <button x-show="g._mHasMore && !g._mLoading" class="btn sm"
                      @click="loadGroupMembers(g)">加载更多成员</button>
              <span class="muted" x-show="g._mLoading" style="font-size:12px;padding:8px">成员加载中…</span>
            </div>
          </div>
        </div>
      </template>
```

空状态行替换为：

```html
      <div class="empty" x-show="!groupLoading && !visibleGroups().length">没有符合条件的提示词组。</div>
```

聚合组哨兵（Task 4 中 `x-show="mode==='aggregate' && false"` 的临时占位）替换为：

```html
    <div id="am-group-sentinel" class="loading-more" x-show="mode==='aggregate' && groupHasMore" x-cloak>
      <span class="muted" x-show="groupLoading">加载中…</span>
    </div>
```

- [ ] **Step 4: 重启并浏览器验证**

重启命令同 Task 4 Step 7。验证：切到「聚合」模式 → 组列表分页加载（20 组/页）、封面行 6 张、展开某组懒加载成员（24 张/页）、「加载更多成员」可继续翻页、搜索 q 过滤已加载组、控制台无报错。

- [ ] **Step 5: 提交**

```bash
git add frontend/api.js frontend/gallery.html
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "feat: 聚合模式分组分页 + 组成员懒加载"
```

---

### Task 7: 同步提示条（替代自动重拉）

**Files:**
- Modify: `frontend/gallery.html`（`pollSync`、新增 `applySync`、提示条 HTML）
- Modify: `frontend/style.css`（追加样式）

- [ ] **Step 1: gallery.html — 替换 `pollSync`，新增 `applySync`**

```javascript
    pollSync() {
      var self = this;
      Api.getSyncVersion().then(function (v) {
        if (v === self._ver) return;
        var first = self._ver === -1;
        self._ver = v;
        if (first) return; // 首次仅建立基线，不打扰
        self.syncDirty = true; // 不自动重拉列表：顶部提示条由用户点击触发
        Api.listFolders().then(function (f) { self.folders = f; });
        Api.listTags().then(function (t) { self.tags = t; });
      });
    },
    applySync() {
      this.syncDirty = false;
      if (this.mode === "aggregate") this.reloadGroups();
      else this.loadImages();
      window.scrollTo(0, 0);
    },
```

状态区追加 `syncDirty: false,`（`permModal` 行之前）。

- [ ] **Step 2: gallery.html — 提示条元素**

`.page` 容器开头（`<div style="margin-top:12px">` 之前）插入：

```html
  <div class="sync-banner" x-show="syncDirty" x-cloak @click="applySync()">后台有更新 · 点击查看</div>
```

- [ ] **Step 3: style.css — 末尾追加**

```css
/* 同步提示条：后台扫描有更新时显示，点击刷新（不遮盖图片，占位在列表上方） */
.sync-banner {
  margin: 0 0 12px;
  padding: 8px 14px;
  border: 1px solid var(--brand);
  border-radius: 8px;
  color: var(--brand);
  font-size: 13px;
  text-align: center;
  cursor: pointer;
  user-select: none;
}
```

- [ ] **Step 4: 重启并验证**

重启后：导入/删除一张图片（触发 watcher 版本变化）→ 列表不自动刷新、滚动位置不动 → 顶部出现「后台有更新 · 点击查看」→ 点击后重载第一页回顶部。

- [ ] **Step 5: 提交**

```bash
git add frontend/gallery.html frontend/style.css
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "feat: 后台同步改为新内容提示条，不再打断浏览"
```

---

### Task 8: 返回图库补页恢复滚动

**Files:**
- Modify: `frontend/gallery.html`

- [ ] **Step 1: 新增 `_resumeScroll` 方法**

在 `loadMore()` 方法后新增：

```javascript
    // 无限滚动下的滚动恢复：循环补页直到页面高度够到目标位置（上限 50 页）
    _resumeScroll() {
      var y = this._restoreScroll;
      var enough = document.documentElement.scrollHeight - window.innerHeight >= y - 50;
      if (enough || !this.hasMore) {
        this._restoreScroll = 0; this._resumePages = 0;
        window.scrollTo(0, Math.min(y, document.documentElement.scrollHeight - window.innerHeight));
        document.documentElement.classList.remove("am-restore");
      } else if (this._resumePages < 50) {
        this._resumePages += 1;
        this.loadMore();
      } else {
        this._restoreScroll = 0; this._resumePages = 0;
        document.documentElement.classList.remove("am-restore");
      }
    },
```

- [ ] **Step 2: `loadImages` / `loadMore` 末尾挂接恢复钩子**

`loadImages()` 的 then 回调中，将 Task 4 保留的旧「单页 pin 恢复块」（`if (self._restoreScroll) { ... }` 整块）替换为：

```javascript
          if (self._restoreScroll) {
            self._afterRender(function () { self._resumeScroll(); });
          }
```

`loadMore()` 的 then 回调中，`self._afterRender(function () { self._rearm("list"); });` 替换为：

```javascript
          self._afterRender(function () {
            self._rearm("list");
            if (self._restoreScroll) self._resumeScroll();
          });
```

- [ ] **Step 3: 聚合模式返回时直接显示（无需补页）**

`init()` 中恢复 `saved` 的代码块末尾（`window.addEventListener("pageshow", ...)` 之后）追加：

```javascript
        if (self.mode === "aggregate") {
          self._restoreScroll = 0;
          document.documentElement.classList.remove("am-restore");
        }
```

- [ ] **Step 4: 重启并验证**

重启后：在图库向下滚动约 5-10 页 → 点击任意图进详情 → 浏览器后退返回图库 → 页面保持隐藏并自动补页 → 高度足够后一次性定位到原滚动位置并显示；2 秒兜底仍然生效。

- [ ] **Step 5: 提交**

```bash
git add frontend/gallery.html
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "feat: 详情页返回图库补页恢复滚动位置"
```

---

### Task 9: 查询索引迁移

**Files:**
- Modify: `backend/app/database.py`
- Test: `backend/tests/test_migrations.py`（新建）

- [ ] **Step 1: 新建失败测试**

```python
"""数据库迁移测试（查询性能索引）。"""
from sqlmodel import SQLModel, create_engine

from app import database


def test_ensure_indexes_creates_all_and_idempotent():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        database._ensure_indexes(conn)
        database._ensure_indexes(conn)  # 幂等：重复执行不报错
    with engine.connect() as conn:
        names = {r[0] for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
    assert {"ix_image_folder", "ix_image_ai_rating", "ix_image_rating"} <= names
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_migrations.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_ensure_indexes'`

- [ ] **Step 3: 实现**

[database.py](file:///workspace/backend/app/database.py) 顶部追加导入：

```python
from sqlalchemy import text
```

`_migrate_sqlite` 函数之后新增：

```python
# 查询性能索引：目录过滤 + 评分排序（幂等创建）
_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_image_folder ON imageasset(folder_id)",
    "CREATE INDEX IF NOT EXISTS ix_image_ai_rating ON imageasset(ai_rating)",
    "CREATE INDEX IF NOT EXISTS ix_image_rating ON imageasset(rating)",
)


def _ensure_indexes(conn) -> None:
    for ddl in _INDEX_DDL:
        conn.execute(text(ddl))
```

`init_db()` 改为（create_all 之后建索引，新旧库都覆盖）：

```python
def init_db() -> None:
    """创建数据表与运行目录（幂等）。"""
    settings.ensure_dirs()
    _migrate_sqlite()
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        _ensure_indexes(conn)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/database.py backend/tests/test_migrations.py
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "perf: 图片表目录/评分索引迁移"
```

---

### Task 10: 造数压测脚本

**Files:**
- Create: `backend/scripts/seed_stress.py`

- [ ] **Step 1: 编写脚本**

```python
"""造数压测：向 data/artmirror.db 插入大量图片记录与占位缩略图。

用法（backend/ 目录下执行）：
    uv run python scripts/seed_stress.py            # 插入 10000 条压测数据
    uv run python scripts/seed_stress.py --n 2000   # 自定义数量
    uv run python scripts/seed_stress.py --clean    # 清理全部压测数据
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine, init_db  # noqa: E402
from app.models import (  # noqa: E402
    ImageAsset,
    ImageTag,
    PromptTranslation,
    RatingRecord,
    ReversePrompt,
    Tag,
    WorkflowMeta,
)

PREFIX = "stress_"
CHUNK = 500

PROMPTS = [
    "masterpiece, best quality, 1girl, silver hair, detailed eyes, cherry blossoms",
    "epic landscape, mountains at sunset, dramatic clouds, ultra detailed, 8k",
    "cyberpunk city street, neon lights, rain reflections, cinematic lighting",
    "portrait of a samurai, ink wash style, dramatic shading, monochrome",
    "cozy reading nook, warm sunlight, plants, watercolor illustration",
    "space station orbiting a gas giant, sci-fi concept art, volumetric light",
    "cute corgi in a tiny wizard hat, sticker style, flat colors",
    "ancient forest temple, mossy stones, god rays, fantasy environment",
    "racing car on a wet track at night, motion blur, headlight flare",
    "bowl of ramen, food photography, steam, shallow depth of field",
    "ice dragon flying over a frozen fjord, matte painting",
    "art nouveau poster of a dancer, gold accents, elegant lines",
    "underwater coral reef, tropical fish, sunbeams from surface",
    "abandoned subway station, graffiti, urban exploration photography",
    "cherry blossom festival at night, paper lanterns, crowd silhouettes",
    "steampunk airship workshop, brass gears, blueprints scattered",
    "minimalist zen garden, raked sand, single maple tree, morning mist",
    "knight in ornate armor standing in a cathedral, dramatic light",
    "pixel art island floating in the sky, retro game style",
    "northern lights over a snowy cabin, long exposure photography",
]


def _thumb(sha: str, tone: int) -> None:
    p = settings.thumbs_dir / f"{sha}.webp"
    if not p.exists():
        Image.new("RGB", (160, 160), (tone % 256, 60, 90)).save(str(p), "WEBP")


def seed(session: Session, n: int) -> None:
    existing = [im for im in session.exec(select(ImageAsset)).all()
                 if im.file_name.startswith(PREFIX)]
    if existing:
        print(f"已存在 {len(existing)} 条压测数据，请先执行 --clean")
        return
    random.seed(42)
    models = [Tag(name=f"{PREFIX}model_{k}", category="model") for k in range(5)]
    loras = [Tag(name=f"{PREFIX}lora_{k}", category="lora") for k in range(8)]
    for t in models + loras:
        session.add(t)
    session.flush()

    for i in range(n):
        prompt = PROMPTS[i % len(PROMPTS)]
        sha = f"{i:064x}"
        im = ImageAsset(
            file_name=f"{PREFIX}{i:05d}.png",
            file_path=f"/stress/{PREFIX}{i:05d}.png",
            abs_path=f"/stress/{PREFIX}{i:05d}.png",
            sha256=sha,
            width=1024, height=1024, file_size=1_500_000 + i,
            ai_rating=(random.random() * 100) if i % 3 else None,
        )
        session.add(im)
        session.flush()
        session.add(WorkflowMeta(
            image_id=im.id, prompt=prompt, negative_prompt="lowres, bad anatomy",
            origin_prompts_json=json.dumps([prompt], ensure_ascii=False),
            steps=20 + i % 10, cfg=6.5, sampler="euler", scheduler="normal", seed=i,
        ))
        session.add(ImageTag(image_id=im.id, tag_id=random.choice(models).id))
        if random.random() < 0.5:
            session.add(ImageTag(image_id=im.id, tag_id=random.choice(loras).id))
        if i % 10 == 0:
            session.add(ReversePrompt(image_id=im.id, text="a stress test reverse prompt"))
            session.add(RatingRecord(image_id=im.id, rating_type="ai", score=80, reason="压测评分依据"))
            session.add(PromptTranslation(image_id=im.id, prompt_kind="origin", lang="zh", text="压测译文"))
        _thumb(sha, i)
        if (i + 1) % CHUNK == 0:
            session.commit()
            print(f"  已插入 {i + 1}/{n}")
    session.commit()
    print(f"完成：插入 {n} 条压测数据")


def clean(session: Session) -> None:
    ims = [im for im in session.exec(select(ImageAsset)).all()
           if im.file_name.startswith(PREFIX)]
    if not ims:
        print("无压测数据")
        return
    ids = [im.id for im in ims]
    shas = [im.sha256 for im in ims]
    for model in (WorkflowMeta, ReversePrompt, PromptTranslation, RatingRecord, ImageTag):
        for row in session.exec(select(model).where(model.image_id.in_(ids))).all():
            session.delete(row)
    for im in ims:
        session.delete(im)
    for tag in session.exec(select(Tag)).all():
        if tag.name.startswith(PREFIX):
            session.delete(tag)
    session.commit()
    removed = 0
    for sha in shas:
        p = settings.thumbs_dir / f"{sha}.webp"
        if p.exists():
            p.unlink()
            removed += 1
    print(f"已清理 {len(ims)} 条记录、{removed} 个缩略图")


def main() -> None:
    ap = argparse.ArgumentParser(description="图库压测造数")
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--clean", action="store_true")
    args = ap.parse_args()
    init_db()
    with Session(engine) as session:
        if args.clean:
            clean(session)
        else:
            seed(session, args.n)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 小规模验证**

```bash
cd backend && uv run python scripts/seed_stress.py --n 200
uv run python scripts/seed_stress.py --clean
```

Expected: 输出「完成：插入 200 条压测数据」→「已清理 200 条记录、200 个缩略图」

- [ ] **Step 3: 提交**

```bash
git add backend/scripts/seed_stress.py
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "feat: 一万张压测造数脚本 seed_stress"
```

---

### Task 11: 端到端验收 + 功能清单更新

**Files:**
- Modify: `docs/功能清单.md`

- [ ] **Step 1: 造数 1 万张并重启**

```bash
cd backend && uv run python scripts/seed_stress.py
lsof -ti:8000 | xargs kill -9 2>/dev/null; sleep 1
(uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/am.log 2>&1 &)
curl -s http://127.0.0.1:8000/api/health
```

- [ ] **Step 2: 接口计时（目标 < 100ms）**

```bash
curl -s -o /dev/null -w "首页: %{time_total}s\n" "http://127.0.0.1:8000/api/images?limit=60&offset=0"
curl -s -o /dev/null -w "翻页: %{time_total}s\n" "http://127.0.0.1:8000/api/images?limit=60&offset=9940"
curl -s -o /dev/null -w "聚合: %{time_total}s\n" "http://127.0.0.1:8000/api/aggregate/by-prompt?limit=20"
curl -s "http://127.0.0.1:8000/api/images?limit=2" | head -c 200
```

- [ ] **Step 3: 浏览器实测（强刷）**

打开 `http://127.0.0.1:8000/gallery.html`：首屏 < 1s 可交互；持续滚动流畅追加；进详情返回恢复位置；聚合模式展开懒加载；导入/删除后出现提示条；控制台无报错。

- [ ] **Step 4: 清理压测数据 + 全量测试**

```bash
cd backend && uv run python scripts/seed_stress.py --clean
uv run pytest -q
```

- [ ] **Step 5: 更新功能清单**

[功能清单.md](file:///workspace/docs/功能清单.md) 图库页「浏览与检索」分类追加：

```markdown
- [x] 大库分页加载：列表接口分页（60 张/页）+ 无限滚动（IntersectionObserver 预加载 600px）
- [x] 大库性能：卡片数据批量组装（消除 N+1 查询）、卡片瘦身（详情字段仅详情页返回）、查询索引
- [x] 后台更新提示条：扫描同步不再自动重拉列表，顶部提示「后台有更新 · 点击查看」
- [x] 详情页返回：无限滚动下自动补页恢复滚动位置（上限 50 页）
```

「聚合」分类追加：

```markdown
- [x] 聚合分页与懒加载：组列表分页（20 组/页）、封面行 ≤6 张、组内成员展开懒加载（24 张/页）
```

「更新记录」表格首行插入：

```markdown
| 2026-08-28 | 图库万张性能优化 | 新增：列表分页 + 无限滚动 + 批量组装去 N+1 + 卡片瘦身 + 查询索引 + 缩略图缓存头；后台同步改提示条；聚合分页与成员懒加载；详情页返回补页恢复滚动 |
```

- [ ] **Step 6: 提交**

```bash
git add docs/功能清单.md
git -c user.name="ShenZiLi" -c user.email="zilishen@qq.com" commit -m "docs: 功能清单补充图库性能优化功能点"
```
