import requests
import json
import re
import os

# API 기본 정보
API_URL = "http://apis.data.go.kr/1613000/BusRouteInfoInqireService/getRouteAcctoThrghSttnList"
API_KEY = "kSkqn5bgn8LgTC9jUY+CGqqcdIzVhyNl43a+bSfbU1QHu/rkFnB4Bc4b/EcdgltpoLhNfn3zSabBQJFmPGY13Q=="  # URL 인코딩된 인증키 입력
CITY_CODE = "34040"

# 주어진 버스 노선 정보 (주석 포함하여 모든 노선을 처리)
ROUTES = {
    "순환5_DOWN": "ASB288000141",  # 호서대학교 출발 (하행)
    "순환5_UP": "ASB288000286",  # 천안아산역 출발 (상행)
    "810_DOWN": "ASB288000276",  # 호서대학교 출발 (하행)
    "810_UP": "ASB288000091",  # 시외버스터미널 출발 (상행)
    "820_DOWN": "ASB288000277",  # 호서대학교 출발 (하행)
    "820_UP": "ASB288000092",  # 시외버스터미널 출발 (상행)
    "821_DOWN": "ASB288000333",  # 호서대학교 출발 (하행)
    "821_UP": "ASB288000332",  # 시외버스터미널 출발 (상행)
    "1000_DOWN": "ASB288000352",  # 호서대학교 출발 (하행)
    "1000_UP": "ASB288000353",  # 탕정역 출발 (상행)
    "1001_UP": "ASB288000358",  # 포스코 아파트 출발 (상행)
}


def fetch_bus_route(route_name, route_id):
    params = {
        "serviceKey": API_KEY,
        "cityCode": CITY_CODE,
        "routeId": route_id,
        "numOfRows": 100,
        "pageNo": 1,
        "_type": "json"
    }

    response = requests.get(API_URL, params=params)

    print(f"📌 {route_name} 응답 코드: {response.status_code}")
    print(f"📌 {route_name} 응답 내용:\n{response.text[:500]}")  # 처음 500자만 출력

    if response.status_code == 200:
        try:
            data = response.json()
            file_name = f"{route_name}.json"
            with open(file_name, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"✅ {route_name} 데이터 저장 완료: {file_name}")
        except json.JSONDecodeError:
            print(f"❌ JSON 디코딩 오류 발생: {route_name}")
            print(f"❗ 응답 내용 확인 필요: {response.text}")
    else:
        print(f"❌ API 요청 실패 ({route_name}): {response.status_code}")


if __name__ == "__main__":
    for name, route_id in ROUTES.items():
        fetch_bus_route(name, route_id)
