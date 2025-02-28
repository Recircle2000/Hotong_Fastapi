from fastapi import FastAPI
from routers import auth, bus
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# API 라우터 등록
app.include_router(auth.router, tags=["Authentication"])
app.include_router(bus.router, tags=["Bus"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용 (보안이 중요하면 특정 도메인만 허용!)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "Welcome to University Transport Service"}
