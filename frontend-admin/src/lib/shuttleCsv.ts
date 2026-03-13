import type { ShuttleSchedulePayload } from "./shuttleTypes";

function toApiTime(value: string) {
  if (!value) {
    return "";
  }

  if (/^\d{2}:\d{2}:\d{2}$/.test(value)) {
    return value;
  }

  if (/^\d{1,2}:\d{2}$/.test(value)) {
    const [hours, minutes] = value.split(":");
    return `${hours.padStart(2, "0")}:${minutes}:00`;
  }

  return value;
}

export function parseCsvRows(text: string) {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];

    if (character === '"') {
      if (inQuotes && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (character === "," && !inQuotes) {
      row.push(cell);
      cell = "";
      continue;
    }

    if ((character === "\n" || character === "\r") && !inQuotes) {
      if (character === "\r" && text[index + 1] === "\n") {
        index += 1;
      }
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      continue;
    }

    cell += character;
  }

  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }

  return rows;
}

export function schedulesFromCsvRows(rows: string[][]) {
  let routeId: number | null = null;
  let scheduleType: string | null = null;

  for (const row of rows) {
    if (row[0]?.trim() === "routeID" && row[1]) {
      routeId = Number(row[1]);
    }
    if (row[3]?.trim() === "schedule_type" && row[4]) {
      scheduleType = row[4].trim();
    }
    if (routeId && scheduleType) {
      break;
    }
  }

  if (!routeId || !scheduleType) {
    throw new Error("CSV에서 노선 ID 또는 일정 유형을 찾지 못했습니다.");
  }

  const stationIds: number[] = [];
  const arrivalRows: Array<Array<string | null>> = [];

  for (const row of rows) {
    if (row[0]?.trim() === "stationID") {
      for (let index = 1; index < row.length; index += 1) {
        if (row[index]?.trim()) {
          stationIds.push(Number(row[index]));
        }
      }
      continue;
    }

    if (stationIds.length > 0 && row[0]?.trim() === "") {
      const timeRow: Array<string | null> = [];
      let hasValidTime = false;

      for (let index = 1; index < Math.min(row.length, stationIds.length + 1); index += 1) {
        const value = row[index]?.trim() ?? "";
        if (value && /^\d{1,2}:\d{2}$/.test(value)) {
          hasValidTime = true;
          timeRow.push(toApiTime(value));
        } else {
          timeRow.push(null);
        }
      }

      if (hasValidTime) {
        arrivalRows.push(timeRow);
      }
    }
  }

  if (stationIds.length === 0 || arrivalRows.length === 0) {
    throw new Error("CSV에서 정류장 또는 도착 시간을 찾지 못했습니다.");
  }

  const schedules: ShuttleSchedulePayload[] = [];

  for (const timeRow of arrivalRows) {
    const filledTimes = timeRow.filter((value): value is string => Boolean(value));
    if (filledTimes.length === 0) {
      continue;
    }

    const stops = stationIds
      .map((stationId, stationIndex) => {
        const arrivalTime = timeRow[stationIndex];
        if (!arrivalTime) {
          return null;
        }

        return {
          station_id: stationId,
          arrival_time: arrivalTime,
          stop_order: stationIndex + 1,
        };
      })
      .filter((value): value is ShuttleSchedulePayload["stops"][number] => Boolean(value));

    if (stops.length === 0) {
      continue;
    }

    schedules.push({
      route_id: routeId,
      schedule_type: scheduleType,
      start_time: filledTimes[0],
      end_time: filledTimes[filledTimes.length - 1],
      stops,
    });
  }

  if (schedules.length === 0) {
    throw new Error("CSV에서 등록 가능한 시간표를 찾지 못했습니다.");
  }

  return {
    routeId,
    scheduleType,
    schedules,
  };
}
