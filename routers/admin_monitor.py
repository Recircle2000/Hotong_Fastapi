from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import psutil
import time
import json
from datetime import datetime, timedelta
from utils.redis_client import redis_client
from database import engine
from sqlalchemy import text
import asyncio
from utils.api_monitor import get_api_stats

router = APIRouter()
templates = Jinja2Templates(directory="templates")

def get_admin_session(request: Request):
    """어드민 세션 확인"""
    user_id = request.session.get("user_id")
    if not user_id:
        accepts_html = "text/html" in (request.headers.get("accept") or "").lower()
        if accepts_html:
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                detail="관리자 로그인이 필요합니다",
                headers={"Location": "/admin/login"},
            )
        raise HTTPException(status_code=401, detail="관리자 로그인이 필요합니다")
    return True

@router.get("/admin/monitor", response_class=HTMLResponse)
async def admin_monitor_page(request: Request, _: bool = Depends(get_admin_session)):
    """서버 모니터링 어드민 페이지"""
    return templates.TemplateResponse("admin_monitor.html", {"request": request})

@router.get("/admin/monitor/api/system-info")
async def get_system_info(_: bool = Depends(get_admin_session)):
    """시스템 정보 API"""
    try:
        # CPU 정보
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        
        # 메모리 정보
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # 디스크 정보
        disk = psutil.disk_usage('/')
        
        # 네트워크 정보
        network = psutil.net_io_counters()
        
        # 프로세스 정보
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                proc_info = proc.info
                if proc_info['cpu_percent'] > 0 or proc_info['memory_percent'] > 0:
                    processes.append(proc_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # CPU 사용률 높은 순으로 정렬
        processes = sorted(processes, key=lambda x: x['cpu_percent'], reverse=True)[:10]
        
        return {
            "timestamp": datetime.now().isoformat(),
            "cpu": {
                "percent": cpu_percent,
                "count": cpu_count,
                "frequency": cpu_freq.current if cpu_freq else None
            },
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "percent": memory.percent,
                "used": memory.used
            },
            "swap": {
                "total": swap.total,
                "used": swap.used,
                "free": swap.free,
                "percent": swap.percent
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": (disk.used / disk.total) * 100
            },
            "network": {
                "bytes_sent": network.bytes_sent,
                "bytes_recv": network.bytes_recv,
                "packets_sent": network.packets_sent,
                "packets_recv": network.packets_recv
            },
            "top_processes": processes
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시스템 정보 조회 실패: {str(e)}")

@router.get("/admin/monitor/api/database-info")
async def get_database_info(_: bool = Depends(get_admin_session)):
    """데이터베이스 정보 API"""
    try:
        with engine.connect() as conn:
            # 활성 연결 수
            active_connections = conn.execute(text("SHOW STATUS LIKE 'Threads_connected'")).fetchone()
            max_connections = conn.execute(text("SHOW VARIABLES LIKE 'max_connections'")).fetchone()
            
            # 쿼리 통계
            queries = conn.execute(text("SHOW STATUS LIKE 'Queries'")).fetchone()
            slow_queries = conn.execute(text("SHOW STATUS LIKE 'Slow_queries'")).fetchone()
            
            # 테이블 크기 정보
            table_sizes = conn.execute(text("""
                SELECT 
                    table_name,
                    ROUND(((data_length + index_length) / 1024 / 1024), 2) AS size_mb
                FROM information_schema.tables 
                WHERE table_schema = DATABASE()
                ORDER BY (data_length + index_length) DESC
                LIMIT 10
            """)).fetchall()
            
            return {
                "timestamp": datetime.now().isoformat(),
                "connections": {
                    "active": active_connections[1] if active_connections else 0,
                    "max": max_connections[1] if max_connections else 0
                },
                "queries": {
                    "total": queries[1] if queries else 0,
                    "slow": slow_queries[1] if slow_queries else 0
                },
                "table_sizes": [{"name": row[0], "size_mb": row[1]} for row in table_sizes]
            }
    except Exception as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "error": f"데이터베이스 정보 조회 실패: {str(e)}"
        }

