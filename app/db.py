from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker


def _default_database_url() -> str:
    storage_root = os.getenv("APP_STORAGE_ROOT") or os.getenv("STORAGE_ROOT")
    if storage_root:
        db_dir = Path(storage_root).expanduser()
    else:
        db_dir = Path(__file__).resolve().parents[1] / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(db_dir / 'workflow.db').resolve()}"


def _database_url() -> str:
    configured = os.getenv("DATABASE_URL")
    if not configured:
        return _default_database_url()
    if not configured.startswith("sqlite"):
        raise RuntimeError(
            "Metadata is stored in a local SQLite file. Unset DATABASE_URL or set it to a sqlite:/// path."
        )
    return configured


DATABASE_URL = _database_url()

engine = create_engine(DATABASE_URL, future=True, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
