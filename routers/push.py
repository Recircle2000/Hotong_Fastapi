from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.app_auth import CurrentAppUser
from schemas.push import PushDeviceRegisterRequest, PushDeviceUnregisterRequest
from services.push import register_device, unregister_device
from utils.supabase_security import get_current_app_user


router = APIRouter(prefix="/api/push", tags=["Push"])


@router.put("/devices", status_code=status.HTTP_204_NO_CONTENT)
def put_push_device(
    payload: PushDeviceRegisterRequest,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    """앱이 로그인 상태에서 FCM 토큰을 받거나 토큰이 바뀔 때마다 부른다."""
    register_device(db, current_user.user_id, payload.token, payload.platform)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/devices", status_code=status.HTTP_204_NO_CONTENT)
def delete_push_device(
    payload: PushDeviceUnregisterRequest,
    current_user: CurrentAppUser = Depends(get_current_app_user),
    db: Session = Depends(get_db),
):
    """로그아웃 직전에 불러 이 기기로 더는 알림이 가지 않게 한다."""
    unregister_device(db, current_user.user_id, payload.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
