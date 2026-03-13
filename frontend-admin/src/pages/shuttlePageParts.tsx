import type { FormEvent } from "react";

import type {
  ShuttleSchedule,
  ShuttleScheduleException,
  ShuttleScheduleType,
  ShuttleStation,
} from "../lib/shuttleTypes";

export type ShuttleStopForm = {
  station_id: string;
  arrival_time: string;
  stop_order: number;
};

export type ScheduleTypeFormState = {
  code: string;
  name: string;
  is_activate: boolean;
};

export type ExceptionFormState = {
  id: number | null;
  start_date: string;
  end_date: string;
  schedule_type: string;
  reason: string;
  is_activate: boolean;
  include_weekday: boolean;
  include_weekday_friday: boolean;
  include_saturday: boolean;
  include_sunday: boolean;
  include_holiday: boolean;
};

export function Banner({
  message,
  tone,
}: {
  message: string;
  tone: "success" | "error";
}) {
  return (
    <div
      className={`mb-4 rounded-lg px-4 py-3 text-sm ${
        tone === "success"
          ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border border-rose-200 bg-rose-50 text-rose-700"
      }`}
    >
      {message}
    </div>
  );
}

export function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

export function ToggleField({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-3 rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 text-sm text-slate-700">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

export function StopRow({
  stop,
  stations,
  onChange,
  onRemove,
}: {
  stop: ShuttleStopForm;
  stations: ShuttleStation[];
  onChange: (key: keyof ShuttleStopForm, value: string | number) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <select
        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
        value={stop.station_id}
        onChange={(event) => onChange("station_id", event.target.value)}
      >
        <option value="">정류장 선택</option>
        {stations.map((station) => (
          <option key={station.id} value={station.id}>
            {station.name}
          </option>
        ))}
      </select>
      <div className="grid gap-3 md:grid-cols-[1fr_120px_auto]">
        <input
          type="time"
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
          value={stop.arrival_time}
          onChange={(event) => onChange("arrival_time", event.target.value)}
        />
        <input
          type="number"
          min={1}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
          value={stop.stop_order}
          onChange={(event) => onChange("stop_order", Number(event.target.value))}
        />
        <button
          type="button"
          onClick={onRemove}
          className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-100"
        >
          삭제
        </button>
      </div>
    </div>
  );
}

export function ScheduleTable({
  schedules,
  allSelected,
  selectedIds,
  onToggleAll,
  onToggleOne,
  getRouteLabel,
  getScheduleTypeLabel,
  onEdit,
  onDelete,
}: {
  schedules: ShuttleSchedule[];
  allSelected: boolean;
  selectedIds: number[];
  onToggleAll: (checked: boolean) => void;
  onToggleOne: (scheduleId: number, checked: boolean) => void;
  getRouteLabel: (routeId: number) => string;
  getScheduleTypeLabel: (scheduleType: string) => string;
  onEdit: (schedule: ShuttleSchedule) => void;
  onDelete: (scheduleId: number) => void;
}) {
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="px-4 py-3 font-medium">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={(event) => onToggleAll(event.target.checked)}
              />
            </th>
            <th className="px-4 py-3 font-medium">ID</th>
            <th className="px-4 py-3 font-medium">노선</th>
            <th className="px-4 py-3 font-medium">유형</th>
            <th className="px-4 py-3 font-medium">출발</th>
            <th className="px-4 py-3 font-medium">도착</th>
            <th className="px-4 py-3 font-medium">관리</th>
          </tr>
        </thead>
        <tbody>
          {schedules.length === 0 ? (
            <tr>
              <td className="px-4 py-8 text-center text-slate-500" colSpan={7}>
                조회된 시간표가 없습니다.
              </td>
            </tr>
          ) : (
            schedules.map((schedule) => (
              <tr key={schedule.id} className="border-t border-slate-200">
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(schedule.id)}
                    onChange={(event) => onToggleOne(schedule.id, event.target.checked)}
                  />
                </td>
                <td className="px-4 py-3 text-slate-500">{schedule.id}</td>
                <td className="px-4 py-3">{getRouteLabel(schedule.route_id)}</td>
                <td className="px-4 py-3">{getScheduleTypeLabel(schedule.schedule_type)}</td>
                <td className="px-4 py-3">{schedule.start_time.slice(0, 5)}</td>
                <td className="px-4 py-3">{schedule.end_time.slice(0, 5)}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => onEdit(schedule)}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
                    >
                      수정
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(schedule.id)}
                      className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 transition hover:bg-rose-100"
                    >
                      삭제
                    </button>
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function ScheduleTypeForm({
  editingTypeCode,
  form,
  isSaving,
  onChange,
  onReset,
  onSubmit,
}: {
  editingTypeCode: string | null;
  form: ScheduleTypeFormState;
  isSaving: boolean;
  onChange: (next: ScheduleTypeFormState) => void;
  onReset: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form
      className="mb-5 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4"
      onSubmit={onSubmit}
    >
      <div className="grid gap-3 md:grid-cols-2">
        <input
          className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100 disabled:bg-slate-100"
          value={form.code}
          onChange={(event) => onChange({ ...form, code: event.target.value })}
          placeholder="일정 유형 코드"
          disabled={Boolean(editingTypeCode)}
        />
        <input
          className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
          value={form.name}
          onChange={(event) => onChange({ ...form, name: event.target.value })}
          placeholder="일정 유형 이름"
        />
      </div>
      <ToggleField
        checked={form.is_activate}
        label="활성화"
        onChange={(checked) => onChange({ ...form, is_activate: checked })}
      />
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onReset}
          className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          초기화
        </button>
        <button
          type="submit"
          className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:bg-blue-300"
          disabled={isSaving}
        >
          {isSaving ? "저장 중..." : editingTypeCode ? "수정" : "추가"}
        </button>
      </div>
    </form>
  );
}

export function ScheduleTypeTable({
  scheduleTypes,
  onDelete,
  onEdit,
}: {
  scheduleTypes: ShuttleScheduleType[];
  onDelete: (scheduleType: string) => void;
  onEdit: (scheduleType: ShuttleScheduleType) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="px-4 py-3 font-medium">코드</th>
            <th className="px-4 py-3 font-medium">이름</th>
            <th className="px-4 py-3 font-medium">상태</th>
            <th className="px-4 py-3 font-medium">관리</th>
          </tr>
        </thead>
        <tbody>
          {scheduleTypes.length === 0 ? (
            <tr>
              <td className="px-4 py-8 text-center text-slate-500" colSpan={4}>
                일정 유형이 없습니다.
              </td>
            </tr>
          ) : (
            scheduleTypes.map((scheduleType) => (
              <tr key={scheduleType.schedule_type} className="border-t border-slate-200">
                <td className="px-4 py-3 font-mono text-xs text-slate-600">
                  {scheduleType.schedule_type}
                </td>
                <td className="px-4 py-3">{scheduleType.schedule_type_name}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${
                      scheduleType.is_activate
                        ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
                        : "border border-slate-200 bg-slate-100 text-slate-600"
                    }`}
                  >
                    {scheduleType.is_activate ? "활성화" : "비활성화"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => onEdit(scheduleType)}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
                    >
                      수정
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(scheduleType.schedule_type)}
                      className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 transition hover:bg-rose-100"
                    >
                      삭제
                    </button>
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function ExceptionForm({
  form,
  getScheduleTypeLabel,
  isSaving,
  onChange,
  onReset,
  onSubmit,
  scheduleTypes,
}: {
  form: ExceptionFormState;
  getScheduleTypeLabel: (scheduleType: string) => string;
  isSaving: boolean;
  onChange: (next: ExceptionFormState) => void;
  onReset: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  scheduleTypes: ShuttleScheduleType[];
}) {
  return (
    <form
      className="mb-5 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4"
      onSubmit={onSubmit}
    >
      <div className="grid gap-3 md:grid-cols-2">
        <input
          type="date"
          className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
          value={form.start_date}
          onChange={(event) => onChange({ ...form, start_date: event.target.value })}
        />
        <input
          type="date"
          className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
          value={form.end_date}
          onChange={(event) => onChange({ ...form, end_date: event.target.value })}
        />
      </div>
      <select
        className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
        value={form.schedule_type}
        onChange={(event) => onChange({ ...form, schedule_type: event.target.value })}
      >
        <option value="">일정 유형 선택</option>
        {scheduleTypes.map((scheduleType) => (
          <option key={scheduleType.schedule_type} value={scheduleType.schedule_type}>
            {getScheduleTypeLabel(scheduleType.schedule_type)}
          </option>
        ))}
      </select>
      <textarea
        className="min-h-24 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
        value={form.reason}
        onChange={(event) => onChange({ ...form, reason: event.target.value })}
        placeholder="사유"
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <ToggleField
          checked={form.include_weekday}
          label="평일 적용"
          onChange={(checked) => onChange({ ...form, include_weekday: checked })}
        />
        <ToggleField
          checked={form.include_weekday_friday}
          label="금요일 적용"
          onChange={(checked) => onChange({ ...form, include_weekday_friday: checked })}
        />
        <ToggleField
          checked={form.include_saturday}
          label="토요일 적용"
          onChange={(checked) => onChange({ ...form, include_saturday: checked })}
        />
        <ToggleField
          checked={form.include_sunday}
          label="일요일 적용"
          onChange={(checked) => onChange({ ...form, include_sunday: checked })}
        />
        <ToggleField
          checked={form.include_holiday}
          label="공휴일 적용"
          onChange={(checked) => onChange({ ...form, include_holiday: checked })}
        />
        <ToggleField
          checked={form.is_activate}
          label="활성화"
          onChange={(checked) => onChange({ ...form, is_activate: checked })}
        />
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onReset}
          className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          초기화
        </button>
        <button
          type="submit"
          className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:bg-blue-300"
          disabled={isSaving}
        >
          {isSaving ? "저장 중..." : form.id ? "수정" : "추가"}
        </button>
      </div>
    </form>
  );
}

export function ExceptionTable({
  exceptions,
  onDelete,
  onEdit,
}: {
  exceptions: ShuttleScheduleException[];
  onDelete: (exceptionId: number) => void;
  onEdit: (exception: ShuttleScheduleException) => void;
}) {
  const formatDate = (value: string) =>
    new Intl.DateTimeFormat("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date(value));

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="px-4 py-3 font-medium">기간</th>
            <th className="px-4 py-3 font-medium">유형</th>
            <th className="px-4 py-3 font-medium">사유</th>
            <th className="px-4 py-3 font-medium">상태</th>
            <th className="px-4 py-3 font-medium">관리</th>
          </tr>
        </thead>
        <tbody>
          {exceptions.length === 0 ? (
            <tr>
              <td className="px-4 py-8 text-center text-slate-500" colSpan={5}>
                일정 예외가 없습니다.
              </td>
            </tr>
          ) : (
            exceptions.map((exception) => (
              <tr key={exception.id} className="border-t border-slate-200">
                <td className="px-4 py-3 text-slate-600">
                  {formatDate(exception.start_date)} - {formatDate(exception.end_date)}
                </td>
                <td className="px-4 py-3">
                  {exception.schedule_type_name ?? exception.schedule_type}
                </td>
                <td className="px-4 py-3 text-slate-600">{exception.reason || "-"}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${
                      exception.is_activate
                        ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
                        : "border border-slate-200 bg-slate-100 text-slate-600"
                    }`}
                  >
                    {exception.is_activate ? "활성화" : "비활성화"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => onEdit(exception)}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
                    >
                      수정
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(exception.id)}
                      className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 transition hover:bg-rose-100"
                    >
                      삭제
                    </button>
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
