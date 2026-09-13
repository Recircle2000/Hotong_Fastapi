from fastapi import APIRouter, Depends, Response

from schemas.app_auth import AppAuthMeResponse, CurrentAppUser
from utils.supabase_security import get_current_app_user


router = APIRouter(prefix="/api/app-auth", tags=["App Authentication"])


@router.get("/me", response_model=AppAuthMeResponse)
def get_me(
    response: Response,
    current_user: CurrentAppUser = Depends(get_current_app_user),
) -> AppAuthMeResponse:
    response.headers["Cache-Control"] = "no-store"
    return AppAuthMeResponse(user_id=current_user.user_id)
