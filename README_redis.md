# Redis 캐싱 적용 가이드

## 1. 개요

API 엔드포인트에 Redis 캐싱을 적용하여 다음과 같은 이점을 얻을 수 있습니다:

- 서버 부하 감소
- 응답 시간 단축
- 데이터베이스 부하 분산
- 고가용성 제공

## 2. 캐싱 적용 엔드포인트

### 2.1 셔틀 버스

- `/shuttle/schedules`: 셔틀 스케줄 조회
- `/shuttle/schedules/{schedule_id}/stops`: 특정 스케줄의 정류장 정보
- `/shuttle/stations/{station_id}/schedules`: 특정 정류장의 스케줄 정보
- `/shuttle/stations`: 모든 정류장 또는 특정 정류장 정보 
- `/shuttle/routes`: 모든 노선 또는 특정 노선 정보

### 2.2 시내 버스

- `/buses`: 모든 버스 노선 정보
- `/buses/{route_name}`: 특정 노선의 버스 정보
- WebSocket(`/ws/bus`): 실시간 버스 위치 정보

## 3. 캐시 관리

### 3.1 캐시 TTL (Time-To-Live)

- 셔틀 데이터: 기본적으로 30분 동안 유효 (utils/redis_client.py의 `CACHE_TTL` 값)
- 버스 데이터: 60초 동안 유효 (routers/bus.py의 `BUS_CACHE_TTL` 값)

### 3.2 캐시 무효화

데이터가 변경되었을 때 캐시를 무효화하려면 다음 API를 사용할 수 있습니다:

#### 셔틀 데이터 캐시 무효화
```http
POST /shuttle/cache/invalidate?pattern=shuttle:*
```

패턴 매개변수 예시:
- `shuttle:*`: 모든 셔틀 관련 캐시 삭제
- `shuttle:schedules:*`: 스케줄 관련 캐시만 삭제
- `shuttle:stations:*`: 정류장 관련 캐시만 삭제

#### 버스 데이터 캐시 무효화
```http
POST /buses/cache/invalidate?route_name=900_UP
```

- `route_name` 지정: 특정 노선의 캐시만 삭제
- `route_name` 미지정: 모든 버스 노선의 캐시 삭제

## 4. Redis 설정

현재 Redis 서버는 다음과 같이 설정되어 있습니다:
- 호스트: 192.168.45.152
- 포트: 6379
- 데이터베이스: 0

설정을 변경하려면 `utils/redis_client.py` 파일을 수정하세요.

## 5. 서버 상태 확인

Redis 서버 연결 상태를 확인하려면 다음 엔드포인트를 사용할 수 있습니다:

```http
GET /health
```

응답 예시:
```json
{
  "api": "healthy",
  "redis": "healthy"
}
```

## 6. 성능 모니터링

Redis INFO 명령어를 사용하여 캐시 적중률(hit rate) 및 메모리 사용량을 모니터링할 수 있습니다:

```bash
redis-cli -h 192.168.45.152 info stats | grep hit_rate
redis-cli -h 192.168.45.152 info memory
```

## 7. 주의 사항

- Redis 서버가 다운되더라도 애플리케이션은 정상적으로 작동합니다 (캐시 미스 시 데이터베이스에서 조회).
- 데이터가 자주 변경되는 경우 캐시 TTL을 더 짧게 설정하는 것이 좋습니다.
- 대용량 데이터를 캐싱할 경우 Redis 서버의 메모리 사용량을 모니터링하세요.
- 버스 데이터는 외부 API에서 가져오는 실시간 데이터이므로 TTL이 60초로 짧게 설정되어 있습니다. 