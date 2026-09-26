"""Regression checks for Chinese/English prompt translation direction and caching."""

from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine, select

from artmirror.models import ImageAsset, PromptTranslation, WorkflowMeta
from artmirror.routers import images
from artmirror.services import llm


def _image_with_prompt(tmp_path, prompt: str):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'translation.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        image = ImageAsset(
            file_name="sample.png", file_path="/x/sample.png", abs_path="/x/sample.png",
            sha256="a" * 64, width=64, height=64, file_size=100,
        )
        session.add(image)
        session.flush()
        session.add(WorkflowMeta(image_id=image.id, prompt=prompt))
        session.commit()
        return engine, image.id


def test_target_language_follows_dominant_source_language():
    assert images._detect_target_lang("一个女孩穿着蓝色裙子，HDR portrait") == "en"
    assert images._detect_target_lang("cinematic portrait of a woman, 中国风 details") == "zh"


def test_wrong_language_cached_translation_is_refreshed(tmp_path, monkeypatch):
    source = "一个女孩站在花园里，手里拿着白色的花。"
    engine, image_id = _image_with_prompt(tmp_path, source)
    with Session(engine) as session:
        session.add(PromptTranslation(
            image_id=image_id, prompt_kind="origin", lang="en", text=source,
        ))
        session.commit()

    calls = []

    def translate(text, target, session):
        calls.append(target)
        return "A girl stands in a garden holding white flowers."

    monkeypatch.setattr(images.llm, "translate_prompt", translate)
    with Session(engine) as session:
        result = images.translate_prompt_image(image_id, {"kind": "origin"}, session)
        rows = session.exec(select(PromptTranslation)).all()

    assert calls == ["en"]
    assert result == {
        "texts": ["A girl stands in a garden holding white flowers."],
        "lang": "en", "cached": False,
    }
    assert len(rows) == 1
    assert rows[0].text == result["texts"][0]


def test_english_prompt_translates_to_chinese(tmp_path, monkeypatch):
    engine, image_id = _image_with_prompt(
        tmp_path, "A girl stands in a garden holding white flowers."
    )
    targets = []

    def translate(text, target, session):
        targets.append(target)
        return "一个女孩站在花园里，手里拿着白色的花。"

    monkeypatch.setattr(images.llm, "translate_prompt", translate)
    with Session(engine) as session:
        result = images.translate_prompt_image(image_id, {"kind": "origin"}, session)

    assert targets == ["zh"]
    assert result["lang"] == "zh"
    assert result["texts"] == ["一个女孩站在花园里，手里拿着白色的花。"]


def test_model_response_in_source_language_is_retried(monkeypatch):
    responses = iter([
        "一个女孩站在花园里，手里拿着白色的花。",
        "A girl stands in a garden holding white flowers.",
    ])
    prompts = []

    def chat(prompt, session):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(llm, "chat_text", chat)
    translated = llm.translate_prompt("一个女孩站在花园里，手里拿着白色的花。", "en")
    assert translated == "A girl stands in a garden holding white flowers."
    assert len(prompts) == 2
    assert "英文" in prompts[0] and "英文" in prompts[1]


def test_editing_source_removes_stale_translation(tmp_path, monkeypatch):
    engine, image_id = _image_with_prompt(tmp_path, "A girl in a garden.")
    with Session(engine) as session:
        session.add(PromptTranslation(
            image_id=image_id, prompt_kind="origin", lang="zh", text="花园中的女孩。",
        ))
        session.commit()

    monkeypatch.setattr(images.watcher, "bump", lambda: None)
    with Session(engine) as session:
        detail = images.update_image_prompt(
            image_id, {"target": "origin", "texts": ["一个女孩站在花园里。"]}, session,
        )
        rows = session.exec(select(PromptTranslation)).all()

    assert detail["translations"] == {}
    assert rows == []
