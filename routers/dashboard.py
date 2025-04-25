from fastapi import APIRouter, Request, Depends, Form, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from models.notice import Notice
from database import get_db
from datetime import datetime
from fastapi import Response
from starlette.middleware.sessions import SessionMiddleware
from models import User
from utils.security import verify_password, get_current_user, get_current_admin
from fastapi.security import OAuth2PasswordBearer
import jwt
import os
from utils.security import SECRET_KEY, ALGORITHM
from typing import Optional

router = APIRouter()
templates = Jinja2Templates(directory="templates")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

@router.get("/apis")
async def get_api_list(request: Request):
    openapi_schema = request.app.openapi()
    return openapi_schema["paths"]

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    openapi_schema = request.app.openapi()
    paths = openapi_schema["paths"]
    html = """
    <html>
    <head>
        <title>API 대시보드</title>
        <style>
            body { font-family: 'Segoe UI', sans-serif; margin: 40px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px; }
            th { background: #f2f2f2; }
            tr:hover { background: #f9f9f9; }
        </style>
    </head>
    <body>
        <h2>API 대시보드</h2>
        <table>
            <tr><th>경로</th><th>메서드</th><th>설명</th></tr>
    """
    for path, methods in paths.items():
        for method, info in methods.items():
            desc = info.get("summary") or info.get("description") or "-"
            html += f"<tr><td>{path}</td><td>{method.upper()}</td><td>{desc}</td></tr>"
    html += """
        </table>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@router.get("/admin/login")
def admin_login_page(request: Request, error: str = None, redirect: str = None):
    # 이미 로그인된 경우 리다이렉트
    if request.session.get("user_id"):
        return RedirectResponse(url="/admin", status_code=303)
    
    return templates.TemplateResponse(
        "admin_login.html", 
        {"request": request, "error": error, "redirect": redirect}
    )

@router.post("/admin/login")
def admin_login(
    request: Request, 
    db: Session = Depends(get_db), 
    email: str = Form(...), 
    password: str = Form(...),
    redirect: str = Form(None)
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("admin_login.html", {"request": request, "error": "로그인 실패: 아이디 또는 비밀번호가 올바르지 않습니다."})
    if not getattr(user, "is_admin", False):
        return templates.TemplateResponse("admin_login.html", {"request": request, "error": "관리자 권한이 없습니다."})
    
    # JWT 토큰 생성
    from datetime import timedelta
    from utils.security import create_access_token
    access_token = create_access_token(data={"sub": user.email}, expires_delta=timedelta(hours=2))
    
    # 세션 로그인 처리
    request.session["user_id"] = user.id
    
    # 토큰 저장을 위한 응답 생성
    # None 값이거나 빈 문자열인 경우 기본 경로로 리다이렉트
    if redirect and redirect != "None" and redirect.strip():
        redirect_url = redirect
    else:
        redirect_url = "/admin"
        
    response = RedirectResponse(url=redirect_url, status_code=303)
    
    return response

@router.get("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)

# 하이브리드 인증 (세션 또는 JWT)
async def get_admin_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    # 1. 세션 인증 확인
    user_id = request.session.get("user_id")
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if user and getattr(user, "is_admin", False):
            return user
    
    # 2. JWT 토큰 인증 확인 (세션 인증 실패 시)
    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email = payload.get("sub")
            if email:
                user = db.query(User).filter(User.email == email).first()
                if user and getattr(user, "is_admin", False):
                    return user
        except jwt.PyJWTError:
            pass
    
    # 인증 실패
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 필요",
        headers={"WWW-Authenticate": "Bearer"},
    )

@router.get("/admin")
async def admin_page(
    request: Request, 
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    notices = db.query(Notice).order_by(Notice.is_pinned.desc(), Notice.created_at.desc()).all()
    return templates.TemplateResponse("admin_notice.html", {"request": request, "notices": notices})

@router.post("/admin/create")
async def create_notice(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    is_pinned: str = Form(None),
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    db_notice = Notice(
        title=title,
        content=content,
        is_pinned=bool(is_pinned),
        created_at=datetime.now()
    )
    db.add(db_notice)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/update/{notice_id}")
async def update_notice(
    request: Request,
    notice_id: int,
    title: str = Form(...),
    content: str = Form(...),
    is_pinned: str = Form(None),
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    db_notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if db_notice:
        db_notice.title = title
        db_notice.content = content
        db_notice.is_pinned = bool(is_pinned)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/delete/{notice_id}")
async def delete_notice(
    request: Request,
    notice_id: int,
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    db_notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if db_notice:
        db.delete(db_notice)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/admin/shuttle")
async def admin_shuttle_page(
    request: Request,
    current_admin = Depends(get_admin_user)
):
    return templates.TemplateResponse("shuttle_admin.html", {"request": request}) 