# 图片目录管理重构 + 本地实时同步 实施计划

## 一、需求概述

修复「图片目录」管理的设计问题，把「录入」改为「链接本地路径 + 实时同步」：

1. **删除路径输入框** —— 不再手动粘贴/输入绝对路径。
2. **点击「添加」打开文件夹选择器** —— 采用服务端目录浏览器（用户已确认）：后端提供目录浏览接口，前端弹「文件管理器式」弹窗选文件夹，能拿到绝对路径。
3. **添加成功后下方展示路径列表，支持删除**，删除后同步更新「已扫描的文件夹」。
4. **本地文件增删实时同步图库** —— 入库存的是**对本地路径的链接**（非拷贝导入），当本地图片新增/删除时，图库实时反映状态。

## 二、现状分析（Phase 1 结论）

已读关键文件：
- `backend/app/routers/settings.py`：`scanRoots`（JSON 存 `scan_roots` 键）、`_set/_get`、`update_settings` 全量替换 roots 并可触发 `scan_all`。
- `backend/app/services/scanner.py`：`get_scan_roots/save_scan_roots`；`scan()` 递归建 `Folder`（`path`=相对根目录）、为每图写 `ImageAsset(abs_path 绝对, file_path 相对, sha256, is_deleted)`、生成缩略图、软删已消失文件。
- `frontend/settings.html`：图片目录卡片含**手动文本框 + 添加**；`cfg.scanRoots` 以 chips 展示、`removeRoot(i)`；下方展示 `scanned`（来自 `/api/folders`）。
- `frontend/api.js`：`listFolders/listTags/listImages/getSettings/updateSettings/aggregateByPrompt/dimensionGroups`。
- `frontend/gallery.html`：文件夹选用 `f.name`；图库按需刷新，无实时同步。

已知缺陷/约束：
- 浏览器本地 Web 应用拿不到本地绝对路径 → 必须走后端目录浏览。
- `Folder.path` 目前是**相对**路径，多根目录下会碰撞；不利于按根目录清理。
- 当前删除本地文件仅在手动「扫描」后生效（软删），非实时。

## 三、总体设计（决策）

- **链接式入库**：延续现有以 `abs_path` 链接本地文件的模型；**新增实时同步**（后台定时增量扫描 + 版本号 + 前端轮询），达成“本地增删实时反映”。
- **Folder 改为绝对路径**：`Folder.path` 存绝对目录路径（name=basename），消除多根碰撞、支撑按根清理与目录浏览复用。
- **目录浏览器**：新增 `/api/fs/**` 端点，前端弹服务端目录树弹窗选文件夹。
- **根目录管理**：新增「添加根」「删除根」端点；删除根时软删该根下图片并清理其目录节点。

## 四、后端改动

| 文件 | 改动 |
|------|------|
| `app/services/scanner.py` | ① `_ensure_folders`：`Folder.path` 改为**绝对目录路径**（`name=basename`），映射键为绝对路径；② 新增 `unlink_root(session, root: Path)`：软删该根下 `ImageAsset`（`abs_path` 以根绝对路径为前缀）并删除其 `Folder` 节点；③ 新增线程安全的 `scan_roots(session, roots)` 复用现有 `scan_all`（加 `threading.Lock` 串行化）。 |
| `app/services/watcher.py`（新） | 后台线程：循环每 `SYNC_INTERVAL`（默认 5s）对每个注册根做一次**增量扫描**（新/更新/删除计数），若变动 `>0` 则递增模块级 `SYNC_VERSION`；提供 `get_version()`；`start(engine)/stop()`。用独立 `Session(engine)`（`check_same_thread=False`）。 |
| `app/main.py` | `startup`：`init_db()` 后调用 `watcher.start(engine)`；`shutdown`：`watcher.stop()`。 |
| `app/routers/settings.py` | 新增端点：① `POST /api/settings/roots` `{path}`：校验目录存在→追加进 `scan_roots`→立即 `scan(root)`→返回 `{roots, scanned}`；② `DELETE /api/settings/roots` `{path}`：从 `scan_roots` 移除→`unlink_root`→返回 `{roots, scanned}`。保留 `GET /api/settings`（返回 `scanRoots` + llm 角色配置）、`POST /api/settings`（LLM/角色配置 + 可选 `scan` 全量重扫）。 |
| `app/routers/fs.py`（新） | 目录浏览器端点：① `GET /api/fs/roots`：初始浏览根（mac 常用 `$HOME`、`/Volumes`、`/`）；返回 `[{name, path, isDir}]`；② `GET /api/fs/list?path=...`：列出该目录的直接子目录 `[{name, path, isDir}]`，`path` 为空时取 home；含 `parent`（上级路径，可为空）；路径统一 `Path.resolve()` 归一，拒绝非法。 |
| `app/routers/sync.py`（新） | `GET /api/sync/version`：返回 `{"version": watcher.get_version()}`，供前端轮询判断是否需要刷新。 |
| `app/routers/folders.py` | `list_folders` 返回 `name=basename`、`path`=绝对路径（`id/parentId/count` 不变）。 |
| `pyproject.toml` | 无需新增依赖（实时同步用标准库 `threading`，目录浏览用 `Pathlib`）。 |

