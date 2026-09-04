# JPG 有损压缩功能 设计（重构：PNG 无损 → JPG 有损）

日期：2026-09-04
状态：已批准（用户确认：称 JPG、输出 .jpg；质量设置页滑块默认 80；彻底替换 PNG 无损；透明用白底；移除 compress_keep_meta）

## 目标

将原「PNG 无损压缩」重构为「JPG 有损压缩」：图库多选批量、图片详情单张，统一输出 `.jpg`；
可「存为新图入库」或「覆盖原图」，透明 PNG 合成白底，JPG 质量可配置（60–95，默认 80）；
压缩后反而变大则中止跳过并提示。

## 背景约束

- 技术栈 FastAPI + Pillow；仓库根即插件、解压即用 → 零新增依赖，纯 Pillow。
- 沿用既有 `compress_mode`（new/overwrite）、`_move_to_trash` 备份、导入目录 + 后台扫描入库链路。

## 设置项

| key | 取值 | 默认 | 说明 |
| --- | --- | --- | --- |
| `compress_mode` | `new` / `overwrite` | `new` | 存新图入库 / 覆盖原图 |
| `compress_quality` | 整数 1–100 | `80` | JPG 质量，设置页滑块 60–95 |

> 移除原 `compress_keep_meta`（JPG 无工作流/提示词文本块，无保留意义）。

## 算法（纯 Pillow 有损转 JPG）

对每张图：
1. 源格式放宽为常见图片（png/jpg/jpeg/webp/bmp）。
2. `img = Image.open(src); img.load()`。
3. 含透明（RGBA/LA/PA 或 P 带 transparency）→ `convert("RGBA")` 后在**白底** `RGB` 图上按 Alpha 合成（透明→白）。
4. 其余模式 `convert("RGB")`。
5. `flat.save(buf, "JPEG", quality=q)` → 返回字节。
6. `new_size < old_size` 才落盘，否则跳过（reason "压缩后反而更大，已跳过"）。

## 产物去向
- `new`：写入导入目录（`import_dir`），命名 `{stem}_compressed.jpg`（冲突 `-N`），注册扫描根+后台扫描入库。
- `overwrite`：临时文件写 → 原图入废纸篓 → `os.replace` 原子替换；成功后 `watcher.bump()`。

## 接口（不变）
- `POST /api/images/{image_id}/compress` → `{original, compressed, saved, new_file, reason}`
- `POST /api/images/batch-compress` body 裸数组 `[id,...]` → `{results:[...],total,saved_count}`

## 前端
- image.html 单张「压缩」按钮、gallery.html 多选「批量压缩」：逻辑不变（toast 提示原→小）。
- settings.html：移除「保留工作流信息」开关，新增「JPG 质量」滑块（60–95，默认 80）绑 `cfg.compressQuality`。
- api.js：getSettings fallback 去 `compressKeepMeta`、增 `compressQuality: 80`。

## 测试
- service：RGBA 透明→白底、无透明剩余、quality 影响字节、产物可解码。
- api：new 生成 `.jpg`、overwrite、batch、变大跳过。

## 影响面
- 改 `artmirror/services/compress.py`、`artmirror/routers/compress.py`、`artmirror/routers/settings.py`、`frontend/api.js`、`frontend/settings.html`、`frontend/image.html`(仅文案可选)、`frontend/gallery.html`(文案可选)、测试、`docs/功能清单.md`。