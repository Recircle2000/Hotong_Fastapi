from typing import List, Dict, Any
from sqlalchemy.ext.declarative import DeclarativeMeta
from datetime import datetime, date, time

def model_to_dict(obj) -> Dict:
    """
    SQLAlchemy 모델을 사전으로 변환합니다.
    """
    if hasattr(obj, '__table__'):  # SQLAlchemy 모델인 경우
        return {c.name: serialize_value(getattr(obj, c.name)) for c in obj.__table__.columns}
    else:
        # 기본 객체 처리
        return {k: serialize_value(v) for k, v in obj.__dict__.items() if not k.startswith('_')}

def serialize_value(value: Any) -> Any:
    """
    값을 JSON 직렬화 가능한 형태로 변환합니다.
    """
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    elif hasattr(value, '__table__'):  # SQLAlchemy 모델인 경우
        return model_to_dict(value)
    elif isinstance(value, list):
        return [serialize_value(item) for item in value]
    elif isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    elif hasattr(value, '__dict__') and not isinstance(value, (str, int, float, bool, type(None))):
        return model_to_dict(value)
    else:
        return value

def serialize_models(models: List) -> List[Dict]:
    """
    SQLAlchemy 모델 리스트를 사전 리스트로 변환합니다.
    """
    return [model_to_dict(model) for model in models] 