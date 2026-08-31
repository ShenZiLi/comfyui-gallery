"""画镜 ArtMirror — web 端启动器（独立服务形态）。

用法：
    uv run uvicorn launchers.web.main:app --host 0.0.0.0 --port 8000
数据目录默认仓库根 data/，前端默认仓库根 frontend/（可经 AM_DATA_DIR / AM_FRONTEND_DIR 覆盖）。
"""
from artmirror.main import create_app

app = create_app()
