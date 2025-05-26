from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from database import get_db
from models.notice import Notice, NoticeType
from utils.security import get_current_admin

router = APIRouter(
    prefix="/notices",
    tags=["Notices"]
)

# Pydantic 모델
class NoticeBase(BaseModel):
    title: str
    content: str
    notice_type: NoticeType = NoticeType.APP
    is_pinned: bool = False

class NoticeCreate(NoticeBase):
    pass

class NoticeUpdate(NoticeBase):
    title: Optional[str] = None
    content: Optional[str] = None
    notice_type: Optional[NoticeType] = None
    is_pinned: Optional[bool] = None

class NoticeResponse(NoticeBase):
    id: int
    created_at: datetime
    
    class Config:
        orm_mode = True

# 모든 공지사항 조회
@router.get("/", response_model=List[NoticeResponse])
def get_all_notices(notice_type: Optional[NoticeType] = None, db: Session = Depends(get_db)):
    """
    모든 공지사항을 조회합니다.
    notice_type 파라미터로 특정 유형의 공지사항만 필터링할 수 있습니다.
    공지사항은 고정 여부와 생성일 기준으로 정렬됩니다.
    """
    query = db.query(Notice)
    if notice_type:
        query = query.filter(Notice.notice_type == notice_type)
    notices = query.order_by(Notice.is_pinned.desc(), Notice.created_at.desc()).all()
    return notices

# 가장 최근 공지사항 1개 조회
@router.get("/latest", response_model=NoticeResponse)
def get_latest_notice(notice_type: Optional[NoticeType] = None, db: Session = Depends(get_db)):
    """
    가장 최근에 작성된 공지사항 1개를 조회합니다.
    notice_type 파라미터로 특정 유형의 공지사항만 필터링할 수 있습니다.
    공지사항이 없는 경우 404 오류를 반환합니다.
    """
    query = db.query(Notice)
    if notice_type:
        query = query.filter(Notice.notice_type == notice_type)
    notice = query.order_by(Notice.created_at.desc()).first()
    if notice is None:
        raise HTTPException(status_code=404, detail="공지사항이 없습니다")
    return notice

# 특정 공지사항 조회
@router.get("/{notice_id}", response_model=NoticeResponse)
def get_notice(notice_id: int, db: Session = Depends(get_db)):
    """
    특정 ID의 공지사항을 조회합니다.
    해당 ID의 공지사항이 없는 경우 404 오류를 반환합니다.
    """
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if notice is None:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    return notice

# 공지사항 생성 (관리자 권한 필요)
@router.post("/", response_model=NoticeResponse, status_code=status.HTTP_201_CREATED)
def create_notice(notice: NoticeCreate, db: Session = Depends(get_db), current_admin = Depends(get_current_admin)):
    """
    새 공지사항을 생성합니다. (관리자 권한 필요)
    """
    db_notice = Notice(
        title=notice.title,
        content=notice.content,
        notice_type=notice.notice_type,
        is_pinned=notice.is_pinned
    )
    db.add(db_notice)
    db.commit()
    db.refresh(db_notice)
    return db_notice

# 공지사항 수정 (관리자 권한 필요)
@router.put("/{notice_id}", response_model=NoticeResponse)
def update_notice(notice_id: int, notice: NoticeUpdate, db: Session = Depends(get_db), current_admin = Depends(get_current_admin)):
    """
    특정 ID의 공지사항을 수정합니다. (관리자 권한 필요)
    해당 ID의 공지사항이 없는 경우 404 오류를 반환합니다.
    """
    db_notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if db_notice is None:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    
    update_data = notice.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_notice, key, value)
    
    db.commit()
    db.refresh(db_notice)
    return db_notice

# 공지사항 삭제 (관리자 권한 필요)
@router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notice(notice_id: int, db: Session = Depends(get_db), current_admin = Depends(get_current_admin)):
    """
    특정 ID의 공지사항을 삭제합니다. (관리자 권한 필요)
    해당 ID의 공지사항이 없는 경우 404 오류를 반환합니다.
    """
    db_notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if db_notice is None:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
    
    db.delete(db_notice)
    db.commit()
    return None 