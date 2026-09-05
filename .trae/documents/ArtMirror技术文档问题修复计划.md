# ArtMirror 画镜技术文档 · 问题修复计划

## 目标

以 **`C:\Project\Code\comfyui-gallery`（dev-rh 分支）当前代码为基准**，逐项审查
`C:\Project\Code\ArtMirror\ArtMirror画镜_技术文档.md`，找出文档与实际代码的分歧，
产出一份「问题 + 改动方案」计划表，然后逐个修复。

> 文档当前存放在 **ArtMirror 仓库**（`C:\Project\Code\ArtMirror`，dev-plugin），
> 而我们校准的基准是 **comfyui-gallery 仓库**。修复过程中文档文件本身归属哪个仓库，
> 由第 0 项决定（见下）。问题清单以内容准确性为核心，不纠结文档物理位置。

---

## 结论速览（先看这个）

这份文档**严重过时且与实际代码不符**，核心内容分两类：

- **A 类 · 文档写的是「一次性试点/外部脚本工作流」**：大量引用 macOS 路径
  （`/Users/xxx/WorkBuddy/...`）、`work/gallery_ref` 下的一堆只读脚本
  （`scan_stats.py` / `backfill_meta.py` / `apply_artmirror_patch.py` 等）、`8100` 端口、
  `~/图片提示词库` 本机资产库。这些在**当前两个仓库里都不存在**，属于旧的试点环境记录。
- **B 类 · 文档声称「已实现的补丁/功能」在真实代码里不存在**：
  解析器补丁（JjkText、22 个中文负面词、mosaic/censored、`_resolve_seed`、`noise_seed`）、
  前端布局（`.vp` 舞台、`rebalanceLayout`、`.detail-left/.detail-info`、360px 统一列）——
  **grep 全库零命中**，属于「从未发生」或「换了实现方案」。

---

## 问题矩阵 + 修复方案（逐项）

> 每项含：**P**（问题证据，来自 Phase-1 实测）+ **F**（修复动作）。修复按编号顺序执行。

### 第 0 项 · 先定文档物理归属（前置决策）
- **P**：文档在 ArtMirror 仓库，校准基准是 comfyui-gallery。两仓库 frontend 已分叉
  （comfyui-gallery 领先：SpaceX 主题、compress 服务等；ArtMirror 落后 1213 行前端差异）。
- **F**：向用户确认文档修改落点：
  - **选项 A（推荐）**：文档以 comfyui-gallery 现状为准重写后，**复制**到
    `C:\Project\Code\comfyui-gallery\docs\`，并更新 comfyui-gallery 的 `docs/功能清单.md`
    保持自洽（仓库有文档维护规则：每次功能点须同步清单与更新记录）。
  - **选项 B**：原地改 ArtMirror 仓库那份文档。
  - （此为开放决策，先问用户；本文档默认按 **选项 A** 规划。）

### 第 1 项 · frontmatter 定位错误
- **P**：文档 `agent_created: true` + description 描述成「RunningHub/krea2-muse
  元数据解析器修复」的 memory 型文档，但内容是运维/技术沉淀，两者定位冲突。
- **F**：改为项目技术文档定位（剥离 memory 语义），description 改述
  「ArtMirror 部署、解析器、前端布局的现状与约定」。

### 第 2 项 · 文档级路径/命令全部指向不存在的 mac 旧环境
- **P**：`/Users/xxx/WorkBuddy/Claw/work/gallery_ref/comfyui-gallery-main/`、
  `image.txt 的 fixed .venv 路径`、`~/图片提示词库`、`8100/8101/8102/8103` 端口、
  `启动Web端-Mac.command` 等——当前 Windows 环境/仓库不存在。
- **F**：重写「固定路径/部署」章节为 comfyui-gallery 现状：
  - 仓库根 = `C:\Project\Code\comfyui-gallery`
  - 启动命令 = `uv run uvicorn launchers.web.main:app --host 127.0.0.1 --port 8000`
  - 依赖安装 = `uv sync`（替换原先 venv+pip 手工流程）
  - 数据目录 = `data/`（SQLite + thumbs）

### 第 3 项 · 解析器补丁章节（5 组 10 处）在代码中不存在
- **P**：实测 `artmirror/parsers/comfyui_parser.py`（两仓库一致，625 行）——
  - ❌ 无 `JjkText`（TEXT_SOURCE_NODES 无它）
  - ❌ 无 22 个中文负面词 / `mosaic` / `censored`
  - ❌ 无 `_resolve_seed()`（seed 仅 `_to_int(i.get("seed"))`，无 `noise_seed`）
  - ❌ 无 `EASY_LORA_STACKS` / `_strength_used` / `num_loras` 逻辑
  - ❌ 无 `TEXT_MERGE_NODES` / CR Text Concatenate 拼接
  - ❌ 无 `lora_weights` 落库链路
- **F**：整段「二、打补丁 + 代码改动位置速查」**删除**，替换为对真实解析器的简短说明
  （列出 parser 实际有哪些能力：UI/API 双格式、正负向、模型/LoRA/seed/sampler 提取、
  文本联结已按原生分支处理等，以 `extract_prompt_lists`/`extract_assets`/`extract_sampler_params`
  为真实锚点）。补丁脚本 `apply_artmirror_patch.py` 不存在 → 删除相关命令。
- 附带删除：`### 关键判定规则速记`、LoRA 权重字段说明、跨 6 文件改动注释（均不存在）。

