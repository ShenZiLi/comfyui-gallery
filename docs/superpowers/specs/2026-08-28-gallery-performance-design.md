# 图库页一万张图片性能优化 · 设计文档

日期：2026-08-28
状态：已与用户逐节确认（方案 A）

## 背景与问题

预设图库规模为一万张图片时，现状存在两个核心瓶颈：

1. **后端 N+1 查询**：`GET /api/images` 一次性返回全部图片；`to_card()` 对每张图发起 5 次独立 SQL（WorkflowMeta / ReversePrompt / PromptTranslation / RatingRecord / Tags）。一万张 ≈ 5 万+ 次查询，响应体携带全部提示词/翻译/参数，体积巨大。
2. **前端全量渲染**：一万张卡片全部进入 DOM（每卡 30+ 节点 → 30 万+ 节点），Alpine `x-for` 全量渲染；3 秒轮询发现版本变化即整页重拉全部数据并重渲染。

聚合模式同样存在 N+1（每组每成员调用 `to_card`），且 `similar` 全局聚类为组数平方级的字符串两两比较。

## 目标

- 一万张图片下图库首屏与翻页流畅可用
- `GET /api/images` 首页/翻页请求均 < 100ms（本机）
- 首屏可交互 < 1s（浏览器）
- 浏览体验：无限滚动；后台扫描更新不打断浏览；详情页返回可恢复滚动位置

非目标（本次不做）：瀑布流虚拟滚动、增量插入式同步、详情页优化。

## 方案选择

- **方案 A（采纳）**：分页 API + 批量查询 + 无限滚动。保留 Alpine 无构建技术栈，覆盖两大瓶颈，风险可控。
- 方案 B（否决）：A + 虚拟滚动。动态高度卡片 + 多列瀑布流虚拟化复杂度极高，收益被多数浏览行为早期化稀释。
- 方案 C（否决）：仅后端优化不分页。前端仍需一次性渲染全部数据，治标不治本。

用户决策记录：无限滚动（而非分页器/加载更多）；聚合模式本次一并优化；同步采用「新内容提示条」；返回恢复采用「补加载到目标位」；验收采用「造数压测」。

## 后端设计

### 1. 列表分页协议

`GET /api/images` 新增查询参数：

- `limit`：默认 60，上限 200（超出截断为 200）
- `offset`：默认 0

响应结构由裸数组改为：

```json
{ "items": [...], "total": 10000, "limit": 60, "offset": 0, "hasMore": true }
```

- `total` 用同一 WHERE 条件 `count(*)` 计算
- `hasMore = offset + len(items) < total`
- 现有过滤/排序参数（`folderId` / `tag` / `q` / `sort`）不变；排序由后端唯一负责

### 2. 批量组装 `to_cards()`

新增 `to_cards(session, images) -> list[dict]`，整页固定 6 次查询（1 次主查询 + 5 次批量查询，与页大小无关）：

| 数据 | 批量方式 |
|---|---|
| WorkflowMeta | `WHERE image_id IN (页内 ids)` |
| ReversePrompt | IN 查询，内存取每图 `max(id)` 的最新一条 |
| PromptTranslation (origin/zh) | IN 查询 |
| RatingRecord (ai) | IN 查询，内存取每图最新一条的理由 |
| Tags | `Tag JOIN ImageTag`，`ImageTag.image_id IN ids`，内存分组 |

单图 `to_card(session, im)` 改为 `to_cards(session, [im])[0]`，逻辑收敛到一处；所有单图接口（详情/评分/删除/AI 解析）行为不变。

### 3. 列表卡片瘦身

列表响应移除仅详情页使用的字段：`negative`、`negativePrompts`、`aiNegative`、`aiReason`、`translationZH`、`params`。

保留（卡片在用）：`id`、`folderId`、`name`、`width`、`height`、`fileSize`、`rating`、`aiRating`、`prompt`、`originPrompts`、`aiPrompt`、`aiPrompts`、`reversePrompt`、`tags`、`thumb`。

`GET /api/images/{id}`（`to_detail`）继续返回全量字段。

### 4. 聚合接口分页化

- `GET /api/aggregate/by-prompt?kind=&limit=&offset=`：分页返回组列表（默认每页 20 组），每组仅含
  `{id, title, kind, count, maxScore, coverThumbs: [{id, thumb} × ≤6]}`，不再携带全部成员
