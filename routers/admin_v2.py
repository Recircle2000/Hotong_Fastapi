from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas.admin_v2 import (
    AdminLoginRequest,
    AdminLogoutResponse,
    AdminNoticePayload,
    AdminNoticeResponse,
    AdminSessionResponse,
    AdminSessionUser,
)
from services.admin_auth import (
    AUTH_REQUIRED_MESSAGE,
    AdminAuthError,
    authenticate_admin_credentials,
    clear_admin_session,
    login_admin_session,
    resolve_admin_user,
)
from services.admin_notice import (
    create_admin_notice,
    delete_admin_notice,
    list_admin_notices,
    serialize_notice,
    update_admin_notice,
)


router = APIRouter(prefix="/api/admin-v2", tags=["Admin V2"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin-v2/auth/login", auto_error=False)


def serialize_session_user(user: User) -> AdminSessionUser:
    return AdminSessionUser(id=user.id, email=user.email, is_admin=bool(user.is_admin))


async def get_admin_api_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str | None = Depends(oauth2_scheme),
) -> User:
    user = resolve_admin_user(request, db, token)
    if user:
        return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AUTH_REQUIRED_MESSAGE)


@router.post("/auth/login", response_model=AdminSessionResponse)
async def login_admin_v2(
    payload: AdminLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user = authenticate_admin_credentials(db, payload.email, payload.password)
    except AdminAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    login_admin_session(request, user)
    return AdminSessionResponse(authenticated=True, user=serialize_session_user(user))


@router.post("/auth/logout", response_model=AdminLogoutResponse)
async def logout_admin_v2(request: Request):
    clear_admin_session(request)
    return AdminLogoutResponse(success=True)


@router.get("/auth/session", response_model=AdminSessionResponse)
async def get_admin_v2_session(current_admin: User = Depends(get_admin_api_user)):
    return AdminSessionResponse(authenticated=True, user=serialize_session_user(current_admin))


@router.get("/notices", response_model=list[AdminNoticeResponse])
async def get_admin_v2_notices(
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    return [serialize_notice(notice) for notice in list_admin_notices(db)]


@router.post("/notices", response_model=AdminNoticeResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_v2_notice(
    payload: AdminNoticePayload,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    notice = create_admin_notice(
        db,
        title=payload.title,
        content=payload.content,
        notice_type=payload.notice_type,
        is_pinned=payload.is_pinned,
    )
    return serialize_notice(notice)


@router.put("/notices/{notice_id}", response_model=AdminNoticeResponse)
async def update_admin_v2_notice(
    notice_id: int,
    payload: AdminNoticePayload,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    notice = update_admin_notice(
        db,
        notice_id=notice_id,
        title=payload.title,
        content=payload.content,
        notice_type=payload.notice_type,
        is_pinned=payload.is_pinned,
    )
    if not notice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="공지사항을 찾을 수 없습니다.")
    return serialize_notice(notice)


@router.delete("/notices/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_v2_notice(
    notice_id: int,
    current_admin: User = Depends(get_admin_api_user),
    db: Session = Depends(get_db),
):
    del current_admin
    if not delete_admin_notice(db, notice_id=notice_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="공지사항을 찾을 수 없습니다.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