> 说明：`watcher` 的后台增量扫描与前端手动“立即扫描”可能并发写 SQLite，用模块级 `threading.Lock` 在 `scan_roots/scan_all` 与 watcher 间串行化；本地单机 SQLite 无并发压力。

## 五、前端改动

| 文件 | 改动 |
|------|------|
| `frontend/api.js` | 新增 `listFsRoots()/listFsDir(path)/addRoot(path)/removeRoot(path)/getSyncVersion()`；mock 回退：addRoot/removeRoot 仅改本地 `Mock`（`scanRoots` 客户端维护），listFs* 返回占位目录。 |
| `frontend/settings.html` 图片目录卡片 | ① **删除手动文本框**；② 改为 `导入目录` 按钮 → 打开服务端目录浏览器**弹窗**（面包屑/上级/子目录列表/「选择此文件夹」），选中即 `addRoot(path)` 并立即入库；③ 已注册根目录以**路径行列表**（含删除 `×`）在下方展示（弹窗关闭后刷新）；④ 删除根 → `removeRoot(path)` 并刷新 `scanned` 置空+重拉 `/api/folders`；⑤ 保留 `立即重新扫描`（`scan` 全量）+ `正在扫描` 进度；⑥ 轮询 `/api/sync/version`，变化时刷新 `scanned`。 |
| `frontend/gallery.html` | 新增轮询：每 3s 调 `getSyncVersion()`，与上次不同则 `loadImages()`（聚合模式另 `reloadGroups()`）；文件夹下拉显示 `f.name`（已为 basename）。 |
| `frontend/style.css` | 新增 `fs-modal`（目录树弹窗）、`root-row`（路径行 + 删除）等少量样式。 |

> 前端目录浏览器为**服务端驱动**：modal 内每层目录先请求 `/api/fs/roots` 或 `/api/fs/list`，展示子目录名；点击进入、面包屑/`上级`返回；底部「选择此文件夹」提交该绝对路径。

## 六、假设与决策

- **文件夹选择**：采用服务端目录浏览器（用户已确认），不用 OS 原生 `showDirectoryPicker`（后者拿不到绝对路径，无法实时同步）。
- **实时同步方案**：后台定时增量扫描 + 版本号 + 前端 3s 轮询（近实时、无新增依赖），而非 OS 文件监听(watchdog) —— 更少依赖、行为可预期。
- **Folder.path 改绝对路径**：旧数据为相对路径，仅在测试库/自建数据上运行，直接重建即可，无需迁移脚本。
- **删除根**：软删该根下图片（`is_deleted=1`）+ 删除该根目录节点，符合“解链本地地址”。
- 单机/局域网个人使用，目录浏览不做额外权限约束（本机就是用户自有目录）。
- 缩略图仍由本地生成（`data/thumbs/<sha>.webp`），图库预览/下载走 `/api/images/{id}/file`（直接流式该本地文件，链路共享同一文件）。

## 七、验证

后端（`uv run pytest`）：
1. `fs`：`/api/fs/roots` 返回本地根；`/api/fs/list?path=...` 返回子目录且 `parent` 正确。
2. `settings/roots`：`POST` 添加存在目录→`scanRoots` 追加、`scanned` 更新；`DELETE` 移除→该根下图片 `is_deleted=1`、`scanned` 剔除；重复添加/不存在的目录报 400。
3. `scanner`：多根目录建 `Folder.path` 为绝对路径；`unlink_root` 正确清理。
4. `sync`：`/api/sync/version` 返回整数；新增/删除本地文件后 version 递增。
5. 端到端 curl：注册根→`/api/images` 出现图片→删除本地文件→等 ≤5s→version+1→`/api/images` 不再含该图。

前端：
6. 打开设置页：图片目录卡片无文本框；点「导入目录」弹服务端目录浏览器，选文件夹后下方出现路径行、`已扫描的文件夹` 更新。
7. 删除路径行 → 图库文件夹下拉/列表同步消失。
8. 图库页在本地增删文件后 3s 内自动刷新（实时同步）。
9. 移动端/窄屏下 目录浏览器 modal 与路径行可操作、主题（明暗）正常。

## 八、落地文件清单

- 新增：`backend/app/services/watcher.py`、`backend/app/routers/fs.py`、`backend/app/routers/sync.py`
- 修改：`backend/app/services/scanner.py`、`backend/app/main.py`、`backend/app/routers/settings.py`、`backend/app/routers/folders.py`
- 前端修改：`frontend/api.js`、`frontend/settings.html`、`frontend/gallery.html`、`frontend/style.css`
- 新增测试：`backend/tests/test_fs.py`、`backend/tests/test_roots_sync.py`（或并入 `test_scanner.py`）