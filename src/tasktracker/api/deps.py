from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from tasktracker.models import User
from tasktracker.services import auth

SESSION_COOKIE = "tasktracker_session"


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_optional_user(request: Request, session: SessionDep) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    return auth.user_for_token(session, token) if token else None


def get_current_user(user: Annotated[User | None, Depends(get_optional_user)]) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


OptionalUser = Annotated[User | None, Depends(get_optional_user)]
CurrentUser = Annotated[User, Depends(get_current_user)]
