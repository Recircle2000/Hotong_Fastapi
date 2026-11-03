"""깃허브 페이지에서 관리하던 시내버스 시간표·노선도를 DB와 Storage로 옮긴다 (한 번만 실행).

    python -m tools.import_city_bus_data --dry-run   # 무엇을 넣을지 확인만
    python -m tools.import_city_bus_data             # 실제로 넣기

- city_bus_routes 초안을 채운다. 이미 있는 노선은 건너뛴다(--overwrite로 덮어쓰기).
- 지금 버전(bus_times.json, 깃허브 매니페스트)을 그대로 게시본으로 등록한다.
  앱이 가진 버전과 같아서 첫 배포 때 앱이 다시 내려받지 않는다.
- 노선도 파일은 bus-data 버킷에 bus-static/{version}.json으로 올린다.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv


GITHUB_BASE = "https://recircle2000.github.io/hotong_station_image"
DEFAULT_TIMETABLE_PATH = Path(__file__).resolve().parent.parent / "bus_times.json"


def fetch_json(url: str) -> dict:
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    return response.json()


def load_sources(timetable_path: Path) -> tuple[dict, dict, dict]:
    timetable = json.loads(timetable_path.read_text(encoding="utf-8"))
    manifest = fetch_json(f"{GITHUB_BASE}/bus_static_manifest.json")
    static = fetch_json(manifest.get("downloadUrl") or f"{GITHUB_BASE}/bus_static_data.json")
    if static.get("version") != manifest.get("version"):
        raise SystemExit(f"깃허브 매니페스트({manifest.get('version')})와 노선도 파일({static.get('version')}) 버전이 다릅니다.")
    return timetable, manifest, static


def ordered_route_keys(timetable: dict, static: dict) -> list[str]:
    # 시간표 파일 순서(앱 화면 순서)를 먼저 따르고, 노선도에만 있는 노선은 뒤에 붙인다.
    keys = [key for key in timetable if key != "version"]
    for key in list(static.get("routes", {})) + list(static.get("stops", {})):
        if key not in keys:
            keys.append(key)
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timetable", type=Path, default=DEFAULT_TIMETABLE_PATH)
    parser.add_argument("--dry-run", action="store_true", help="DB와 Storage는 건드리지 않고 요약만 출력")
    parser.add_argument("--overwrite", action="store_true", help="이미 있는 노선 초안도 덮어쓰기")
    args = parser.parse_args()

    load_dotenv()
    timetable, manifest, static = load_sources(args.timetable)
    keys = ordered_route_keys(timetable, static)

    print(f"시간표 버전 {timetable['version']}, 노선도 버전 {static['version']} (적용 {manifest.get('effectiveFrom')})")
    for index, key in enumerate(keys):
        entry = timetable.get(key, {})
        print(
            f"  {index:2d} {key:12s} 시각 {len(entry.get('시간표', [])):3d}개"
            f" | 선형 {'O' if key in static.get('routes', {}) else '-'}"
            f" | 정류장 {'O' if key in static.get('stops', {}) else '-'}"
        )
    if args.dry_run:
        print("--dry-run: 아무것도 쓰지 않았습니다.")
        return

    # DB 연결은 실제로 쓸 때만 만든다.
    from database import SessionLocal
    from models import CityBusRelease, CityBusRoute
    from services import city_bus_data

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for index, key in enumerate(keys):
            entry = timetable.get(key, {})
            route = db.get(CityBusRoute, key)
            if route is not None and not args.overwrite:
                print(f"  {key}: 이미 있어 건너뜀")
                continue
            if route is None:
                route = CityBusRoute(route_key=key)
                db.add(route)
            route.sort_order = index
            route.origin = entry.get("출발지", "")
            route.terminus = entry.get("종점", "")
            route.times = city_bus_data.normalize_times(entry.get("시간표", []))
            route.route_geojson = static.get("routes", {}).get(key)
            route.stops_json = static.get("stops", {}).get(key)
            route.geojson_feature_count = city_bus_data.count_geojson_features(route.route_geojson)
            route.stop_count = city_bus_data.count_stops(route.stops_json)
        db.commit()
        print("노선 초안 저장 완료")

        def release_exists(kind: str, version: str) -> bool:
            return db.query(CityBusRelease).filter_by(kind=kind, version=version).first() is not None

        if release_exists(city_bus_data.KIND_TIMETABLE, timetable["version"]):
            print(f"시간표 게시본 {timetable['version']}이 이미 있어 건너뜀")
        else:
            db.add(CityBusRelease(
                kind=city_bus_data.KIND_TIMETABLE,
                version=timetable["version"],
                payload=timetable,
                published_at=now,
            ))
            db.commit()
            print(f"시간표 게시본 {timetable['version']} 등록")

        if release_exists(city_bus_data.KIND_STATIC, static["version"]):
            print(f"노선도 게시본 {static['version']}이 이미 있어 건너뜀")
        else:
            effective_text = manifest.get("effectiveFrom")
            effective_from = datetime.fromisoformat(effective_text) if effective_text else None
            # 깃허브 파일 그대로 올린다. 앱이 가진 파일과 내용이 같다.
            body = city_bus_data.encode_static_payload(static)
            release = city_bus_data.create_static_release(
                db,
                version=static["version"],
                body=body,
                effective_from=effective_from,
                published_at=now,
                admin_id=None,
            )
            print(f"노선도 게시본 {release.version} 등록: {release.download_url}")


if __name__ == "__main__":
    main()
