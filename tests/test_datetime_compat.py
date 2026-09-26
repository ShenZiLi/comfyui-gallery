"""Keep the existing local, timezone-naive SQLite timestamps writable."""

from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

from artmirror.models import ImageAsset, Setting


def test_naive_model_timestamps_round_trip() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    stamp = datetime(2026, 9, 26, 12, 34, 56)

    with Session(engine) as session:
        session.add(Setting(key="test", create_time=stamp, update_time=stamp))
        session.add(
            ImageAsset(
                file_name="test.png",
                file_path="test.png",
                abs_path="C:/images/test.png",
                path_key="c:\\images\\test.png",
                create_time=stamp,
                update_time=stamp,
                scan_time=stamp,
            )
        )
        session.commit()
        session.expire_all()

        setting = session.exec(select(Setting)).one()
        image = session.exec(select(ImageAsset)).one()

    assert setting.create_time == stamp
    assert setting.update_time == stamp
    assert image.create_time == stamp
    assert image.update_time == stamp
    assert image.scan_time == stamp