### 第 4 项 · 「已知数据 / 15 张不一致 / 回填本机库」是旧试点数据
- **P**：`library_db.json`（489 条）、`img_lib` 585 PNG、`backfill_meta.py`、`mismatch_detail.py`
  等均为外部资产库一次性摸底产出，与当前仓库无映射，脚本/数据都不在仓库里。
- **F**：整段删除「已知数据 / 15 张不一致 / 六、回填本机库 / 已知坑：比对 pos 归一化」。
  若用户仍需要这些统计口径，另立独立文档，不放在本项目技术文档。

### 第 5 项 · 「七、升级到上游新版」流程与现状冲突
- **P**：文档称要「把补丁迁移到上游新版」，但补丁根本不存在；且流程引用
  `_new_upstream/`、`_merge_test/`、`verify_upstream_merge.py` 等仓库里没有的目录/脚本。
- **F**：删除整段升级/回滚流程及其踩坑（GBK 文件名、cp 超时、沙箱 curl 等 mac 试点的坑）。
  如需保留「版本比较/升级」的通识，改写为通用的「同源 diff + 测试 + 清库重扫」指引，
  不写死不存在的脚本名。

### 第 6 项 · 「八、前端详情页布局定制」与真实实现不符
- **P**：文档大篇幅描述 `.vp` 舞台（`vpZoom/vpFitToWindow/vpWheel`…）、
  `rebalanceLayout`、`.detail-left/.detail-info/.left-extras/.right-extras`、
  「三处 grid-template-columns 统一 360px」——**全部在 comfyui-gallery 前端零命中**。
  真实现状（实测）：
  - `image.html` `ratioClass()`：`(w/h) > 2.3 ? "landscape" : "portrait"`
    （`landscape`=单列上下，`portrait`=左右分栏）
  - `style.css`：`.detail-layout` = `minmax(0,1.1fr) minmax(0,1fr)`（默认左右）、
    `.portrait` 同、`.landscape` = `1fr`、`<900px` 单列
  - 图片缩放/预览用的是 **`.pv`（preview）机制 + 详情页放大镜**，非文档的 `.vp`
- **F**：整段重写「八、前端详情页」为当前真实实现：
  - 布局判定：`(w/h)>2.3 → landscape(单列) / ≤2.3 → portrait(左右)`，并注明语义
    （landscape 反而单列，命名与直觉相反，已作为已知点保留因阈值用户本意）
  - 预览：`.pv` 双击预览窗（滚轮缩放 1–8、拖拽平移、Esc/遮罩关闭）+ 详情放大镜
  - 主题系统：7→4 主题现状（light/dark/claude/spacex，`frontend/themes/spacex.css`，
    经 `themes.css` 引入，settings 主题板块可换），补充说明其余主题已删。
  - 压缩：JPG 有损（`compress_mode` new/overwrite，覆盖前入废纸篓）现状。

### 第 7 项 · 「硬规则」节与代码红线脱节
- **P**：`~/图片提示词库 只读`、`compress_mode 保持 new` 等规则针对旧的局外资产库；
  当前仓库数据在 `data/`，且压缩功能已正规支持 new/overwrite（overwrite 有废纸篓备份）。
- **F**：重写「硬规则」为当前项目约束：
  - `data/` 为运行数据可清空重建；不改 ComfyUI 核心（用户既有偏好）
  - 每次功能点须更新 `docs/功能清单.md`（AGENTS.md 规则）
  - 前端改动不做自动化浏览器验证，由用户强刷核对（AGENTS.md 规则）

### 第 8 项 · 结构与可读性
- **P**：全文 232 行，命令、统计、踩坑、代码位置混排，「升级」「部署」等现象与国内外混；
  大量不再适用的历史记录增噪。
- **F**：重排为清晰章节：① 现状总览 ② 启动/部署 ③ 解析器能力 ④ 前端布局与主题
  ⑤ 硬规则。逐项对应上面 1–7 的重写结果。

---

## 关键假设 / 决策

- 校准基准 = `comfyui-gallery` 当前 HEAD（dev-rh，含 `11ba6fc fix: 横纵比展示问题`）。
- 文档修改落点默认**选项 A**（落到 comfyui-gallery/docs/），执行前向用户确认。
- 不新增任何「本就不存在的功能」到文档；文档只描述真实存在的现状。
- 涉及 parser 的章节只做「如实描述」，不借机改 parser 代码（本任务是文档修复，不是功能开发）。

---

## 验证步骤

1. 重读修改后文档，逐条回查：每个提到的文件名/类名/函数/命令/端口在
   `comfyui-gallery` 中真实存在（可 grep）。
2. 确认不再出现任何 `/Users/xxx`、`8100+`、`gallery_ref`、`img_lib`、
   `archive .vp / rebalanceLayout / 360px 统一列` 等已删除的错误引用。
3. 若文档落位 comfyui-gallery，则 `docs/功能清单.md` 保持自洽（无矛盾）。
4. 更新 `AGENTS.md` 的「文档维护」说明（若涉及文档归属变更）。
5. 提交到当前工作分支（dev-rh 或经用户确认的分支）。