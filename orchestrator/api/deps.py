"""FastAPI dependencies."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from orchestrator.config import get_settings
from orchestrator.models.base import get_session_factory


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def verify_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    settings = get_settings()
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


DbSession = Annotated[Session, Depends(get_db)]
ApiAuth = Annotated[None, Depends(verify_api_key)]
