import redis
import json
from typing import Any, Dict, List, Optional

# Redis 클라이언트 설정
redis_client = redis.Redis(
    host='192.168.45.152',
    port=6379,
    db=0,
    decode_responses=True
)

# 캐시 만료 시간 (초)
CACHE_TTL = 60 * 60  # 1시간

def set_cache(key: str, data: Any, expire: int = CACHE_TTL) -> bool:
    """
    Redis에 데이터를 캐싱합니다.
    """
    try:
        serialized_data = json.dumps(data)
        return redis_client.set(key, serialized_data, ex=expire)
    except Exception as e:
        print(f"Redis 캐싱 오류: {e}")
        return False

def get_cache(key: str) -> Optional[Any]:
    """
    Redis에서 캐시된 데이터를 가져옵니다.
    """
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        print(f"Redis 캐시 조회 오류: {e}")
        return None

def delete_cache(key: str) -> bool:
    """
    Redis에서 캐시를 삭제합니다.
    """
    try:
        return redis_client.delete(key) > 0
    except Exception as e:
        print(f"Redis 캐시 삭제 오류: {e}")
        return False

def delete_pattern(pattern: str) -> int:
    """
    패턴에 일치하는 모든 키를 삭제합니다.
    """
    try:
        keys = redis_client.keys(pattern)
        if keys:
            return redis_client.delete(*keys)
        return 0
    except Exception as e:
        print(f"Redis 패턴 삭제 오류: {e}")
        return 0 