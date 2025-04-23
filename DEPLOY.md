# 도커를 이용한 배포 가이드

## 사전 요구 사항

- 도커 설치
- 도커 컴포즈 설치
- Git

## 서버에 배포하는 단계

### 1. 프로젝트 클론

```bash
git clone <repository-url>
cd gotohoseo_backend
```

### 2. 환경 변수 설정

`.env` 파일을 프로젝트 루트 디렉토리에 생성하고 필요한 환경 변수를 설정합니다.

```
API_KEY=<your-api-key>
DATABASE_URL=mysql+pymysql://<username>:<password>@<host>:<port>/bus_service
SERVER_URL=<server-url>
REDIS_HOST=redis
REDIS_PASSWORD=<your-redis-password>
SECRET_KEY=<your-secret-key>
```

> 참고: Docker Compose를 사용할 때는 REDIS_HOST를 `redis`로 설정해야 합니다 (서비스 이름).

### 3. 도커 이미지 빌드 및 실행

```bash
docker-compose up -d
```

이 명령어는 다음과 같은 작업을 수행합니다:
- API 서비스 이미지 빌드
- Redis 컨테이너 실행
- API 서비스 컨테이너 실행

### 4. 서비스 상태 확인

```bash
docker-compose ps
```

### 5. 로그 확인

```bash
docker-compose logs -f api
```

## 서비스 업데이트 방법

코드가 변경된 경우 다음 명령어로 서비스를 업데이트할 수 있습니다:

```bash
git pull
docker-compose build api
docker-compose up -d
```

## 서비스 중단

```bash
docker-compose down
```

## 데이터 유지

Redis 데이터는 Docker 볼륨 `redis-data`에 저장되므로 컨테이너를 재시작해도 유지됩니다.

모든 데이터를 삭제하고 싶은 경우:

```bash
docker-compose down -v
```

## 트러블슈팅

### Redis 연결 문제

API 서비스가 Redis에 연결할 수 없는 경우:

1. `.env` 파일에서 `REDIS_HOST`가 `redis`로 설정되어 있는지 확인
2. Redis 컨테이너가 실행 중인지 확인
3. Redis 비밀번호가 올바르게 설정되어 있는지 확인

```bash
docker-compose logs redis
```

### 데이터베이스 연결 문제

데이터베이스 연결에 문제가 있는 경우:

1. `.env` 파일의 `DATABASE_URL`이 올바른지 확인
2. 데이터베이스 서버가 실행 중인지 확인
3. 데이터베이스 사용자 권한이 올바르게 설정되어 있는지 확인 