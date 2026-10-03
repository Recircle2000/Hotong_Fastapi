import asyncio
import os
import unittest
from unittest.mock import patch

os.environ["REDIS_ENABLED"] = "false"

from routers import bus  # noqa: E402


class _Response:
    def __init__(self, items):
        self._items = items

    def raise_for_status(self):
        return None

    def json(self):
        return {"response": {"body": {"items": self._items}}}


class _Client:
    """외부 버스 API 대신 미리 정한 응답을 차례로 돌려준다."""

    is_closed = False

    def __init__(self, responses):
        self._responses = list(responses)

    async def get(self, url):
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return _Response(result)


BUS = {"vehicleno": "충남70자1234", "nodeord": 3}


class BusHoldTest(unittest.TestCase):
    def setUp(self):
        bus.latest_bus_data.clear()
        bus.last_good_bus_data.clear()
        self.clock = 1000.0
        # 다른 테스트가 먼저 불러와 Redis가 켜진 상태여도 메모리 경로로 시험한다.
        for patcher in (
            patch.object(bus, "REDIS_ENABLED", False),
            patch.object(bus.time_module, "monotonic", lambda: self.clock),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _fetch(self, *responses, should_check=True):
        bus.bus_http_client = _Client(responses)
        for _ in responses or [None]:
            asyncio.run(bus.fetch_bus_data("24_DOWN", "ID", route_should_check=should_check))

    def test_keeps_last_position_through_empty_and_failed_responses(self):
        self._fetch({"item": [BUS]})
        self.assertEqual(bus.get_latest_bus_data("24_DOWN"), [BUS])

        # 외부 API가 잠깐 비거나 실패해도 마지막 위치를 유지한다.
        self._fetch("", RuntimeError("timeout"))
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


if __name__ == "__main__":
    unittest.main()
