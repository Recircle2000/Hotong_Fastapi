import time
from collections import defaultdict, deque
from threading import Lock
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

class APIMonitorMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.request_counts = defaultdict(int)
        self.request_times = deque()
        self.lock = Lock()
        
        # 전역 인스턴스로 설정
        global api_monitor
        api_monitor = self
        
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # 어드민 관련 모든 API는 집계에서 제외
        is_admin_api = request.url.path.startswith('/admin')
        
        if not is_admin_api:
            # 요청 카운트 증가
            with self.lock:
                self.request_counts['total'] += 1
                self.request_times.append(start_time)
                
                # 1분 이상 된 요청 기록 제거
                cutoff_time = start_time - 60
                while self.request_times and self.request_times[0] < cutoff_time:
                    self.request_times.popleft()
                
                # 디버깅용 로그 (처음 몇 개 요청만)
                if self.request_counts['total'] <= 5:
                    print(f"API 요청 감지: {request.url.path} (총 {self.request_counts['total']}번째)")
        
        response = await call_next(request)
        
        if not is_admin_api:
            # 응답 상태별 카운트
            status_code = response.status_code
            with self.lock:
                if 200 <= status_code < 300:
                    self.request_counts['success'] += 1
                elif 400 <= status_code < 500:
                    self.request_counts['client_error'] += 1
                elif 500 <= status_code < 600:
                    self.request_counts['server_error'] += 1
        
        return response
    
    def get_stats(self):
        """API 통계 반환"""
        with self.lock:
            current_time = time.time()
            
            # 최근 1분간의 요청 수 계산
            cutoff_time = current_time - 60
            recent_requests = sum(1 for t in self.request_times if t >= cutoff_time)
            
            # 초당 요청 수 계산 (최근 1분 평균)
            requests_per_second = recent_requests / 60.0
            
            return {
                'total_requests': self.request_counts['total'],
                'success_requests': self.request_counts['success'],
                'client_errors': self.request_counts['client_error'],
                'server_errors': self.request_counts['server_error'],
                'requests_per_minute': recent_requests,
                'requests_per_second': round(requests_per_second, 2)
            }

# 전역 인스턴스
api_monitor = None

def get_api_stats():
    """API 통계 가져오기"""
    if api_monitor:
        stats = api_monitor.get_stats()
        # 디버깅용 로그 (가끔씩만)
        if stats['total_requests'] % 10 == 0 and stats['total_requests'] > 0:
            print(f"API 통계: 총 {stats['total_requests']}개 요청, 초당 {stats['requests_per_second']}/s")
        return stats
    else:
        print("API 모니터 인스턴스가 없습니다")
        return {
            'total_requests': 0,
            'success_requests': 0,
            'client_errors': 0,
            'server_errors': 0,
            'requests_per_minute': 0,
            'requests_per_second': 0
        } 