- 新增 `GET /api/aggregate/by-prompt/members?group=<key>&limit=&offset=`：展开组时懒加载成员（默认每页 24 张，返回同列表协议结构）；group 为 normalize 后的提示词首条（作为 query 参数传递，避免路径编码问题）；分组在内存重算（万行 O(n)）
- `similar` 聚类改为**页内聚类**：仅对当前页返回的组两两比较（60 组 ≈ 1770 次 SequenceMatcher，毫秒级），避免组数平方级全局比较

### 5. 索引与缓存

- `database.py` 的 `_migrate_sqlite()` 追加幂等索引：
  `CREATE INDEX IF NOT EXISTS ix_image_folder ON imageasset(folder_id)`、
  `ix_image_ai_rating ON imageasset(ai_rating)`、
  `ix_image_rating ON imageasset(rating)`
- `/api/images/{id}/thumb` 响应头：`Cache-Control: public, max-age=31536000, immutable`（缩略图按 sha256 内容寻址，不可变；不影响前端静态资源 no-cache 策略）

## 前端设计

### 1. 无限滚动（平铺/沉浸）

- Gallery 状态新增：`limit=60`、`offset`、`total`、`hasMore`、`loadingMore`
- 列表底部哨兵元素 + `IntersectionObserver`（`rootMargin: 600px` 预加载）触发 `loadMore()` 追加下一页
- `loadImages()`（筛选/排序/搜索/目录变化）重置为第一页并清空已加载列表
- 摘要显示「已显示 X / 共 Y 张」

### 2. 请求竞态防护

- 请求序号 token：`loadImages` 自增 `_reqSeq`，响应回调校验自身是否最新，过期响应丢弃
- `loadMore` 以 `loadingMore` 标志防重入
- 保留现有 300ms 搜索防抖

### 3. 同步提示条

`pollSync` 检测版本变化时不再自动重拉列表：

- 顶部（工具栏下方）固定提示条「后台有更新 · 点击查看」，点击后重载第一页回顶部
- `folders` / `tags` 轻量计数接口仍静默刷新
- 聚合模式同样适用

### 4. 返回图库补页恢复滚动

沿用 `am_gallery_state`（scroll/mode/folder/sort/q/tag）与 `am-restore` 隐藏机制，恢复流程扩展：

1. 拉第一页渲染 → 检查 `scrollHeight` 是否可达保存的 `scrollY`
2. 不足且 `hasMore` → 循环继续加载下一页，期间保持隐藏
3. 高度足够后一次性 `scrollTo` 定位并显示
4. 补页上限 50 页 + 现有 2 秒兜底保留，防死循环

### 5. 聚合模式前端

- 组列表无限滚动（每页 20 组）
- 组展开时调用成员接口懒加载（每页 24 张），组内滚动可继续翻页
- 封面行用 `coverThumbs` 渲染

### 6. Mock 回退适配

`Api.listImages` 内部将 Mock 回退结果统一包装为 `{items, total, hasMore}` 结构，页面代码不感知差异。

## 测试与验收

### pytest（新增）

- 分页：默认 limit、limit 上限截断、offset 翻页、`total`/`hasMore` 正确
- 批量组装：`to_cards` 与逐图结果字段等价（瘦身字段除外）；列表响应不含瘦身字段
- 聚合：组列表分页、`coverThumbs ≤ 6`、成员接口翻页
- 缩略图响应头含 `Cache-Control: immutable`

### 造数压测

新增 `backend/scripts/seed_stress.py`：

- 插入 10,000 条 ImageAsset + WorkflowMeta（真实规模提示词文本）+ 标签关联 + 少量反推/翻译/AI 评分记录
- Pillow 生成占位缩略图 `data/thumbs/<sha>.webp`
- 幂等可重复运行；`--clean` 清理压测数据

### 性能验收目标（本机，1 万张）

| 指标 | 目标 |
|---|---|
| `GET /api/images?limit=60` 首页 | < 100ms |
| 翻页请求 | < 100ms |
| 首屏可交互（浏览器） | < 1s |
| 滚动加载下一页 | 无可感知卡顿 |

验收流程：造数 → 重启服务 → curl 计时 → 浏览器实测（滚动/返回恢复/聚合展开）→ `--clean` 清理 → 全量 pytest → 更新 `docs/功能清单.md`（新增功能点 + 更新记录一行）。

## 实施边界

- 涉及文件：`backend/app/routers/images.py`、`backend/app/routers/aggregate.py`、`backend/app/database.py`、`backend/scripts/seed_stress.py`（新增）、`frontend/gallery.html`、`frontend/api.js`、`backend/tests/`
- 每次改动后按 AGENTS.md 强制流程重启服务验证；改动提交至 dev 分支
- 图片不可被遮盖约束不变（提示条位于工具栏区域，不遮盖图片）