@router.get("/admin/monitor/api/redis-info")
async def get_redis_info(_: bool = Depends(get_admin_session)):
    """Redis 정보 API"""
    try:
        info = redis_client.info()
        
        # 메모리 사용량
        memory_info = {
            "used_memory": info.get('used_memory', 0),
            "used_memory_human": info.get('used_memory_human', '0B'),
            "used_memory_peak": info.get('used_memory_peak', 0),
            "used_memory_peak_human": info.get('used_memory_peak_human', '0B'),
            "maxmemory": info.get('maxmemory', 0)
        }
        
        # 연결 정보
        connection_info = {
            "connected_clients": info.get('connected_clients', 0),
            "blocked_clients": info.get('blocked_clients', 0),
            "total_connections_received": info.get('total_connections_received', 0)
        }
        
        # 키 통계
        keyspace_info = {}
        for key, value in info.items():
            if key.startswith('db'):
                keyspace_info[key] = value
        
        # 성능 통계
        stats_info = {
            "total_commands_processed": info.get('total_commands_processed', 0),
            "instantaneous_ops_per_sec": info.get('instantaneous_ops_per_sec', 0),
            "keyspace_hits": info.get('keyspace_hits', 0),
            "keyspace_misses": info.get('keyspace_misses', 0)
        }
        
        # 히트율 계산
        hits = stats_info['keyspace_hits']
        misses = stats_info['keyspace_misses']
        hit_rate = (hits / (hits + misses)) * 100 if (hits + misses) > 0 else 0
        
        return {
            "timestamp": datetime.now().isoformat(),
            "memory": memory_info,
            "connections": connection_info,
            "keyspace": keyspace_info,
            "stats": {**stats_info, "hit_rate": round(hit_rate, 2)},
            "uptime": info.get('uptime_in_seconds', 0)
        }
    except Exception as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "error": f"Redis 정보 조회 실패: {str(e)}"
        }

@router.get("/admin/monitor/api/application-info")
async def get_application_info(_: bool = Depends(get_admin_session)):
    """애플리케이션 정보 API"""
    try:
        # 현재 프로세스 정보
        current_process = psutil.Process()
        
        # 메모리 사용량
        memory_info = current_process.memory_info()
        
        # CPU 사용량
        cpu_percent = current_process.cpu_percent()
        
        # 파일 디스크립터 수
        try:
            num_fds = current_process.num_fds()
        except AttributeError:
            # Windows에서는 지원하지 않음
            num_fds = None
        
        # 스레드 수
        num_threads = current_process.num_threads()
        
        # 실행 시간
        create_time = current_process.create_time()
        uptime = time.time() - create_time
        
        # API 통계 가져오기
        api_stats = get_api_stats()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "process_id": current_process.pid,
            "memory": {
                "rss": memory_info.rss,
                "vms": memory_info.vms,
                "percent": current_process.memory_percent()
            },
            "cpu_percent": cpu_percent,
            "num_threads": num_threads,
            "num_fds": num_fds,
            "uptime_seconds": uptime,
            "create_time": datetime.fromtimestamp(create_time).isoformat(),
            "api_stats": api_stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"애플리케이션 정보 조회 실패: {str(e)}")

@router.get("/admin/monitor/api/logs")
async def get_recent_logs(_: bool = Depends(get_admin_session), lines: int = 100):
    """최근 로그 조회 API"""
    try:
        # 실제 로그 파일 경로는 환경에 따라 조정 필요
        log_files = [
            "/var/log/app.log",
            "app.log",
            "logs/app.log"
        ]
        
        logs = []
        for log_file in log_files:
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    file_logs = f.readlines()
                    logs.extend(file_logs[-lines:])
                break
            except FileNotFoundError:
                continue
        
        if not logs:
            logs = ["로그 파일을 찾을 수 없습니다."]
        
        return {
            "timestamp": datetime.now().isoformat(),
            "logs": logs[-lines:]
        }
    except Exception as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "error": f"로그 조회 실패: {str(e)}",
            "logs": []
        } 
