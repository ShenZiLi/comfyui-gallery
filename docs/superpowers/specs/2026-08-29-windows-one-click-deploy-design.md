# 设计：Windows 一键启动部署

* 日期：2026-08-29

* 状态：已确认

* 目标：让小白无需手动 `uv sync` / `uvicorn`，双击即完成依赖安装、服务启动与浏览器打开

## 背景与目标

当前部署方式为手动执行 `uv sync` + `uv run uvicorn`，对非技术用户门槛较高。目标：在 Windows 上提供「双击 `.bat`」一键启动体验，自动完成依赖检查/安装、虚拟环境隔离、服务启动与浏览器打开。

### 关键决策（来自澄清）

* **部署形态**：Windows 双击 `.bat` 一键启动

* **依赖方案**：纯 pip（系统 Python + `pip install -r requirements.txt`），不依赖 uv

* **Python 缺失**：脚本仅提示手动安装指引，不自动安装

* **启动后行为**：自动打开浏览器（图库页）

* **实现方案**：方案 B —— `启动.bat`（双击入口）+ `start.ps1`（逻辑）+ `requirements.txt`

## 文件与结构

| 文件                 | 位置         | 作用                               |
| ------------------ | ---------- | -------------------------------- |
| `启动.bat`           | 项目根目录      | 双击入口：绕过执行策略调用 `start.ps1`，窗口中文标题 |
| `start.ps1`        | 项目根目录      | 核心逻辑                             |
| `requirements.txt` | `backend/` | 纯 pip 依赖清单                       |

## start.ps1 执行流程

1. 定位 `backend` 目录（脚本所在目录下 `backend/`）
2. 检测 Python：

   * `python --version` 不存在 → 打印「未检测到 Python 3.11+，请到 python.org 下载并勾选 Add to PATH」→ 暂停退出

   * 版本 < 3.11 → 同样提示后退出
3. 若 `backend/.venv` 不存在 → `python -m venv .venv`
4. 激活 `.venv` → `python -m pip install -r requirements.txt`（首次自动安装，之后秒过）
5. 后台启动服务：`Start-Process .venv\Scripts\python -m uvicorn app.main:app --port 8000`（日志重定向到 `data/server.log`）
6. 轮询 `http://127.0.0.1:8000/api/health` 直到就绪（超时 60s）
7. 就绪后 `Start-Process` 默认浏览器打开 `http://127.0.0.1:8000/gallery.html`
8. 窗口保持前台，显示「画镜已启动 · 地址：… · 按任意键停止服务退出」
9. 退出时结束 uvicorn 进程

## 边界与异常处理

* **端口已占用**：检测 8000 已监听 → 跳过启动，直接打开浏览器（服务可能已在运行）

* **pip 安装失败**：打印错误并暂停，便于小白截图反馈

* **再次运行**：检测 `.venv` 与依赖已就绪 → 跳过安装秒启

* **停止**：关闭窗口自动结束 uvicorn；不残留后台进程

## 依赖清单（requirements.txt）

来自 `backend/pyproject.toml`（`requires-python >=3.11`）：

```
fastapi>=0.115
uvicorn[standard]>=0.32
sqlmodel>=0.0.22
pydantic-settings>=2.6
pillow>=11.0
httpx>=0.27
python-multipart>=0.0.9
send2trash>=1.8
```

## 文档更新

* README 新增「小白快速启动」章节：双击 `启动.bat` 即可，附首次/后续/停止说明

## 验证方式

* 干净环境（删除 `backend/.venv`）首次运行 → 建环境装依赖 → 服务起 → 浏览器打开

* 二次运行秒启；端口占用复用；Python 缺失提示（按项目约定，前端/部署验证不使用自动化浏览器）

