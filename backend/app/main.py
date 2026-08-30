"""画镜 ArtMirror 应用入口。

单进程同时提供 REST API 与前端静态托管；本文件为 M0 脚手架，
包含健康检查、静态托管与启动初始化（建表、创建目录）。
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response


class NoCacheStaticFiles(StaticFiles):
    """静态资源禁用浏览器缓存，保证前端改动即时生效。"""

    def file_response(self, *args, **kwargs) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

from .config import settings
from .database import init_db, get_session
from .routers import aggregate, folders, fs, images, settings as settings_router, sync, tags
from .services import watcher, meta_service

app = FastAPI(title="画镜 ArtMirror", version="0.1.0")

# 跨域（原型阶段前端直连或局域网访问均可行）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    images.router,
    folders.router,
    tags.router,
    aggregate.router,
    settings_router.router,
    fs.router,
    sync.router,
):
    app.include_router(r)


@app.get("/api/health", tags=["system"])
def health() -> dict:
    """健康检查。"""
    return {
        "status": "ok",
        "app": "artmirror",
        "version": app.version,
        "scan_root": settings.scan_root,
        "llm_configured": bool(settings.llm_base_url and settings.llm_api_key),
    }


@app.on_event("startup")
def on_startup() -> None:
    """启动初始化：建表、迁移标签、创建目录并启动后台实时同步。"""
    init_db()
    with next(get_session()) as session:
        meta_service.migrate_tag_paths(session)
    watcher.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    """关闭后台实时同步线程。"""
    watcher.stop()


# 前端静态托管（优先级低于 API 路由）。
app.mount(
    "/",
    NoCacheStaticFiles(directory=settings.frontend_dir, html=True),
    name="frontend",
)