# 호통 백엔드 API

FastAPI 기반의 백엔드 API 서버입니다.

## 아키텍처

- **Nginx**: 리버스 프록시 및 SSL 터미네이션
- **FastAPI**: Python 웹 프레임워크
- **Redis**: 캐싱 및 세션 저장소
- **Docker**: 컨테이너화된 배포

## 빠른 시작

### 사전 요구사항
- Docker & Docker Compose
- SSL 인증서 (fullchain.pem, privkey.pem)

### 실행 방법
```bash
# 1. 프로젝트 클론
git clone <repository-url>
cd gotohoseo_backend

# 2. SSL 인증서 배치
cp /path/to/fullchain.pem ./certs/
cp /path/to/privkey.pem ./certs/

# 3. 환경 변수 설정
cp .env.example .env
# .env 파일 편집

# 4. 서비스 실행
docker-compose up -d
```

### 접속 정보
- HTTPS: https://hotong.click
- HTTP: http://hotong.click (자동으로 HTTPS로 리다이렉트)
- www.hotong.click → hotong.click으로 자동 리다이렉트

## 상세 문서

- [배포 가이드](DEPLOY.md)
- [Redis 설정](README_redis.md)

## 개발

로컬 개발 환경에서는 다음과 같이 실행할 수 있습니다:

```bash
# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 개발 서버 실행
uvicorn main:app --reload --host 0.0.0.0 --port 8000
``` 
