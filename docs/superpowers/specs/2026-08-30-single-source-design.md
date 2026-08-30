# 设计文档：Web 端与 ComfyUI 插件统一底层代码

- 日期：2026-08-30
- 状态：已批准（brainstorming 完成）
- 方案：纯生成物（副本不提交 git，由同步脚本从唯一真源生成）

## 背景与问题

ArtMirror 现有两套代码，底层实为同源：

| 端 | 后端 | 前端 |
| --- | --- | --- |
| Web 端 | `backend/app/` | `frontend/` |
| ComfyUI 插件 | `comfyui-plugin/artmirror_app/`（backend/app 副本） | `comfyui-plugin/static/`（frontend 副本） |

当前用 `sync_backend.py` / `sync_frontend.py` 做**整目录覆盖拷贝**，但：

1. **副本提交进主仓库 git**——同一份代码在 git 里存两份，改动需手动同步两份，易漂移（历史提交 9715360 即手工同步了两份）。
2. 同步**手动触发**，无校验，漏跑即插件运行旧版。
3. 副本可被手改，产生隐性分叉。

**目标**：一处改底层代码（`backend/` 或 `frontend/`），两个操作端都生效；git 只维护一份真源。

## 约束（已与用户确认）

1. **插件自包含**：`comfyui-plugin/` 必须保持独立、可分发（可 `git subtree split` 拆为独立仓库发布 Comfy Registry），**运行时不能引用主仓库路径**（不用软链接/junction/symlink 指向 backend/frontend）。
2. **副本为生成物**：`artmirror_app/` 与 `static/` 不提交进主仓库 git，由脚本从真源生成。
3. **手动一键同步**：不引入文件监听自动同步，也不引入 git 提交钩子。

## 目标目录结构

```
ArtMirror/（主仓库，git 只维护一份真源）
├── backend/app/        # ★ 唯一真源：后端（FastAPI）
├── frontend/           # ★ 唯一真源：前端（无构建静态页）
└── comfyui-plugin/
    ├── artmirror_app/  # 生成物：由 backend/app 生成（.gitignore，不提交）
    ├── static/         # 生成物：由 frontend 生成（.gitignore，不提交）
    ├── __init__.py / server.py / proxy.py / artmirror_embed.py / comfy_paths.py
    ├── web/ tests/ pyproject.toml README.md
    └── sync_backend.py / sync_frontend.py / sync_all.py
```

## 设计

### 1. Git 调整

- `comfyui-plugin/.gitignore` 追加两行：
  - `artmirror_app/`
  - `static/`
- 执行 `git rm -r --cached comfyui-plugin/artmirror_app comfyui-plugin/static`（移除 git 跟踪，**保留工作区文件**）。
- 结果：主仓库 git 中不再出现副本文件；插件专属代码（`__init__.py`、`server.py`、`proxy.py`、`artmirror_embed.py`、`comfy_paths.py`、`web/`、`tests/`、`pyproject.toml`、`README.md`、`sync_*.py`）继续跟踪。

### 2. 副本标识（防手改）

- `artmirror_app/__init__.py` 已有标识（同步脚本写入"勿手改"声明），保留。
- `static/` 由同步脚本写入 `.am-synced` 标识文件，内容含同步时间与来源路径。

### 3. 同步脚本

保留现有 `sync_backend.py`（`backend/app → artmirror_app/`）与 `sync_frontend.py`（`frontend/ → static/`）的整目录覆盖逻辑，并补充：

- `sync_backend.py`：生成后写入 `artmirror_app/__init__.py` 标识（已有）。
- `sync_frontend.py`：生成后写入 `static/.am-synced`。
- 新增 `sync_all.py`：顺序执行两个同步 → 打印摘要（路径、文件数）→ 支持 `--check`：不写副本，仅校验副本与真源逐文件一致（报告差异、退出码非 0 表示漂移）。

`--check` 用于发布/CI 前确认副本为最新，防止漏同步。

### 4. 开发工作流

1. 改 `backend/app` 或 `frontend/`。
2. 跑 `python comfyui-plugin/sync_all.py` 生成/更新副本。
3. 后端改动：重启 ComfyUI（进程内 Python 需重启加载）；前端改动：浏览器强刷（`Ctrl+Shift+R`）。

> 新克隆/新环境首次使用：副本在 git 中不存在，必须先跑 `sync_all.py` 生成，再部署到 ComfyUI `custom_nodes/`。

README（`comfyui-plugin/README.md` 开发章节）补记此约定：改主代码后必须跑 `sync_all.py`。

### 5. 发布流程（Comfy Registry）

`git subtree split` 拆分前**必须先跑 `sync_all.py`**（否则独立仓库缺副本）。顺序：

1. `python comfyui-plugin/sync_all.py`（生成最新副本）
2. `git subtree split --prefix=comfyui-plugin -b <plugin-branch>`
3. 在独立仓库分支提交/发布（副本随 split 进入独立仓库，可独立分发）

> 注：`artmirror_app/`、`static/` 在主仓库被 `.gitignore` 忽略，但 `git subtree split` 会按**工作树内容**打包，因此本地生成的副本会被包含进独立仓库——这是"自包含"与"真源唯一"的衔接点。

### 6. 测试与验证

- 插件现有测试（22 例）继续通过。
- 扩展同步一致性测试：对真源做一处改动 → 跑同步 → 断言副本与真源逐文件一致；`sync_all.py --check` 在副本一致时退出码 0、不一致时非 0。
- 验证流程（手工）：改 `frontend/style.css` 一处 → `sync_all.py` → 确认 `static/style.css` 同步 → ComfyUI 强刷生效。

## 不做的事（YAGNI）

- 不做开发时运行时引用主仓库（方案 B，已被否决）。
- 不做文件监听自动同步（用户选择手动）。
- 不做 git 提交钩子自动同步（用户选择手动）。
- 不引入独立插件仓库 + subtree 双仓库长期维护（方案 C，已被否决）。
- 不改动插件专属代码与主仓库的边界（`artmirror_embed`、`proxy`、`server`、`comfy_paths` 等本就单源）。
