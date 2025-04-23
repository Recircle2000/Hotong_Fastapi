from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from models.notice import Notice
from database import get_db
from datetime import datetime
from fastapi import Response
from starlette.middleware.sessions import SessionMiddleware
from models import User
from utils.security import verify_password

router = APIRouter()
templates = Jinja2Templates(directory="templates")

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
def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": None})

@router.post("/admin/login")
def admin_login(request: Request, db: Session = Depends(get_db), email: str = Form(...), password: str = Form(...)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("admin_login.html", {"request": request, "error": "로그인 실패: 아이디 또는 비밀번호가 올바르지 않습니다."})
    if not getattr(user, "is_admin", False):
        return templates.TemplateResponse("admin_login.html", {"request": request, "error": "관리자 권한이 없습니다."})
    request.session["user_id"] = user.id
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)

def require_admin(request: Request):
    if not request.session.get("user_id"):
        return False
    return True

@router.get("/admin")
def admin_page(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    notices = db.query(Notice).order_by(Notice.is_pinned.desc(), Notice.created_at.desc()).all()
    return templates.TemplateResponse("admin_notice.html", {"request": request, "notices": notices})

@router.post("/admin/create")
def create_notice(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    is_pinned: str = Form(None),
    db: Session = Depends(get_db)
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
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
def update_notice(
    request: Request,
    notice_id: int,
    title: str = Form(...),
    content: str = Form(...),
    is_pinned: str = Form(None),
    db: Session = Depends(get_db)
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    db_notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if db_notice:
        db_notice.title = title
        db_notice.content = content
        db_notice.is_pinned = bool(is_pinned)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/delete/{notice_id}")
def delete_notice(
    request: Request,
    notice_id: int,
    db: Session = Depends(get_db)
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    db_notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if db_notice:
        db.delete(db_notice)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/admin/shuttle")
def admin_shuttle_page(request: Request):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse("shuttle_admin.html", {"request": request}) 