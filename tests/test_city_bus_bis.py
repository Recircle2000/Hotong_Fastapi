import os
import unittest
from unittest import mock

import httpx

os.environ["SUPABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("SUPABASE_PASSWORD", None)

from services import city_bus_bis  # noqa: E402
from services.city_bus_bis import BisSource, CityBusBisError  # noqa: E402


ROUTES = {
    "810_UP": "ASB288000091",
    "81_UP": "CAB285000294",
    "81_DOWN": "CAB285000293",
    "순환5_DOWN": "ASB288000141",
}


def asan_item(time, *, updn="1", turn="0", week="1"):
    return {"departure_time": time, "updn_line": updn, "turn_useflag": turn, "week_operation_flag": week}


CHEONAN_HTML = """
<div class="timeTable"><dl>
  <dt>평일 출발시간</dt>
  <dd>06:30</dd>
  <dd>06:45</dd>
  <dd>22:30</dd>
</dl></div>
<div class="timeTable"><dl>
  <dt>주말 출발시간</dt>
  <dd>07:00</dd>
</dl></div>
"""


class ResolveSourceTests(unittest.TestCase):
    def test_asan_uses_numeric_route_id(self):
        self.assertEqual(city_bus_bis.resolve_bis_source("810_UP", ROUTES), BisSource("asan", "288000091"))
        self.assertEqual(city_bus_bis.resolve_bis_source("순환5_DOWN", ROUTES), BisSource("asan", "288000141"))

    def test_cheonan_uses_route_name_and_direction(self):
        self.assertEqual(city_bus_bis.resolve_bis_source("81_UP", ROUTES), BisSource("cheonan", "81", "2"))
        self.assertEqual(city_bus_bis.resolve_bis_source("81_DOWN", ROUTES), BisSource("cheonan", "81", "1"))

    def test_unknown_route_has_no_source(self):
        self.assertIsNone(city_bus_bis.resolve_bis_source("900_UP", ROUTES))

    def test_page_urls(self):
        self.assertEqual(
            BisSource("asan", "288000091").page_url,
            "https://bus.asan.go.kr/web/bus_timetable_pop?auto_route_id=288000091",
        )
        cheonan = BisSource("cheonan", "81", "2").page_url
        self.assertIn("routeName=81&routeDirection=2&relayAreacode=285", cheonan)
        self.assertIn("avgTime=", cheonan)


class ParseTests(unittest.TestCase):
    def test_asan_weekday_only_and_three_digit_times(self):
        data = {"busTimeList": [asan_item("0840"), asan_item("715"), asan_item("1200", week="0")]}
        self.assertEqual(city_bus_bis.parse_asan_times(data), ["08:40", "07:15"])

    def test_asan_round_trip_route_keeps_up_line(self):
        data = {"busTimeList": [asan_item("0700", turn="1"), asan_item("0730", updn="2", turn="1")]}
        self.assertEqual(city_bus_bis.parse_asan_times(data), ["07:00"])

    def test_asan_bad_shape(self):
        with self.assertRaises(CityBusBisError):
            city_bus_bis.parse_asan_times({"resultList": []})

    def test_cheonan_reads_weekday_block_only(self):
        self.assertEqual(city_bus_bis.parse_cheonan_times(CHEONAN_HTML), ["06:30", "06:45", "22:30"])

    def test_cheonan_error_page(self):
        with self.assertRaises(CityBusBisError):
            city_bus_bis.parse_cheonan_times("<h1>요청하신 페이지를 찾을 수 없습니다.</h1>")


class FetchTests(unittest.TestCase):
    def test_asan_fetch_sorts_and_merges_duplicates(self):
        response = httpx.Response(
            200,
            json={"busTimeList": [asan_item("0900"), asan_item("0700"), asan_item("0700")]},
            request=httpx.Request("POST", city_bus_bis.ASAN_TIME_LIST_URL),
        )
        with mock.patch.object(httpx, "post", return_value=response) as post:
            result = city_bus_bis.fetch_bis_timetable(BisSource("asan", "288000091"))
        self.assertEqual(result.times, ["07:00", "09:00"])
        self.assertEqual(post.call_args.kwargs["data"], {"busRouteId": "288000091", "weekcd": "1"})

    def test_cheonan_fetch(self):
        response = httpx.Response(200, text=CHEONAN_HTML, request=httpx.Request("GET", city_bus_bis.CHEONAN_TIMETABLE_URL))
        with mock.patch.object(httpx, "get", return_value=response) as get:
            result = city_bus_bis.fetch_bis_timetable(BisSource("cheonan", "81", "2"))
        self.assertEqual(result.times, ["06:30", "06:45", "22:30"])
        self.assertEqual(get.call_args.kwargs["params"]["routeDirection"], "2")

    def test_empty_result_is_error(self):
        response = httpx.Response(200, json={"busTimeList": []}, request=httpx.Request("POST", city_bus_bis.ASAN_TIME_LIST_URL))
        with mock.patch.object(httpx, "post", return_value=response):
            with self.assertRaises(CityBusBisError):
                city_bus_bis.fetch_bis_timetable(BisSource("asan", "1"))

    def test_network_and_json_errors(self):
        with mock.patch.object(httpx, "post", side_effect=httpx.ConnectTimeout("timeout")):
            with self.assertRaises(CityBusBisError):
                city_bus_bis.fetch_bis_timetable(BisSource("asan", "1"))
        bad_json = httpx.Response(200, text="<html>", request=httpx.Request("POST", city_bus_bis.ASAN_TIME_LIST_URL))
        with mock.patch.object(httpx, "post", return_value=bad_json):
            with self.assertRaises(CityBusBisError):
                city_bus_bis.fetch_bis_timetable(BisSource("asan", "1"))


def stop(node_id, order, name, lat=36.7, lng=127.0, route_id="ASB288000091"):
    return {"nodeid": node_id, "nodeord": order, "nodenm": name, "gpslati": lat, "gpslong": lng, "routeid": route_id}


def stops_response(items, *, total=None, code="00"):
    return {
        "response": {
            "header": {"resultCode": code, "resultMsg": "NORMAL SERVICE." if code == "00" else "ERROR"},
            "body": {"items": {"item": items}, "numOfRows": 200, "pageNo": 1, "totalCount": len(items) if total is None else total},
        }
    }


class StopsSourceTests(unittest.TestCase):
    def test_stored_route_id_wins(self):
        stored = stops_response([stop("A", 1, "a", route_id="ASB285000245")])
        self.assertEqual(city_bus_bis.resolve_stops_route_id(stored, "900_UP", ROUTES), ("ASB285000245", "34040"))

    def test_falls_back_to_routes_and_cheonan_city_code(self):
        self.assertEqual(city_bus_bis.resolve_stops_route_id(None, "81_UP", ROUTES), ("CAB285000294", "34010"))
        self.assertEqual(city_bus_bis.resolve_stops_route_id(None, "810_UP", ROUTES), ("ASB288000091", "34040"))
        self.assertIsNone(city_bus_bis.resolve_stops_route_id(None, "900_UP", ROUTES))


class DiffStopsTests(unittest.TestCase):
    def test_same_stops(self):
        items = [stop("A", 1, "a"), stop("B", 2, "b")]
        diff = city_bus_bis.diff_stops(stops_response(items), stops_response(items))
        self.assertEqual((diff.added, diff.removed, diff.renamed, diff.moved, diff.reordered), ([], [], [], [], False))

    def test_added_removed_renamed_moved_reordered(self):
        current = stops_response([stop("A", 1, "a"), stop("B", 2, "b"), stop("C", 3, "c"), stop("D", 4, "d")])
        fetched = stops_response([
            stop("B", 1, "b2"),  # 이름 변경
            stop("A", 2, "a", lat=36.7 + 0.001),  # 약 111m 이동
            stop("C", 3, "c", lat=36.7 + 0.0001),  # 약 11m는 이동으로 보지 않음
            stop("E", 4, "e"),
        ])
        diff = city_bus_bis.diff_stops(current, fetched)
        self.assertEqual([item["nodeid"] for item in diff.added], ["E"])
        self.assertEqual([item["nodeid"] for item in diff.removed], ["D"])
        self.assertEqual(diff.renamed, [{"nodeid": "B", "nodeord": 1, "nodenm": "b2", "before": "b"}])
        self.assertEqual([(item["nodeid"], item["meters"]) for item in diff.moved], [("A", 111)])
        self.assertTrue(diff.reordered)
        self.assertEqual((diff.current_count, diff.fetched_count), (4, 4))

    def test_single_item_and_missing_current(self):
        fetched = stops_response(stop("A", 1, "a"))
        diff = city_bus_bis.diff_stops(None, fetched)
        self.assertEqual(diff.current_count, 0)
        self.assertEqual([item["nodeid"] for item in diff.added], ["A"])


class FetchStopsTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"API_KEY": "abc%2Bdef%3D%3D"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def respond(self, **kwargs):
        return httpx.Response(request=httpx.Request("GET", city_bus_bis.TAGO_ROUTE_STOPS_URL), **kwargs)

    def test_key_goes_into_url_unencoded_again(self):
        data = stops_response([stop("A", 1, "a")])
        with mock.patch.object(httpx, "get", return_value=self.respond(status_code=200, json=data)) as get:
            self.assertEqual(city_bus_bis.fetch_route_stops("ASB288000091", "34040"), data)
        url = get.call_args.args[0]
        self.assertIn("serviceKey=abc%2Bdef%3D%3D&", url)
        self.assertIn("routeId=ASB288000091", url)
        self.assertIn("cityCode=34040", url)

    def test_errors(self):
        cases = [
            self.respond(status_code=403, text="SERVICE_KEY_IS_NOT_REGISTERED_ERROR"),
            self.respond(status_code=200, json=stops_response([stop("A", 1, "a")], code="30")),
            self.respond(status_code=200, json=stops_response([stop("A", 1, "a")], total=300)),
            self.respond(status_code=200, json={"response": {"header": {"resultCode": "00"}, "body": {"items": ""}}}),
            self.respond(status_code=200, text="<xml/>"),
        ]
        for response in cases:
            with mock.patch.object(httpx, "get", return_value=response):
                with self.assertRaises(CityBusBisError):
                    city_bus_bis.fetch_route_stops("ASB1", "34040")

    def test_missing_key(self):
        with mock.patch.dict(os.environ, {"API_KEY": ""}):
            with self.assertRaises(CityBusBisError):
                city_bus_bis.fetch_route_stops("ASB1", "34040")


if __name__ == "__main__":
    unittest.main()
