import asyncio
import json
import os
import unittest
from unittest.mock import patch

os.environ["REDIS_ENABLED"] = "false"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routers import bus  # noqa: E402


class _Response:
    def __init__(self, items):
        self._items = items

    def raise_for_status(self):
        return None

    def json(self):
        return {"response": {"body": {"items": self._items}}}


class _Client:
    """외부 버스 API 대신 미리 정한 응답을 차례로 돌려주고, 부른 주소를 남긴다."""

    is_closed = False

    def __init__(self, responses=()):
        self._responses = list(responses)
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return _Response(result)


BUS = {"vehicleno": "충남70자1234", "nodeord": 3}
BUS_RAW = {**BUS, "nodeid": "CAB1", "routetp": "일반"}


class _BusStateTest(unittest.TestCase):
    def setUp(self):
        bus.latest_bus_data.clear()
        bus.last_good_bus_data.clear()
        bus.route_checked_at.clear()
        bus.bus_loop_wake.clear()
        self.clock = 1000.0
        # 다른 테스트가 먼저 불러와 Redis가 켜진 상태여도 메모리 경로로 시험한다.
        for patcher in (
            patch.object(bus, "REDIS_ENABLED", False),
            patch.object(bus.time_module, "monotonic", lambda: self.clock),
            patch.object(bus, "last_http_demand_at", None),
            patch.object(bus, "bus_loop_interval", bus.BUS_IDLE_INTERVAL),
            patch.object(bus, "bus_http_client", None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(bus.bus_loop_wake.clear)

    def _use_client(self, *responses):
        client = _Client(responses)
        bus.bus_http_client = client
        return client


class BusHoldTest(_BusStateTest):
    def _fetch(self, *responses, should_check=True):
        self._use_client(*responses)
        for _ in responses or [None]:
            asyncio.run(bus.fetch_bus_data("24_DOWN", "ID", route_should_check=should_check))

    def test_keeps_last_position_through_empty_and_failed_responses(self):
        self._fetch({"item": [BUS]})
        self.assertEqual(bus.get_latest_bus_data("24_DOWN"), [BUS])

        # 외부 API가 잠깐 비거나 실패해도 마지막 위치를 유지한다.
        self._fetch("", RuntimeError("timeout"))
        self.assertEqual(bus.get_latest_bus_data("24_DOWN"), [BUS])

    def test_hold_covers_two_idle_rounds_and_a_timeout(self):
        self.assertGreater(bus.BUS_HOLD_SECONDS, bus.BUS_IDLE_INTERVAL * 2 + bus.BUS_API_TIMEOUT.read)

        self._fetch({"item": [BUS]})
        self.clock += bus.BUS_IDLE_INTERVAL * 2
        self._fetch(RuntimeError("timeout"))
        self.assertEqual(bus.get_latest_bus_data("24_DOWN"), [BUS])

    def test_drops_bus_after_hold_time_without_fresh_data(self):
        self._fetch({"item": [BUS]})
        self._fetch("")
        self.clock += bus.BUS_HOLD_SECONDS + 1
        self.assertIsNone(bus.get_latest_bus_data("24_DOWN"))

    def test_out_of_service_route_clears_held_position_immediately(self):
        self._fetch({"item": [BUS]})
        self._fetch(should_check=False)
        self.assertIsNone(bus.get_latest_bus_data("24_DOWN"))

    def test_records_check_time_even_when_the_api_fails(self):
        self._fetch(RuntimeError("timeout"))
        self.assertEqual(bus.route_checked_at["24_DOWN"], self.clock)

    def test_http_client_is_created_with_explicit_timeout(self):
        created = {}

        def factory(**kwargs):
            created.update(kwargs)
            return _Client([{"item": BUS}])

        with patch.object(bus.httpx, "AsyncClient", factory):
            items = asyncio.run(bus.fetch_bus_data("24_DOWN", "ID", route_should_check=True))

        self.assertIs(created["timeout"], bus.BUS_API_TIMEOUT)
        self.assertEqual(bus.BUS_API_TIMEOUT.read, 8.0)
        self.assertEqual(bus.BUS_API_TIMEOUT.connect, 3.0)
        # 버스가 한 대면 객체로 오는데 목록으로 맞춘다.
        self.assertEqual(items, [BUS])


class LoopIntervalTest(_BusStateTest):
    def test_idle_without_viewers(self):
        self.assertEqual(bus.select_loop_interval(0, None, self.clock), bus.BUS_IDLE_INTERVAL)

    def test_active_while_websocket_connected(self):
        self.assertEqual(bus.select_loop_interval(1, None, self.clock), bus.BUS_ACTIVE_INTERVAL)

    def test_active_after_recent_http_request_then_back_to_idle(self):
        demand_at = self.clock
        self.assertEqual(bus.select_loop_interval(0, demand_at, self.clock + 10), bus.BUS_ACTIVE_INTERVAL)
        self.assertEqual(
            bus.select_loop_interval(0, demand_at, self.clock + bus.BUS_HTTP_DEMAND_SECONDS),
            bus.BUS_ACTIVE_INTERVAL,
        )
        self.assertEqual(
            bus.select_loop_interval(0, demand_at, self.clock + bus.BUS_HTTP_DEMAND_SECONDS + 1),
            bus.BUS_IDLE_INTERVAL,
        )

    def test_demand_wakes_loop_only_while_idle(self):
        bus.record_http_demand()
        self.assertEqual(bus.last_http_demand_at, self.clock)
        self.assertTrue(bus.bus_loop_wake.is_set())

        # 이미 짧은 주기로 돌고 있으면 요청마다 깨우지 않는다 (구버전 앱 폴링이 많아도 호출이 늘지 않음).
        bus.bus_loop_wake.clear()
        bus.bus_loop_interval = bus.BUS_ACTIVE_INTERVAL
        bus.record_http_demand()
        self.assertFalse(bus.bus_loop_wake.is_set())


class BusesEndpointTest(_BusStateTest):
    def setUp(self):
        super().setUp()
        patcher = patch.object(bus, "should_check_route", lambda route_name: True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_cache_without_calling_external_api(self):
        client = self._use_client()
        bus.latest_bus_data["24_DOWN"] = [BUS_RAW]
        bus.route_checked_at["24_DOWN"] = self.clock
        # 81번은 방금 조회했는데 차가 없었다.
        bus.route_checked_at["81_DOWN"] = self.clock - 3

        result = asyncio.run(bus.get_all_buses())

        self.assertEqual(client.calls, [])
        self.assertEqual(result, {"buses": {"24_DOWN": [BUS], "81_DOWN": None}})
        self.assertEqual(bus.last_http_demand_at, self.clock)

    def test_fetches_only_routes_never_checked(self):
        client = self._use_client({"item": [BUS_RAW]})
        bus.latest_bus_data["24_DOWN"] = [BUS_RAW]
        bus.route_checked_at["24_DOWN"] = self.clock

        result = asyncio.run(bus.get_all_buses())

        self.assertEqual(len(client.calls), 1)
        self.assertIn(bus.ROUTES["81_DOWN"], client.calls[0])
        self.assertEqual(result["buses"]["81_DOWN"], [BUS])

    def test_single_route_endpoint_reads_cache(self):
        client = self._use_client()
        bus.latest_bus_data["81_DOWN"] = [BUS_RAW]
        bus.route_checked_at["81_DOWN"] = self.clock

        result = asyncio.run(bus.get_bus_by_route("81_DOWN"))

        self.assertEqual(client.calls, [])
        self.assertEqual(result, {"81_DOWN": [BUS_RAW]})


class BusWebSocketTest(_BusStateTest):
    def setUp(self):
        super().setUp()

        async def no_loop():
            return None

        patcher = patch.object(bus, "update_bus_cache", no_loop)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(bus.router)
        self.client = TestClient(app)

    def test_cheonan_down_sends_cache_immediately_without_external_api(self):
        client = self._use_client()
        bus.latest_bus_data["24_DOWN"] = [BUS_RAW]
        # 다른 그룹 노선은 보내지 않는다.
        bus.latest_bus_data["24_UP"] = [BUS_RAW]

        with self.client.websocket_connect("/ws/bus/cheonan/down") as websocket:
            message = json.loads(websocket.receive_text())
            self.assertEqual(bus.get_total_active_connections(), 1)
            websocket.send_text("ping")
            self.assertEqual(websocket.receive_text(), "pong")

        self.assertEqual(message, {"24_DOWN": [BUS]})
        self.assertEqual(client.calls, [])
        self.assertTrue(bus.bus_loop_wake.is_set())

    def test_all_routes_socket_sends_cache_immediately(self):
        client = self._use_client()
        bus.latest_bus_data["순환5_DOWN"] = [BUS_RAW]

        with self.client.websocket_connect("/ws/bus") as websocket:
            message = json.loads(websocket.receive_text())

        self.assertEqual(message, {"순환5_DOWN": [BUS]})
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
