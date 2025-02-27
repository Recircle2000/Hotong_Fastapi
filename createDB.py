from database import engine, Base

# 수동으로 테이블 생성
Base.metadata.create_all(bind=engine)