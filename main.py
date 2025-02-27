from fastapi import FastAPI
from routers import auth, bus

app = FastAPI()

# API 라우터 등록
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(bus.router, prefix="/bus", tags=["Bus"])

@app.get("/")
def home():
    return {"message": "Welcome to University Transport Service"}
