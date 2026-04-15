from types import SimpleNamespace
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import User
from models.emergency_notice import EmergencyNotice, EmergencyNoticeCategory
from services.admin_emergency_notice import (
    INVALID_TIME_RANGE_MESSAGE,
    create_admin_emergency_notice,
    delete_admin_emergency_notice,
    list_admin_emergency_notices,
    update_admin_emergency_notice,
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
    update_admin_notice,
)
from services.dashboard_utils import (
    get_now_kst_naive,
    parse_datetime_local,
    sanitize_redirect_path,
    to_kst_naive,
)


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
        <title>API Dashboard</title>
        <style>
            body { font-family: 'Segoe UI', sans-serif; margin: 40px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px; }
            th { background: #f2f2f2; }
            tr:hover { background: #f9f9f9; }
        </style>
    </head>
    <body>
        <h2>API Dashboard</h2>
        <table>
            <tr><th>Path</th><th>Method</th><th>Description</th></tr>
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
    if request.session.get("user_id"):
        return RedirectResponse(url="/admin", status_code=303)

    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": error, "redirect": redirect},
    )


@router.post("/admin/login")
def admin_login(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
    redirect: str = Form(None),
):
    try:
        user = authenticate_admin_credentials(db, email, password)
    except AdminAuthError as exc:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": exc.message, "redirect": redirect},
        )

    login_admin_session(request, user)
    redirect_url = sanitize_redirect_path(redirect)
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/admin/logout")
def admin_logout(request: Request):
    clear_admin_session(request)
    return RedirectResponse(url="/admin/login", status_code=303)


async def get_admin_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    user = resolve_admin_user(request, db, token)
    if user:
        return user

    accepts_html = "text/html" in (request.headers.get("accept") or "").lower()
    if accepts_html:
        redirect_target = request.url.path
        if request.url.query:
            redirect_target = f"{redirect_target}?{request.url.query}"
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail=AUTH_REQUIRED_MESSAGE,
            headers={"Location": f"/admin/login?redirect={quote(redirect_target, safe='')}"},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AUTH_REQUIRED_MESSAGE,
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.get("/admin")
async def admin_page(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_admin_user),
):
    del current_admin
    notices = list_admin_notices(db)
    return templates.TemplateResponse("admin_notice.html", {"request": request, "notices": notices})


@router.post("/admin/create")
async def create_notice(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    notice_type: str = Form("App"),
    is_pinned: str = Form(None),
    db: Session = Depends(get_db),
    current_admin=Depends(get_admin_user),
):
    del request, current_admin
    create_admin_notice(
        db,
        title=title,
        content=content,
        notice_type=notice_type,
        is_pinned=is_pinned,
    )
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
    current_admin=Depends(get_admin_user),
):
    del request, current_admin
    update_admin_notice(
        db,
        notice_id=notice_id,
        title=title,
        content=content,
        notice_type=notice_type,
        is_pinned=is_pinned,
    )
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/delete/{notice_id}")
async def delete_notice(
    request: Request,
    notice_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(get_admin_user),
):
    del request, current_admin
    delete_admin_notice(db, notice_id=notice_id)
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/admin/shuttle")
async def admin_shuttle_page(
    request: Request,
    current_admin=Depends(get_admin_user),
):
    del current_admin
    return templates.TemplateResponse("shuttle_admin.html", {"request": request})


@router.get("/admin/emergency-notices")
async def admin_emergency_notice_page(
    request: Request,
    error: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_admin=Depends(get_admin_user),
):
    del current_admin
    notices = [
        SimpleNamespace(
            id=notice.id,
            category=notice.category,
            title=notice.title,
            content=notice.content,
            created_at=to_kst_naive(notice.created_at),
            end_at=to_kst_naive(notice.end_at),
        )
        for notice in list_admin_emergency_notices(db)
    ]
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
    current_admin=Depends(get_admin_user),
):
    del request, current_admin
    try:
        category_enum = EmergencyNoticeCategory(category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="유효하지 않은 구분 값입니다.") from exc

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
    current_admin=Depends(get_admin_user),
):
    del request, current_admin
    try:
        category_enum = EmergencyNoticeCategory(category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="유효하지 않은 구분 값입니다.") from exc

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
    current_admin=Depends(get_admin_user),
):
    del request, current_admin
    notice = db.query(EmergencyNotice).filter(EmergencyNotice.id == notice_id).first()
    if notice:
        db.delete(notice)
        db.commit()
    return RedirectResponse(url="/admin/emergency-notices", status_code=303)
