from fastapi import APIRouter, HTTPException, Request, Response

from tasktracker.api.deps import SESSION_COOKIE, CurrentUser, SessionDep
from tasktracker.schemas import LoginRequest, UserRead
from tasktracker.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserRead)
def login(data: LoginRequest, request: Request, response: Response, session: SessionDep):
    user = auth.authenticate(session, data.username, data.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    response.set_cookie(
        SESSION_COOKIE,
        auth.start_session(session, user.id),
        max_age=int(auth.SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.secure_cookies,
    )
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, session: SessionDep) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth.end_session(session, token)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser):
    return user
