import { Fragment, useEffect, useMemo, useState } from "react";

import { AdminPanel } from "../components/AdminPanel";
import { createShuttleSchedule, getShuttleRouteStations } from "../lib/shuttleApi";
import { schedulesFromCsvRows } from "../lib/shuttleCsv";
import {
  csvRowsToText,
  getRowWarnings,
  isTimeCell,
  parsePastedTimetable,
  toCsvRows,
} from "../lib/shuttlePaste";
import type {
  ShuttleRoute,
  ShuttleScheduleType,
  ShuttleStation,
  ShuttleTimetableStation,
} from "../lib/shuttleTypes";

const SELECT_CLASS =
  "rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100";

// 노선의 기준 정류장 순서로 채운다. 열 수와 다르면 아래 편집기에서 추가/삭제해 맞춘다.
function defaultStationIds(routeStations: ShuttleTimetableStation[], columnCount: number) {
  if (routeStations.length > 0) {
    return routeStations.map((station) => String(station.station_id));
  }
  return Array<string>(columnCount).fill("");
}

export function ShuttlePasteImport({
  routes,
  scheduleTypes,
  stations,
  getScheduleTypeLabel,
  onError,
  onImported,
  onNotify,
}: {
  routes: ShuttleRoute[];
  scheduleTypes: ShuttleScheduleType[];
  stations: ShuttleStation[];
  getScheduleTypeLabel: (code: string) => string;
  onError: (error: unknown, fallbackMessage: string) => Promise<void>;
  onImported: (routeId: number, scheduleType: string) => Promise<void>;
  onNotify: (tone: "success" | "error", message: string) => void;
}) {
  const [routeId, setRouteId] = useState("");
  const [scheduleType, setScheduleType] = useState("");
  const [text, setText] = useState("");
  const [routeStations, setRouteStations] = useState<ShuttleTimetableStation[]>([]);
  const [stationIds, setStationIds] = useState<string[]>([]);
  const [grid, setGrid] = useState<string[][]>([]);
  const [ambiguousRows, setAmbiguousRows] = useState<number[]>([]);
  const [isRegistering, setIsRegistering] = useState(false);

  const columnCount = grid[0]?.length ?? 0;

  useEffect(() => {
    if (!routeId) {
      setRouteStations([]);
      return;
    }

    let cancelled = false;
    getShuttleRouteStations(Number(routeId))
      .then((nextStations) => {
        if (cancelled) return;
        setRouteStations(nextStations);
      })
      .catch((error) => {
        if (cancelled) return;
        setRouteStations([]);
        void onError(error, "노선 정류장을 불러오지 못했습니다.");
      });

    return () => {
      cancelled = true;
    };
  }, [routeId]);

  useEffect(() => {
    setStationIds(defaultStationIds(routeStations, columnCount));
  }, [routeStations]);

  function handleTextChange(value: string) {
    setText(value);
    const parsed = parsePastedTimetable(value);
    setGrid(parsed.grid);
    setAmbiguousRows(parsed.ambiguousRows);
    setStationIds(defaultStationIds(routeStations, parsed.columnCount));
  }

  function updateCell(rowIndex: number, column: number, value: string) {
    setGrid((current) =>
      current.map((row, index) =>
        index === rowIndex ? row.map((cell, cellIndex) => (cellIndex === column ? value : cell)) : row,
      ),
    );
    setAmbiguousRows((current) => current.filter((index) => index !== rowIndex));
  }

  function insertStation(position: number) {
    setStationIds((current) => [...current.slice(0, position), "", ...current.slice(position)]);
  }

  function removeStation(position: number) {
    setStationIds((current) => current.filter((_, index) => index !== position));
  }

  function changeStation(position: number, value: string) {
    setStationIds((current) => current.map((id, index) => (index === position ? value : id)));
  }

  function resetStations() {
    setStationIds(defaultStationIds(routeStations, columnCount));
  }

  function getStationName(stationId: string) {
    return stations.find((station) => String(station.id) === stationId)?.name ?? null;
  }

  function removeRow(rowIndex: number) {
    setGrid((current) => current.filter((_, index) => index !== rowIndex));
    setAmbiguousRows((current) =>
      current.filter((index) => index !== rowIndex).map((index) => (index > rowIndex ? index - 1 : index)),
    );
  }

  const rowWarnings = useMemo(() => getRowWarnings(grid, columnCount), [grid, columnCount]);

  const blockingError = useMemo(() => {
    if (grid.length === 0) return "시간표를 붙여넣으세요.";
    if (!routeId || !scheduleType) return "노선과 일정 유형을 선택하세요.";
    if (stationIds.length !== columnCount) {
      return `시간표는 ${columnCount}열인데 정류장이 ${stationIds.length}개입니다.`;
    }
    if (stationIds.some((id) => !id)) return "모든 열의 정류장을 선택하세요.";
    if (new Set(stationIds).size !== stationIds.length) return "같은 정류장이 두 열에 지정되어 있습니다.";
    if (grid.some((row) => row.some((cell) => cell.trim() !== "" && !isTimeCell(cell)))) {
      return "시간 형식(예: 8:30)이 아닌 칸이 있습니다.";
    }
    return null;
  }, [grid, columnCount, routeId, scheduleType, stationIds]);

  const warningCount = new Set([...rowWarnings.keys(), ...ambiguousRows]).size;
  const hasColumnMismatch = grid.length > 0 && stationIds.length !== columnCount;

  function buildCsvRows() {
    return toCsvRows(Number(routeId), scheduleType, stationIds.map(Number), grid);
  }

  function downloadCsv() {
    const route = routes.find((item) => item.id === Number(routeId));
    const blob = new Blob([csvRowsToText(buildCsvRows())], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${route?.route_name ?? `route-${routeId}`} (${scheduleType}).csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function register() {
    let created = 0;
    try {
      const parsed = schedulesFromCsvRows(buildCsvRows());
      const warningNote = warningCount > 0 ? `\n확인이 필요한 행이 ${warningCount}개 있습니다.` : "";
      if (!window.confirm(`시간표 ${parsed.schedules.length}개를 등록하시겠습니까?${warningNote}`)) {
        return;
      }

      setIsRegistering(true);
      for (const schedule of parsed.schedules) {
        await createShuttleSchedule(schedule);
        created += 1;
      }
      onNotify("success", `${created}개 시간표를 등록했습니다.`);
      setText("");
      setGrid([]);
      setAmbiguousRows([]);
      setStationIds([]);
      await onImported(parsed.routeId, parsed.scheduleType);
    } catch (error) {
      await onError(
        error,
        created > 0 ? `${created}개 등록 후 실패했습니다.` : "시간표 등록에 실패했습니다.",
      );
      if (created > 0) {
        onNotify("error", `${created}개는 이미 등록되었습니다. 조회 후 중복에 주의하세요.`);
      }
    } finally {
      setIsRegistering(false);
    }
  }

  return (
    <AdminPanel
      title="시간표 붙여넣기 등록"
      description="PDF나 표에서 복사한 시간표를 붙여넣으면 정류장을 맞춰 CSV로 만들거나 바로 등록합니다."
    >
      <div className="grid gap-3 md:grid-cols-2">
        <select className={SELECT_CLASS} value={routeId} onChange={(event) => setRouteId(event.target.value)}>
          <option value="">노선 선택</option>
          {routes.map((route) => (
            <option key={route.id} value={route.id}>
              {route.route_name} ({route.direction})
            </option>
          ))}
        </select>
        <select
          className={SELECT_CLASS}
          value={scheduleType}
          onChange={(event) => setScheduleType(event.target.value)}
        >
          <option value="">일정 유형 선택</option>
          {scheduleTypes.map((item) => (
            <option key={item.schedule_type} value={item.schedule_type}>
              {getScheduleTypeLabel(item.schedule_type)}
            </option>
          ))}
        </select>
      </div>

      <textarea
        className="mt-3 h-32 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 font-mono text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
        placeholder="복사한 시간표를 여기에 붙여넣으세요. 헤더와 운행횟수는 자동으로 무시됩니다."
        value={text}
        onChange={(event) => handleTextChange(event.target.value)}
      />

      {grid.length > 0 ? (
        <>
          <div
            className={`mt-3 rounded-lg border px-4 py-3 ${
              hasColumnMismatch ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-slate-50"
            }`}
          >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className={`text-sm ${hasColumnMismatch ? "text-amber-800" : "text-slate-600"}`}>
                {hasColumnMismatch
                  ? `시간표 ${columnCount}열 / 정류장 ${stationIds.length}개 — ＋로 사이에 정류장을 추가하거나 ×로 삭제해 개수를 맞추세요.`
                  : `정류장 순서 (시간표 ${columnCount}열과 일치)`}
              </div>
              {routeStations.length > 0 ? (
                <button
                  type="button"
                  onClick={resetStations}
                  className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  기준 정류장으로 되돌리기
                </button>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-y-2">
              {stationIds.map((stationId, position) => (
                <Fragment key={position}>
                  <button
                    type="button"
                    title="여기에 정류장 추가"
                    onClick={() => insertStation(position)}
                    className="mx-0.5 h-6 w-6 shrink-0 rounded-full border border-dashed border-slate-300 text-xs text-slate-400 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-600"
                  >
                    ＋
                  </button>
                  <div
                    className={`flex items-center gap-1 rounded-md border bg-white py-1 pl-2 pr-1 ${
                      stationId ? "border-slate-300" : "border-rose-300 bg-rose-50"
                    }`}
                  >
                    <span className="text-xs font-semibold text-slate-400">{position + 1}</span>
                    <select
                      className="max-w-40 bg-transparent text-xs font-medium text-slate-900 outline-none"
                      value={stationId}
                      onChange={(event) => changeStation(position, event.target.value)}
                    >
                      <option value="">정류장 선택</option>
                      {stations.map((station) => (
                        <option key={station.id} value={station.id}>
                          {station.name} ({station.id})
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      title="정류장 삭제"
                      onClick={() => removeStation(position)}
                      className="rounded px-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                    >
                      ×
                    </button>
                  </div>
                </Fragment>
              ))}
              <button
                type="button"
                title="맨 끝에 정류장 추가"
                onClick={() => insertStation(stationIds.length)}
                className="mx-0.5 h-6 w-6 shrink-0 rounded-full border border-dashed border-slate-300 text-xs text-slate-400 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-600"
              >
                ＋
              </button>
            </div>
          </div>
          {ambiguousRows.length > 0 ? (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              빈 칸 위치를 자동으로 정하지 못한 행이 {ambiguousRows.length}개 있습니다. 노란색 행의 시간을
              올바른 열로 옮겨 주세요.
            </div>
          ) : null}

          <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="bg-slate-50">
                  <th className="px-2 py-2 text-xs font-medium text-slate-500">#</th>
                  {Array.from({ length: columnCount }, (_, column) => {
                    const name = stationIds[column] ? getStationName(stationIds[column]) : null;
                    return (
                      <th
                        key={column}
                        className={`px-2 py-2 text-xs font-medium ${
                          name ? "text-slate-700" : "text-rose-600"
                        }`}
                      >
                        <span className="mr-1 text-slate-400">{column + 1}</span>
                        {name ?? (column < stationIds.length ? "미선택" : "정류장 없음")}
                      </th>
                    );
                  })}
                  <th />
                </tr>
              </thead>
              <tbody>
                {grid.map((row, rowIndex) => {
                  const warning = ambiguousRows.includes(rowIndex)
                    ? "빈 칸 위치를 확인하세요."
                    : rowWarnings.get(rowIndex);
                  return (
                    <tr key={rowIndex} className={`border-t border-slate-100 ${warning ? "bg-amber-50" : ""}`}>
                      <td className="px-2 py-1 text-center text-xs text-slate-400">{rowIndex + 1}</td>
                      {row.map((cell, column) => (
                        <td key={column} className="px-1 py-1">
                          <input
                            className={`w-full min-w-16 rounded-md border px-2 py-1 text-center font-mono text-sm ${
                              cell.trim() !== "" && !isTimeCell(cell)
                                ? "border-rose-400 bg-rose-50"
                                : "border-transparent bg-transparent hover:border-slate-300 focus:border-blue-500 focus:bg-white"
                            } outline-none`}
                            value={cell}
                            onChange={(event) => updateCell(rowIndex, column, event.target.value)}
                          />
                        </td>
                      ))}
                      <td className="whitespace-nowrap px-2 py-1 text-xs text-amber-700">
                        <button
                          type="button"
                          title="행 삭제"
                          onClick={() => removeRow(rowIndex)}
                          className="mr-1 rounded px-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                        >
                          ×
                        </button>
                        {warning}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
            <div className="mr-auto text-sm text-slate-500">
              {blockingError ?? `${grid.length}개 회차${warningCount > 0 ? ` · 확인 필요 ${warningCount}개` : ""}`}
            </div>
            <button
              type="button"
              onClick={downloadCsv}
              disabled={blockingError !== null}
              className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
            >
              CSV 다운로드
            </button>
            <button
              type="button"
              onClick={() => void register()}
              disabled={blockingError !== null || isRegistering}
              className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:bg-blue-300"
            >
              {isRegistering ? "등록 중..." : "바로 등록"}
            </button>
          </div>
        </>
      ) : null}
    </AdminPanel>
  );
}
