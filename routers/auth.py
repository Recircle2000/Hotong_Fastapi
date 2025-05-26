from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Response, Body
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User
from utils.security import hash_password, verify_password, create_access_token, get_current_user
from pydantic import BaseModel
from datetime import timedelta
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from typing import Optional

router = APIRouter()


class UserCreate(BaseModel):
    email: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


# 회원가입 API
@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    """
    새로운 사용자를 등록합니다.
    이미 등록된 이메일인 경우 400 오류를 반환합니다.
    """
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = hash_password(user.password)
    new_user = User(email=user.email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)  # Refresh to get the new user's ID and other fields

    return {"message": "User registered successfully"}


# 로그인 API (OAuth2 호환)
@router.post("/login")
async def login(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    사용자 인증을 수행하고 JWT 토큰을 발급합니다.
    폼 데이터나 JSON 데이터로 요청할 수 있으며, 브라우저 폼 요청의 경우 성공 시 관리자 페이지로 리다이렉트합니다.
    """
    # 요청 타입 확인
    content_type = request.headers.get("Content-Type", "")
    
    # 폼 데이터 요청인 경우
    if "application/x-www-form-urlencoded" in content_type:
        form_data = await request.form()
        username = form_data.get("email") or form_data.get("username")
        password = form_data.get("password")
        is_browser_form = True
    # JSON 요청인 경우
    elif "application/json" in content_type:
        json_data = await request.json()
        username = json_data.get("username")
        password = json_data.get("password")
        is_browser_form = False
    # OAuth2 요청인 경우 (특수 처리)
    elif "application/x-www-form-urlencoded" in content_type and request.query_params.get("grant_type") == "password":
        form_data = await request.form()
        username = form_data.get("username")
        password = form_data.get("password")
        is_browser_form = False
    else:
        # 다른 요청 타입은 지원하지 않음
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="지원하지 않는 요청 형식입니다"
        )
    
    # 유효성 검사
    if not username or not password:
        if is_browser_form:
            return RedirectResponse(
                url="/admin/login?error=이메일과 비밀번호를 모두 입력해주세요", 
                status_code=status.HTTP_303_SEE_OTHER
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이메일(아이디)와 비밀번호를 입력해주세요",
            )
    
    # 사용자 인증
    user_record = db.query(User).filter(User.email == username).first()
    if not user_record or not verify_password(password, user_record.hashed_password):
        if is_browser_form:
            # 브라우저 로그인 실패 시 로그인 페이지로 리디렉션
            return RedirectResponse(
                url="/admin/login?error=로그인에 실패했습니다", 
                status_code=status.HTTP_303_SEE_OTHER
            )
        else:
            # API 로그인 실패 시 401 오류
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="아이디 또는 비밀번호가 틀렸습니다",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    # 관리자 권한 체크 (브라우저 로그인의 경우)
    if is_browser_form and not getattr(user_record, "is_admin", False):
        return RedirectResponse(
            url="/admin/login?error=관리자 권한이 없습니다", 
            status_code=status.HTTP_303_SEE_OTHER
        )

    # JWT 토큰 생성
    access_token = create_access_token(data={"sub": user_record.email}, expires_delta=timedelta(hours=2))
    
    # 세션 로그인 처리 (관리자 페이지용)
    request.session["user_id"] = user_record.id
    
    # 브라우저 로그인 성공 시 관리자 페이지로 리디렉션
    if is_browser_form:
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    
    # API 로그인 성공 시 토큰 반환
    return {"access_token": access_token, "token_type": "bearer"}


# 세션 상태 확인 API
@router.get("/auth/session-status")
async def check_session_status(request: Request, db: Session = Depends(get_db)):
    """
    현재 세션의 인증 상태를 확인합니다.
    인증되지 않은 경우 401 오류를 반환합니다.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {"status": "authenticated", "user_id": user_id}


# 토큰 갱신 API
@router.post("/auth/token/refresh")
async def refresh_token(request: Request, db: Session = Depends(get_db)):
    """
    세션 기반으로 새 JWT 토큰을 발급합니다.
    인증되지 않은 경우 401 오류를 반환합니다.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 새 액세스 토큰 생성
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(hours=2)
    )
    
    return {"access_token": access_token, "token_type": "bearer"}
