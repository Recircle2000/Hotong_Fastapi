from fastapi import APIRouter, Request, Depends, Form, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from models.notice import Notice
from models.emergency_notice import EmergencyNotice, EmergencyNoticeCategory
from database import get_db
from datetime import datetime, timedelta, timezone
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
KST = timezone(timedelta(hours=9))


def get_now_kst_naive() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def parse_datetime_local(value: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="종료시간 형식이 올바르지 않습니다.")

@router.get("/apis")
async def get_api_list(request: Request):
    """
    모든 API 엔드포인트 목록을 반환합니다.
    """
    openapi_schema = request.app.openapi()
    return openapi_schema["paths"]

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """
    API 대시보드 페이지를 제공합니다.
    모든 API 엔드포인트와 설명을 HTML 테이블로 표시합니다.
    """
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
    """
    관리자 로그인 페이지를 제공합니다.
    이미 로그인된 경우 관리자 페이지로 리다이렉트합니다.
    """
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
    """
    관리자 로그인 처리를 수행합니다.
    성공 시 지정된 리다이렉트 URL 또는 관리자 페이지로 리다이렉트합니다.
    실패 시 오류 메시지와 함께 로그인 페이지로 이동합니다.
    """
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
    """
    관리자 로그아웃을 처리합니다.
    세션을 초기화하고 로그인 페이지로 리다이렉트합니다.
    """
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)

# 하이브리드 인증 (세션 또는 JWT)
async def get_admin_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """
    세션 또는 JWT 토큰을 통한 관리자 인증을 처리합니다.
    인증 실패 시 401 오류를 반환합니다.
    """
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
    """
    관리자 메인 페이지(공지사항 관리)를 제공합니다.
    관리자 인증이 필요합니다.
    """
    notices = db.query(Notice).order_by(Notice.is_pinned.desc(), Notice.created_at.desc()).all()
    return templates.TemplateResponse("admin_notice.html", {"request": request, "notices": notices})

@router.post("/admin/create")
async def create_notice(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    notice_type: str = Form("App"),
    is_pinned: str = Form(None),
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    """
    새 공지사항을 생성합니다.
    관리자 인증이 필요합니다.
    """
    from models.notice import NoticeType
    
    # notice_type 문자열을 enum으로 변환
    try:
        notice_type_enum = NoticeType(notice_type)
    except ValueError:
        notice_type_enum = NoticeType.APP
    
    db_notice = Notice(
        title=title,
        content=content,
        notice_type=notice_type_enum,
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
    notice_type: str = Form("App"),
    is_pinned: str = Form(None),
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    """
    기존 공지사항을 수정합니다.
    관리자 인증이 필요합니다.
    """
    from models.notice import NoticeType
    
    # notice_type 문자열을 enum으로 변환
    try:
        notice_type_enum = NoticeType(notice_type)
    except ValueError:
        notice_type_enum = NoticeType.APP
    
    db_notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if db_notice:
        db_notice.title = title
        db_notice.content = content
        db_notice.notice_type = notice_type_enum
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
    """
    공지사항을 삭제합니다.
    관리자 인증이 필요합니다.
    """
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
    """
    셔틀 관리 페이지를 제공합니다.
    관리자 인증이 필요합니다.
    """
    return templates.TemplateResponse("shuttle_admin.html", {"request": request}) 


@router.get("/admin/emergency-notices")
async def admin_emergency_notice_page(
    request: Request,
    error: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    notices = db.query(EmergencyNotice).order_by(EmergencyNotice.created_at.desc()).all()
    return templates.TemplateResponse(
        "admin_emergency_notice.html",
        {
            "request": request,
            "notices": notices,
            "now_kst": get_now_kst_naive(),
            "error": error,
        },
    )


@router.post("/admin/emergency-notices/create")
async def create_emergency_notice(
    request: Request,
    category: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    created_at: str = Form(None),
    end_at: str = Form(...),
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    try:
        category_enum = EmergencyNoticeCategory(category)
    except ValueError:
        raise HTTPException(status_code=400, detail="유효하지 않은 구분 값입니다.")

    created_at_dt = parse_datetime_local(created_at) if created_at else get_now_kst_naive()
    end_at_dt = parse_datetime_local(end_at)
    if created_at_dt > end_at_dt:
        return RedirectResponse(url="/admin/emergency-notices?error=invalid_time_range", status_code=303)

    new_notice = EmergencyNotice(
        category=category_enum,
        title=title.strip(),
        content=content.strip(),
        created_at=created_at_dt,
        end_at=end_at_dt,
    )
    db.add(new_notice)
    db.commit()
    return RedirectResponse(url="/admin/emergency-notices", status_code=303)


@router.post("/admin/emergency-notices/update/{notice_id}")
async def update_emergency_notice(
    request: Request,
    notice_id: int,
    category: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    created_at: str = Form(None),
    end_at: str = Form(...),
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    try:
        category_enum = EmergencyNoticeCategory(category)
    except ValueError:
        raise HTTPException(status_code=400, detail="유효하지 않은 구분 값입니다.")

    created_at_dt = parse_datetime_local(created_at) if created_at else None
    end_at_dt = parse_datetime_local(end_at)
    if created_at_dt and created_at_dt > end_at_dt:
        return RedirectResponse(url="/admin/emergency-notices?error=invalid_time_range", status_code=303)
    notice = db.query(EmergencyNotice).filter(EmergencyNotice.id == notice_id).first()
    if notice is None:
        raise HTTPException(status_code=404, detail="긴급공지 정보를 찾을 수 없습니다.")

    notice.category = category_enum
    notice.title = title.strip()
    notice.content = content.strip()
    if created_at_dt:
        notice.created_at = created_at_dt
    notice.end_at = end_at_dt
    db.commit()
    return RedirectResponse(url="/admin/emergency-notices", status_code=303)


@router.post("/admin/emergency-notices/delete/{notice_id}")
async def delete_emergency_notice(
    request: Request,
    notice_id: int,
    db: Session = Depends(get_db),
    current_admin = Depends(get_admin_user)
):
    notice = db.query(EmergencyNotice).filter(EmergencyNotice.id == notice_id).first()
    if notice:
        db.delete(notice)
        db.commit()
    return RedirectResponse(url="/admin/emergency-notices", status_code=303)
