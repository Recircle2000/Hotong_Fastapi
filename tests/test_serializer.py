import unittest
from datetime import date, datetime, time

from utils.serializer import model_to_dict, serialize_models, serialize_value


class DummyObject:
    def __init__(self):
        self.name = "dummy"
        self.count = 3
        self._private = "hidden"


class SerializerTests(unittest.TestCase):
    def test_serialize_datetime_family(self):
        self.assertEqual(serialize_value(datetime(2026, 3, 5, 9, 30, 0)), "2026-03-05T09:30:00")
        self.assertEqual(serialize_value(date(2026, 3, 5)), "2026-03-05")
        self.assertEqual(serialize_value(time(9, 30, 0)), "09:30:00")

    def test_model_to_dict_plain_object_ignores_private(self):
        payload = model_to_dict(DummyObject())
        self.assertEqual(payload, {"name": "dummy", "count": 3})

    def test_serialize_value_nested_structure(self):
        nested = {
            "created_at": datetime(2026, 3, 5, 9, 30, 0),
            "items": [date(2026, 3, 5), {"at": time(10, 0, 0)}],
        }
        self.assertEqual(
            serialize_value(nested),
            {
                "created_at": "2026-03-05T09:30:00",
                "items": ["2026-03-05", {"at": "10:00:00"}],
            },
        )

    def test_serialize_models_returns_list_of_dicts(self):
        serialized = serialize_models([DummyObject(), DummyObject()])
        self.assertEqual(
            serialized,
            [{"name": "dummy", "count": 3}, {"name": "dummy", "count": 3}],
        )


if __name__ == "__main__":
    unittest.main()
