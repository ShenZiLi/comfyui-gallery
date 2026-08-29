"""系统级路由：目前仅「一键关闭服务」，供打包后的单文件 exe 使用。"""
from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.post("/api/shutdown")
def shutdown(request: Request) -> dict:
    """优雅关闭服务。

    打包态（run.py 启动）下，server 实例挂在 app.state.server 上，置
    should_exit=True 后 uvicorn 会响应完本次请求再退出，并触发 FastAPI
    shutdown 事件（watcher.stop()）。开发态（uvicorn CLI）下无该实例，
    返回提示而非关闭，避免误杀开发服务。
    """
    server = getattr(request.app.state, "server", None)
    if server is not None:
        server.should_exit = True
        return {"status": "ok", "message": "服务即将关闭，请稍候关闭此页面"}
    return {"status": "ok", "message": "开发模式请手动停止服务"}
