const TIME_PATTERN = /^\d{1,2}:\d{2}$/;

export type PastedTimetable = {
  columnCount: number;
  grid: string[][];
  // 빈 칸 위치를 간격만으로 확정하지 못한 행 번호
  ambiguousRows: number[];
};

export function isTimeCell(value: string) {
  return TIME_PATTERN.test(value.trim());
}

function toMinutes(value: string) {
  const [hours, minutes] = value.trim().split(":");
  return Number(hours) * 60 + Number(minutes);
}

function parseLine(line: string): string[] | null {
  if (line.includes("\t")) {
    // 엑셀/웹 표에서 복사하면 탭으로 구분되고 빈 칸이 그대로 남는다.
    const cells = line.split("\t").map((cell) => cell.trim());
    if (/^\d+$/.test(cells[0] ?? "")) {
      cells.shift();
    }
    if (!cells.some(isTimeCell)) {
      return null;
    }
    return cells.map((cell) => (isTimeCell(cell) ? cell : ""));
  }

  // PDF에서 복사하면 공백으로만 구분되고 빈 칸은 사라진다.
  const times = line.match(/\d{1,2}:\d{2}/g);
  return times && times.length > 0 ? times : null;
}

/** 모든 칸이 채워진 행들에서 가장 흔한 "첫 열 기준 경과 분" 패턴을 구한다. */
export function getReferenceOffsets(grid: string[][], columnCount: number): number[] | null {
  const counts = new Map<string, { offsets: number[]; count: number }>();

  for (const row of grid) {
    if (row.length !== columnCount || !row.every(isTimeCell)) {
      continue;
    }
    const first = toMinutes(row[0]);
    const offsets = row.map((cell) => toMinutes(cell) - first);
    const key = offsets.join(",");
    const entry = counts.get(key) ?? { offsets, count: 0 };
    entry.count += 1;
    counts.set(key, entry);
  }

  let best: { offsets: number[]; count: number } | null = null;
  for (const entry of counts.values()) {
    if (!best || entry.count > best.count) {
      best = entry;
    }
  }
  return best ? best.offsets : null;
}

/** 시간 k개가 기준 간격과 정확히 맞는 열 조합을 최대 2개까지 찾는다. */
function findPlacements(minutes: number[], reference: number[]): number[][] {
  const placements: number[][] = [];

  function search(startColumn: number, picked: number[]) {
    if (placements.length >= 2) {
      return;
    }
    if (picked.length === minutes.length) {
      placements.push([...picked]);
      return;
    }
    const remaining = minutes.length - picked.length;
    for (let column = startColumn; column <= reference.length - remaining; column += 1) {
      if (picked.length > 0) {
        const expected = reference[column] - reference[picked[0]];
        const actual = minutes[picked.length] - minutes[0];
        if (expected !== actual) {
          continue;
        }
      }
      picked.push(column);
      search(column + 1, picked);
      picked.pop();
    }
  }

  search(0, []);
  return placements;
}

export function parsePastedTimetable(text: string): PastedTimetable {
  const rawRows = text
    .split(/\r?\n/)
    .map(parseLine)
    .filter((row): row is string[] => row !== null);

  const columnCount = rawRows.reduce((max, row) => Math.max(max, row.length), 0);
  const reference = getReferenceOffsets(rawRows, columnCount);
  const ambiguousRows: number[] = [];

  const grid = rawRows.map((row, rowIndex) => {
    if (row.length === columnCount) {
      return row;
    }

    const times = row.filter(isTimeCell);
    const aligned = Array<string>(columnCount).fill("");
    const placements = reference ? findPlacements(times.map(toMinutes), reference) : [];

    if (placements.length !== 1) {
      ambiguousRows.push(rowIndex);
    }

    const columns = placements[0] ?? times.map((_, index) => index);
    times.forEach((time, index) => {
      aligned[columns[index]] = time;
    });
    return aligned;
  });

  return { columnCount, grid, ambiguousRows };
}

/** 등록을 막지는 않지만 확인이 필요한 행별 경고를 만든다. */
export function getRowWarnings(grid: string[][], columnCount: number): Map<number, string> {
  const warnings = new Map<number, string>();
  const reference = getReferenceOffsets(grid, columnCount);

  grid.forEach((row, rowIndex) => {
    const filled = row
      .map((cell, column) => ({ cell: cell.trim(), column }))
      .filter((item) => item.cell !== "");

    if (filled.length === 0) {
      warnings.set(rowIndex, "시간이 없어 등록에서 제외됩니다.");
      return;
    }
    if (filled.some((item) => !isTimeCell(item.cell))) {
      return;
    }

    const minutes = filled.map((item) => toMinutes(item.cell));
    if (minutes.some((value, index) => index > 0 && value < minutes[index - 1])) {
      warnings.set(rowIndex, "시간이 앞 정류장보다 이릅니다.");
      return;
    }

    if (
      reference &&
      filled.some(
        (item, index) =>
          minutes[index] - minutes[0] !== reference[item.column] - reference[filled[0].column],
      )
    ) {
      warnings.set(rowIndex, "정류장 간 간격이 다른 회차와 다릅니다.");
    }
  });

  return warnings;
}

/** 기존 CSV 일괄 등록 형식과 같은 행 배열을 만든다. */
export function toCsvRows(
  routeId: number,
  scheduleType: string,
  stationIds: number[],
  grid: string[][],
): string[][] {
  const width = Math.max(stationIds.length + 1, 5);
  const pad = (row: string[]) => [...row, ...Array<string>(Math.max(0, width - row.length)).fill("")];

  return [
    pad(["routeID", String(routeId), "", "schedule_type", scheduleType]),
    pad([]),
    pad(["stationID", ...stationIds.map(String)]),
    ...grid
      .filter((row) => row.some((cell) => cell.trim() !== ""))
      .map((row) => pad(["", ...row.map((cell) => cell.trim())])),
  ];
}

export function csvRowsToText(rows: string[][]) {
  return rows.map((row) => row.join(",")).join("\n") + "\n";
}
