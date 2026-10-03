from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from auth_config import SupabaseAuthConfig
from database import get_db
from schemas.app_auth import (
    AppAuthMeResponse,
    CurrentAppUser,
    ReviewOtpRequest,
    ReviewOtpResponse,
)
from services.account import delete_account
from services.review_login import ReviewLoginError, issue_review_otp
from services.taxi import TaxiServiceError
from utils.supabase_security import get_auth_config_dependency, get_current_app_user


router = APIRouter(prefix="/api/app-auth", tags=["App Authentication"])


@router.get("/me", response_model=AppAuthMeResponse)
def get_me(
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
) -> AppAuthMeResponse:
    response.headers["Cache-Control"] = "no-store"
    return AppAuthMeResponse(user_id=current_user.user_id)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
) -> Response:
    # 이미 발급된 액세스 토큰은 만료 전까지 서명상 유효하지만, 앱이 곧바로 로컬 세션을 지운다.
    try:
        await run_in_threadpool(delete_account, db, current_user.user_id)
    except TaxiServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.post("/review-otp", response_model=ReviewOtpResponse)
async def create_review_otp(
    payload: ReviewOtpRequest,
    response: Response,
    config: SupabaseAuthConfig = Depends(get_auth_config_dependency),
) -> ReviewOtpResponse:
    """앱 심사용 계정이 고정 코드로 일회용 인증번호를 받는다.

    심사자는 메일함을 열 수 없어서, 메일 대신 이 응답으로 인증번호를 받아 평소처럼 인증한다.
    """
    response.headers["Cache-Control"] = "no-store"
    try:
        otp = await issue_review_otp(config, payload.email, payload.code)
    except ReviewLoginError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return ReviewOtpResponse(otp=otp)
