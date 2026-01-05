# main.py 수정
from fastapi import FastAPI
from routers import auth, bus, notice, shuttle, dashboard, admin_monitor, subway
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from utils.redis_client import redis_client
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
import os
from database import engine
from utils.api_monitor import APIMonitorMiddleware
import utils.api_monitor as api_monitor_module

app = FastAPI()

# API 모니터링 미들웨어 추가
app.add_middleware(APIMonitorMiddleware)

app.add_middleware(SessionMiddleware, secret_key="supersecretkey123!@#")

# 정적 파일 폴더가 없는 경우 생성
if not os.path.exists("static"):
    os.makedirs("static")

# 정적 파일 제공
app.mount("/static", StaticFiles(directory="static"), name="static")

# API 라우터 등록
app.include_router(auth.router, tags=["Authentication"])
app.include_router(bus.router, tags=["Bus"])
app.include_router(notice.router, tags=["Notices"])
app.include_router(shuttle.router, prefix="/shuttle", tags=["Shuttle"])
app.include_router(dashboard.router)
app.include_router(admin_monitor.router, tags=["Admin Monitor"])
app.include_router(subway.router, tags=["Subway"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(bus.update_bus_data_periodically())
    
    # API 모니터링 미들웨어 확인
    if api_monitor_module.api_monitor:
        print("API 모니터링 미들웨어 초기화 성공")
    else:
        print("API 모니터링 미들웨어 초기화 실패")
    
    # Redis 연결 확인
    try:
        redis_client.ping()
        print("Redis 서버 연결 성공")
    except Exception as e:
        print(f"Redis 서버 연결 실패: {e}")
    
    # 데이터베이스 연결 확인
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        print("데이터베이스 연결 성공")
    except Exception as e:
        print(f"데이터베이스 연결 실패: {e}")

@app.get("/")
def home():
    return {"message": "Welcome to University Transport Service"}

@app.get("/health")
def health_check():
    # Redis 연결 상태 확인
    redis_status = "healthy" if redis_client.ping() else "unhealthy"
    
    # 데이터베이스 연결 상태 확인
    db_status = "healthy"
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
    except Exception:
        db_status = "unhealthy"
    
    return {
        "api": "healthy",
        "redis": redis_status,
        "database": db_status
    }