# PNG 无损压缩功能 设计

日期：2026-09-04
状态：待评审（用户已确认技术选型与三处决策，待过目本文档后进入实现计划）

## 目标

在画镜 ArtMirror 中新增 **PNG 无损压缩** 能力：图库「平铺/沉浸」多选批量压缩，图片详情页单张压缩；
只做无损（像素逐点一致，不改变格式、不损失画质），产物可以「存为新图入库」也可「覆盖原图」，
并可选择是否保留内嵌工作流信息；压缩后反而变大时中止且明确提示。

## 背景与约束

- 技术栈：Python 3.12 + FastAPI + SQLModel(SQLite) + Pillow。缩略图已用 Pillow。
- 仓库根即插件、解压即用：ComfyUI 加载时 `install_deps.py` 自动 `pip install`，并以单文件 zip 分发。
  → **原则：不新增随包外部二进制**；用纯 Pillow，零新增依赖。
- 原图字节以引用（`abs_path`/`sha256`）入库，不存库内。
- 覆盖类危险操作已有 `Send2Trash`（删除入废纸篓）先例，复用同库做安全备份。

## 非目标

- 不做有损（WebP/AVIF/JPEG/调色板量化）。
- 不做无损压得最狠（不引入 oxipng/Zopfli）。
- 批量不打包 zip（YAGNI，逐张压缩入库并返回结果列表）。

## 设置项（设置页新增）

| key | 取值 | 默认 | 说明 |
| --- | --- | --- | --- |
| `compress_mode` | `new` / `overwrite` | `new` | 压缩产物存为新图入库 / 覆盖原文件 |
| `compress_keep_meta` | `true` / `false` | `true` | 保留内嵌工作流信息（`workflow`/`prompt`/`tEXt`/`iTXt`/`zTXt`） |

- 生效时机：每张压缩时读取一次（可与图库/详情页传入参数互斥——本次不做页面级覆盖，统一用设置项）。

## 算法（纯 Pillow 无损压缩）

对每张目标 PNG：

1. `img = Image.open(abs_path)`；`data = list(img.info.get("text")...)` 等读取文本块。
   - 用 `img.load()` 确认可解码；失败 → 返回错误。
2. 决定保留/剥离文本块：
   - `compress_keep_meta == true`：把原图文本块（`tEXt/iTXt/zTXt`，经 `img.info`/`img.text`）通过 `pnginfo` 写回。
   - `compress_keep_meta == false`：剥离这些文本块（不写回）。
3. `img.save(tmp, "PNG", optimize=True, compress_level=9, pnginfo=...)`。
   - `pnginfo` 提供与否由第 2 步决定。
4. 比较 `old_size = Path(abs_path).stat().st_size` 与 `new_size = tmp.stat().st_size`。
   - `new_size >= old_size`：**不保存**，删除临时文件，返回 `saved=false`（提示「压缩后反而更大，已跳过」）。
   - `new_size < old_size`：按 `compress_mode` 落盘（见下）。

> 说明：`optimize=True` 会让 Pillow 用 zlib 最优档重压 IDAT；剥离文本块进一步减体积。像素数据本身不变 → 无损。

## 产物去向

- **`new`（存为新图）**：
  - 写入 `settings.import_dir`（设置页「导入保存目录」，需可写；不可写则报错并提示授权引导，复用现有 403 逻辑）。
  - 文件名：`<原名去扩展名>_compressed.png`；若同名冲突则追加序号。
  - 写入后交由 watcher/扫描机制入库 → gallery 立即可见（与现有导入一致）。
- **`overwrite`（覆盖原图）**：先 `Send2Trash.send2trash(abs_path)` 备份原文件到废纸篓，再以临时文件替换原路径。

## 接口

### 单张

`POST /api/images/{image_id}/compress`
- 无 body（参数来自设置项）。
- 成功：`200 {"original":<int>,"compressed":<int|None>,"saved":<bool>,"new_file":<path|None>,"reason":<str|null>}`
- 变大跳过：`saved=false, compressed=原大或None, reason="压缩后反而更大，已跳过"`
- 非 PNG / 解码失败：`400`；图片不存在：`404`。

### 批量

`POST /api/images/batch-compress`，body `{"ids": [int, ...]}`
- 逐张执行与单张相同逻辑，仅「变小」者落盘。
- 返回：`{"results":[{id,name,original,compressed,saved,new_file,reason}], "total":int, "saved_count":int}`。

## 前端入口

- **image 页**：信息栏或顶部加「压缩」按钮 → 调单张接口 → toast 展示「原 X · 压后 Y」或「变大已跳过」。
- **gallery 多选批量**：多选后（复用现有 `selIds` 与批量删除按钮区）加「批量压缩」→ 调批量接口 → toast 汇总「成功 n / 跳过 m」。
- 存新图模式下，批量压缩后刷新目录/图库（沿用现有 `manualRefresh`/版本号轮询）以展示新入库图。

## 错误处理与边界

- 非 PNG、文件缺失、解码失败：明确 400/404 及中文原因。
- `overwrite` 备份失败（Send2Trash 异常）：中止该张，不覆盖，报错。
- `new` 目标目录不可写：报错并弹既有授权引导（403）。
- 并发/竞态：批量逐张在独立 try；单张失败不影响其它。
- 文件极大触发出于「越大越可能反向」的省略：仍按 size 比较决定，不预设阈值。

## 测试

- 无损：构造含文本块与 ComfyUI workflow 的 PNG → 压缩（保留/剥离两种）→ 解码比较像素逐点一致。
- chunk：`compress_keep_meta=true` 保留 `workflow`/`tEXt`；`false` 剥离。
- 变大中止：构造已高度压缩（`zlib` 最优）的 PNG → 断言 `saved=false` 且原文件未被改动。
- 两模式落位：`new` 写到 import_dir 且入库索引；`overwrite` 覆盖原路径且先入废纸篓备份。
- 接口：单张/批量成功与跳过分支；404/400。

## 影响面

- 后端：新增 `artmirror/routers/compress.py`（或并入 images.py）；设置项并入 `settings.py`；模型无需改表（设置用 KV）。
- 前端：`api.js` 增两方法；image.html、gallery.html 增入口；settings.html 增两个开关。
- 文档：`docs/功能清单.md` 增补一条。