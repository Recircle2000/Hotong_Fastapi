from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from database import get_db
from schemas.app_auth import AppAuthMeResponse, CurrentAppUser
from services.account import delete_account
from services.taxi import TaxiServiceError
from utils.supabase_security import get_current_app_user


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
