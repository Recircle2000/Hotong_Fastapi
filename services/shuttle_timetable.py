from collections import defaultdict
from datetime import time
from typing import Any

from sqlalchemy.orm import Session, selectinload

from models.schedule_types import ScheduleType
from models.shuttle import Schedule, ScheduleStop


def format_timetable_time(value: time | None) -> str:
    """Format a database time value for the timetable UI."""
    if value is None:
        return "—"
    return value.strftime("%H:%M")


def build_admin_shuttle_timetable(db: Session) -> list[dict[str, Any]]:
    """Build the schedule-type -> route -> stop matrix used by the admin page."""
    schedule_types = db.query(ScheduleType).order_by(ScheduleType.id).all()
    schedules = (
        db.query(Schedule)
        .options(
            selectinload(Schedule.route),
            selectinload(Schedule.stops).selectinload(ScheduleStop.station),
        )
        .all()
    )

    schedules_by_type: dict[str, dict[int, list[Schedule]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for schedule in schedules:
        if schedule.route is None:
            continue
        schedules_by_type[schedule.schedule_type][schedule.route_id].append(schedule)

    type_metadata = {
        schedule_type.schedule_type: schedule_type for schedule_type in schedule_types
    }
    ordered_type_codes = [
        schedule_type.schedule_type
        for schedule_type in schedule_types
        if schedule_type.schedule_type in schedules_by_type
    ]
    ordered_type_codes.extend(
        sorted(set(schedules_by_type) - set(ordered_type_codes))
    )

    sections: list[dict[str, Any]] = []
    for section_index, schedule_type_code in enumerate(ordered_type_codes, start=1):
        route_groups = schedules_by_type[schedule_type_code]
        route_tables: list[dict[str, Any]] = []

        for route_id in sorted(route_groups):
            route_schedules = sorted(
                route_groups[route_id],
                key=lambda item: (item.start_time, item.end_time, item.id),
            )
            route = route_schedules[0].route

            station_positions: dict[int, tuple[int, str]] = {}
            for schedule in route_schedules:
                for stop in schedule.stops:
                    if stop.station is None:
                        continue
                    existing = station_positions.get(stop.station_id)
                    candidate = (stop.stop_order, stop.station.name)
                    if existing is None or candidate[0] < existing[0]:
                        station_positions[stop.station_id] = candidate

            station_columns = [
                {
                    "station_id": station_id,
                    "station_name": station_name,
                    "stop_order": stop_order,
                }
                for station_id, (stop_order, station_name) in sorted(
                    station_positions.items(),
                    key=lambda item: (item[1][0], item[0]),
                )
            ]

            rows: list[dict[str, Any]] = []
            for row_number, schedule in enumerate(route_schedules, start=1):
                arrival_times = {
                    stop.station_id: format_timetable_time(stop.arrival_time)
                    for stop in schedule.stops
                    if stop.station is not None
                }
                rows.append(
                    {
                        "number": row_number,
                        "schedule_id": schedule.id,
                        "times": [
                            arrival_times.get(column["station_id"], "—")
                            for column in station_columns
                        ],
                    }
                )

            route_tables.append(
                {
                    "route_id": route.id,
                    "route_name": route.route_name,
                    "direction": route.direction,
                    "stations": station_columns,
                    "rows": rows,
                    "schedule_count": len(rows),
                }
            )

        metadata = type_metadata.get(schedule_type_code)
        sections.append(
            {
                "anchor_id": f"schedule-type-{section_index}",
                "schedule_type": schedule_type_code,
                "schedule_type_name": (
                    metadata.schedule_type_name if metadata else schedule_type_code
                ),
                "is_active": metadata.is_activate if metadata else True,
                "routes": route_tables,
                "route_count": len(route_tables),
                "schedule_count": sum(
                    route_table["schedule_count"] for route_table in route_tables
                ),
            }
        )

    return sections
