# main.py 수정
from fastapi import FastAPI
from routers import auth, bus, notice, shuttle, dashboard
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from utils.redis_client import redis_client
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="supersecretkey123!@#")

# API 라우터 등록
app.include_router(auth.router, tags=["Authentication"])
app.include_router(bus.router, tags=["Bus"])
app.include_router(notice.router, tags=["Notices"])
app.include_router(shuttle.router, prefix="/shuttle", tags=["Shuttle"])
app.include_router(dashboard.router)

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
    # Redis 연결 확인
    try:
        redis_client.ping()
        print("Redis 서버 연결 성공")
    except Exception as e:
        print(f"Redis 서버 연결 실패: {e}")

@app.get("/")
def home():
    return {"message": "Welcome to University Transport Service"}

@app.get("/health")
def health_check():
    # Redis 연결 상태 확인
    redis_status = "healthy" if redis_client.ping() else "unhealthy"
    
    return {
        "api": "healthy",
        "redis": redis_status
    }