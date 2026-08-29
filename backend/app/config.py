"""应用配置。

包含扫描路径、数据库路径与大模型（OpenAI 兼容）配置。通过环境变量或
.env 覆盖，便于在不同客户端/部署环境使用。
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置项。"""

    model_config = SettingsConfigDict(env_prefix="AM_", env_file=".env", extra="ignore")

    # 本地数据目录（SQLite 库、缩略图等）。默认与 backend 同级下的 data 目录。
    data_dir: str = str(Path(__file__).resolve().parent.parent.parent / "data")

    # 扫描根目录：可配置单个本地图片目录（预留多根）。
    scan_root: str | None = None

    # 大模型（OpenAI 兼容）配置
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_vision_model: str = ""  # 反推提示词 / 评分看图
    llm_text_model: str = ""    # 翻译 / AI 评分
    llm_embed_model: str = ""   # 相似提示词聚类（可选）

    frontend_dir: str = str(
        Path(__file__).resolve().parent.parent.parent / "frontend"
    )

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