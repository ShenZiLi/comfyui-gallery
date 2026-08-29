"""应用配置。

包含扫描路径、数据库路径与大模型（OpenAI 兼容）配置。通过环境变量或
.env 覆盖，便于在不同客户端/部署环境使用。
"""
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _module_root() -> Path:
    """开发态项目根：backend/ 的父目录。"""
    return Path(__file__).resolve().parent.parent.parent


def _app_base_dir() -> Path:
    """运行数据基目录：打包态为 exe 所在目录（data/ 放 exe 旁，便携）；开发态为项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _module_root()


def _frontend_base_dir() -> Path:
    """前端静态资源目录：打包态为 exe 内解出的 frontend（sys._MEIPASS）；开发态为项目根/frontend。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend"
    return _module_root() / "frontend"


class Settings(BaseSettings):
    """全局配置项。"""

    model_config = SettingsConfigDict(env_prefix="AM_", env_file=".env", extra="ignore")

    # 本地数据目录（SQLite 库、缩略图等）。默认与 backend 同级下的 data 目录。
    data_dir: str = str(_app_base_dir() / "data")

    # 扫描根目录：可配置单个本地图片目录（预留多根）。
    scan_root: str | None = None

    # 大模型（OpenAI 兼容）配置
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_vision_model: str = ""  # 反推提示词 / 评分看图
    llm_text_model: str = ""    # 翻译 / AI 评分
    llm_embed_model: str = ""   # 相似提示词聚类（可选）

    frontend_dir: str = str(_frontend_base_dir())

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "artmirror.db"

    @property
    def thumbs_dir(self) -> Path:
        return Path(self.data_dir) / "thumbs"

    def ensure_dirs(self) -> None:
        """创建运行所需目录。"""
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()