# 배포 가이드

## 사전 준비

### 1. SSL 인증서 준비
```bash
# certs 디렉토리에 SSL 인증서 파일 배치
certs/
├── fullchain.pem  # SSL 인증서
└── privkey.pem    # 개인키
```

### 2. 환경 변수 설정
`.env` 파일을 생성하고 다음 변수들을 설정:
```
REDIS_PASSWORD=your_redis_password
DATABASE_URL=your_database_url
# 기타 필요한 환경 변수들...
```

## 배포 과정

### 1. 프로젝트 클론 및 이동
```bash
git clone <repository-url>
cd gotohoseo_backend
```

### 2. SSL 인증서 배치
```bash
# SSL 인증서를 certs 디렉토리에 복사
cp /path/to/your/fullchain.pem ./certs/
cp /path/to/your/privkey.pem ./certs/
```

### 3. 환경 변수 파일 생성
```bash
cp .env.example .env
# .env 파일을 편집하여 실제 값으로 설정
```

### 4. Docker Compose로 실행
```bash
# 백그라운드에서 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 서비스 상태 확인
docker-compose ps
```

## 서비스 구조

- **nginx**: 리버스 프록시 및 SSL 터미네이션 (포트 80, 443)
- **api**: FastAPI 애플리케이션 (내부 포트 8000)
- **redis**: Redis 캐시 서버 (포트 6379)

## 주요 기능

### SSL/TLS 설정
- HTTP 요청은 자동으로 HTTPS로 리다이렉트
- TLS 1.2, 1.3 지원
- 보안 헤더 자동 추가

### 로그 관리
- 각 서비스별 로그 로테이션 설정
- 최대 10MB, 3개 파일까지 보관

### 보안 설정
- X-Frame-Options, X-Content-Type-Options 등 보안 헤더
- HSTS (HTTP Strict Transport Security) 적용

## 관리 명령어

### 서비스 재시작
```bash
docker-compose restart
```

### 특정 서비스만 재시작
```bash
docker-compose restart api
docker-compose restart nginx
```

### 로그 확인
```bash
# 전체 로그
docker-compose logs

# 특정 서비스 로그
docker-compose logs api
docker-compose logs nginx

# 실시간 로그
docker-compose logs -f
```

### 서비스 중지
```bash
docker-compose down
```

### 완전 정리 (볼륨 포함)
```bash
docker-compose down -v
```

## 트러블슈팅

### SSL 인증서 문제
- `certs/` 디렉토리에 `fullchain.pem`과 `privkey.pem` 파일이 있는지 확인
- 인증서 파일의 권한 확인

### 서비스 연결 문제
- `docker-compose ps`로 모든 서비스가 실행 중인지 확인
- `docker-compose logs`로 에러 메시지 확인

### 포트 충돌
- 80, 443, 6379 포트가 다른 서비스에서 사용 중이지 않은지 확인 