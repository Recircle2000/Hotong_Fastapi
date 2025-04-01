# main.py 수정
from fastapi import FastAPI
from routers import auth, bus, notice
from fastapi.middleware.cors import CORSMiddleware
import asyncio

app = FastAPI()

# API 라우터 등록
app.include_router(auth.router, tags=["Authentication"])
app.include_router(bus.router, tags=["Bus"])
app.include_router(notice.router, tags=["Notices"])
#app.include_router(shuttle.router, prefix="/shuttle", tags=["Shuttle"])

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

@app.get("/")
def home():
    return {"message": "Welcome to University Transport Service"}