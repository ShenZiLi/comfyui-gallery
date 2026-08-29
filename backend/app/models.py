"""数据模型（SQLModel 表）。

通用字段遵循约定：id、create_time、update_time、is_deleted。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, Relationship, SQLModel

from .common import now


class BaseModel(SQLModel):
    """公共字段基类。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    create_time: datetime = Field(default_factory=now)
    update_time: datetime = Field(default_factory=now)
    is_deleted: int = Field(default=0)


class Folder(BaseModel, table=True):
    """目录节点（一棵树）。"""

    parent_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("folder.id"), nullable=True)
    )
    name: str = Field(max_length=255)
    path: str = Field(max_length=1024)  # 相对根目录的路径
    sort_order: int = Field(default=0)


class ImageAsset(BaseModel, table=True):
    """图片资产。"""

    __table_args__ = (UniqueConstraint("file_path", name="uq_image_path"),)

    folder_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("folder.id"), nullable=True)
    )
    file_name: str = Field(max_length=512)
    file_path: str = Field(max_length=2048, index=True)  # 相对根目录
    abs_path: str = Field(default="", max_length=4096)   # 物理文件绝对路径
    sha256: str = Field(default="", max_length=64, index=True)
    width: int = Field(default=0)
    height: int = Field(default=0)
    file_size: int = Field(default=0)
    file_mtime: float = Field(default=0.0)
    thumb_ok: int = Field(default=0)
    scan_time: datetime = Field(default_factory=now)
    prompt_type: str = Field(default="none")  # none / origin / reverse
    rating: Optional[float] = Field(default=None)      # 人工评分 1-5
    ai_rating: Optional[float] = Field(default=None)   # AI 评分 0-100

    workflow_meta: Optional["WorkflowMeta"] = Relationship(back_populates="image")
    reverse_prompts: list["ReversePrompt"] = Relationship(back_populates="image")
    translations: list["PromptTranslation"] = Relationship(back_populates="image")
    rating_records: list["RatingRecord"] = Relationship(back_populates="image")


class WorkflowMeta(BaseModel, table=True):
    """由 PNK meta 解析出的工作流信息（约定的名称字段见设计文档）。"""

    image_id: int = Field(foreign_key="imageasset.id", index=True, unique=True)
    prompt: str = Field(default="", sa_column=Column(Text))
    negative_prompt: str = Field(default="", sa_column=Column(Text))
    prompt_graph_json: str = Field(default="", sa_column=Column(Text))
    workflow_json: str = Field(default="", sa_column=Column(Text))
    steps: Optional[int] = None
    cfg: Optional[float] = None
    sampler: str = Field(default="", max_length=128)
    scheduler: str = Field(default="", max_length=128)
    seed: Optional[int] = None
    denoise: Optional[float] = None
    model_name: str = Field(default="", max_length=512)
    ai_prompt: str = Field(default="", sa_column=Column(Text))          # AI 从工作流解析出的提示词
    ai_negative_prompt: str = Field(default="", sa_column=Column(Text)) # AI 解析出的负向提示词
    origin_prompts_json: str = Field(default="", sa_column=Column(Text))  # 原生多提示词（正）JSON 列表
    negative_prompts_json: str = Field(default="", sa_column=Column(Text))  # 原生多提示词（负）JSON 列表
    ai_prompts_json: str = Field(default="", sa_column=Column(Text))      # AI 多提示词（正）JSON 列表

    image: Optional[ImageAsset] = Relationship(back_populates="workflow_meta")


class Tag(BaseModel, table=True):
    """标签：模型 / LoRA / VAE 等（按类别区分）。"""

    __table_args__ = (UniqueConstraint("name", "category", name="uq_tag_name_cat"),)

    name: str = Field(max_length=512)
    category: str = Field(max_length=64, index=True)  # model/lora/vae/embedding/style/special
    count: int = Field(default=0)


class ImageTag(BaseModel, table=True):
    """图片-标签 多对多关联。"""

    image_id: int = Field(foreign_key="imageasset.id", index=True)
    tag_id: int = Field(foreign_key="tag.id", index=True)


class ReversePrompt(BaseModel, table=True):
    """AI 反推提示词（与原生 workf提示分离，避免覆盖）。"""

    image_id: int = Field(foreign_key="imageasset.id", index=True)
    engine: str = Field(default="", max_length=128)
    model_name: str = Field(default="", max_length=256)
    text: str = Field(default="", sa_column=Column(Text))

    image: Optional[ImageAsset] = Relationship(back_populates="reverse_prompts")


class PromptTranslation(BaseModel, table=True):
    """提示词中英翻译。"""

    image_id: int = Field(foreign_key="imageasset.id", index=True)
    prompt_kind: str = Field(max_length=32)  # origin / reverse
    lang: str = Field(max_length=16)         # zh / en
    text: str = Field(default="", sa_column=Column(Text))

    image: Optional[ImageAsset] = Relationship(back_populates="translations")


class RatingRecord(BaseModel, table=True):
    """评分记录（历史）；最新值汇总到 ImageAsset.rating / ai_rating。"""

    image_id: int = Field(foreign_key="imageasset.id", index=True)
    rating_type: str = Field(max_length=16)  # ai / manual
    score: float = Field(default=0)
    reason: str = Field(default="", sa_column=Column(Text))

    image: Optional[ImageAsset] = Relationship(back_populates="rating_records")


class ClusterGroup(BaseModel, table=True):
    """聚合/聚类分组结果。"""

    group_key: str = Field(max_length=2048, index=True)
    cluster_type: str = Field(max_length=32)  # exact / similar / dimension
    name: str = Field(default="", max_length=1024)
    sort_rank: int = Field(default=0)


class Setting(BaseModel, table=True):
    """键值配置（扫描路径、LLM 配置、UI 偏好等）。"""

    key: str = Field(max_length=255, unique=True, index=True)
    value: str = Field(default="", sa_column=Column(Text))