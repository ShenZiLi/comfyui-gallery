"""造数压测：向 data/artmirror.db 插入大量图片记录与占位缩略图。

用法（仓库根目录下执行）：
    uv run python scripts/seed_stress.py            # 插入 10000 条压测数据
    uv run python scripts/seed_stress.py --n 2000   # 自定义数量
    uv run python scripts/seed_stress.py --clean    # 清理全部压测数据
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine, init_db  # noqa: E402
from app.models import (  # noqa: E402
    ImageAsset,
    ImageTag,
    PromptTranslation,
    RatingRecord,
    ReversePrompt,
    Tag,
    WorkflowMeta,
)

PREFIX = "stress_"
CHUNK = 500

PROMPTS = [
    "masterpiece, best quality, 1girl, silver hair, detailed eyes, cherry blossoms",
    "epic landscape, mountains at sunset, dramatic clouds, ultra detailed, 8k",
    "cyberpunk city street, neon lights, rain reflections, cinematic lighting",
    "portrait of a samurai, ink wash style, dramatic shading, monochrome",
    "cozy reading nook, warm sunlight, plants, watercolor illustration",
    "space station orbiting a gas giant, sci-fi concept art, volumetric light",
    "cute corgi in a tiny wizard hat, sticker style, flat colors",
    "ancient forest temple, mossy stones, god rays, fantasy environment",
    "racing car on a wet track at night, motion blur, headlight flare",
    "bowl of ramen, food photography, steam, shallow depth of field",
    "ice dragon flying over a frozen fjord, matte painting",
    "art nouveau poster of a dancer, gold accents, elegant lines",
    "underwater coral reef, tropical fish, sunbeams from surface",
    "abandoned subway station, graffiti, urban exploration photography",
    "cherry blossom festival at night, paper lanterns, crowd silhouettes",
    "steampunk airship workshop, brass gears, blueprints scattered",
    "minimalist zen garden, raked sand, single maple tree, morning mist",
    "knight in ornate armor standing in a cathedral, dramatic light",
    "pixel art island floating in the sky, retro game style",
    "northern lights over a snowy cabin, long exposure photography",
]


def _thumb(sha: str, tone: int) -> None:
    p = settings.thumbs_dir / f"{sha}.webp"
    if not p.exists():
        Image.new("RGB", (160, 160), (tone % 256, 60, 90)).save(str(p), "WEBP")


def seed(session: Session, n: int) -> None:
    existing = [im for im in session.exec(select(ImageAsset)).all()
                 if im.file_name.startswith(PREFIX)]
    if existing:
        print(f"已存在 {len(existing)} 条压测数据，请先执行 --clean")
        return
    random.seed(42)
    models = [Tag(name=f"{PREFIX}model_{k}", category="model") for k in range(5)]
    loras = [Tag(name=f"{PREFIX}lora_{k}", category="lora") for k in range(8)]
    for t in models + loras:
        session.add(t)
    session.flush()

    for i in range(n):
        prompt = PROMPTS[i % len(PROMPTS)]
        sha = f"{i:064x}"
        im = ImageAsset(
            file_name=f"{PREFIX}{i:05d}.png",
            file_path=f"/stress/{PREFIX}{i:05d}.png",
            abs_path=f"/stress/{PREFIX}{i:05d}.png",
            sha256=sha,
            width=1024, height=1024, file_size=1_500_000 + i,
            ai_rating=(random.random() * 100) if i % 3 else None,
        )
        session.add(im)
        session.flush()
        session.add(WorkflowMeta(
            image_id=im.id, prompt=prompt, negative_prompt="lowres, bad anatomy",
            origin_prompts_json=json.dumps([prompt], ensure_ascii=False),
            steps=20 + i % 10, cfg=6.5, sampler="euler", scheduler="normal", seed=i,
        ))
        session.add(ImageTag(image_id=im.id, tag_id=random.choice(models).id))
        if random.random() < 0.5:
            session.add(ImageTag(image_id=im.id, tag_id=random.choice(loras).id))
        if i % 10 == 0:
            session.add(ReversePrompt(image_id=im.id, text="a stress test reverse prompt"))
            session.add(RatingRecord(image_id=im.id, rating_type="ai", score=80, reason="压测评分依据"))
            session.add(PromptTranslation(image_id=im.id, prompt_kind="origin", lang="zh", text="压测译文"))
        _thumb(sha, i)
        if (i + 1) % CHUNK == 0:
            session.commit()
            print(f"  已插入 {i + 1}/{n}")
    session.commit()
    print(f"完成：插入 {n} 条压测数据")


def clean(session: Session) -> None:
    ims = [im for im in session.exec(select(ImageAsset)).all()
           if im.file_name.startswith(PREFIX)]
    if not ims:
        print("无压测数据")
        return
    ids = [im.id for im in ims]
    shas = [im.sha256 for im in ims]
    for model in (WorkflowMeta, ReversePrompt, PromptTranslation, RatingRecord, ImageTag):
        for row in session.exec(select(model).where(model.image_id.in_(ids))).all():
            session.delete(row)
    for im in ims:
        session.delete(im)
    for tag in session.exec(select(Tag)).all():
        if tag.name.startswith(PREFIX):
            session.delete(tag)
    session.commit()
    removed = 0
    for sha in shas:
        p = settings.thumbs_dir / f"{sha}.webp"
        if p.exists():
            p.unlink()
            removed += 1
    print(f"已清理 {len(ims)} 条记录、{removed} 个缩略图")


def main() -> None:
    ap = argparse.ArgumentParser(description="图库压测造数")
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--clean", action="store_true")
    args = ap.parse_args()
    init_db()
    with Session(engine) as session:
        if args.clean:
            clean(session)
        else:
            seed(session, args.n)


if __name__ == "__main__":
    main()
