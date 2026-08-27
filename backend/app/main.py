"""画镜 ArtMirror 应用入口。

单进程同时提供 REST API 与前端静态托管；本文件为 M0 脚手架，
包含健康检查、静态托管与启动初始化（建表、创建目录）。
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routers import aggregate, folders, images, settings as settings_router, tags

app = FastAPI(title="画镜 ArtMirror", version="0.1.0")

# 跨域（原型阶段前端直连或局域网访问均可行）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (images.router, folders.router, tags.router, aggregate.router, settings_router.router):
    app.include_router(r)


@app.get("/api/health", tags=["system"])
def health() -> dict:
    """健康检查。"""
    return {
        "status": "ok",
        "app": "artmirror",
        "scan_root": settings.scan_root,
        "llm_configured": bool(settings.llm_base_url and settings.llm_api_key),
    }


@app.on_event("startup")
def on_startup() -> None:
    """启动初始化：建表与目录。"""
    init_db()


# 前端静态托管（优先级低于 API 路由）。
app.mount(
    "/",
    StaticFiles(directory=settings.frontend_dir, html=True),
    name="frontend",
)