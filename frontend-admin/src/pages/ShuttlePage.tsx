import { type ChangeEvent, type DragEvent, FormEvent, useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { AdminPanel } from "../components/AdminPanel";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { ApiError } from "../lib/api";
import {
  clearShuttleCache,
  createShuttleSchedule,
  createShuttleScheduleException,
  createShuttleScheduleType,
  deleteShuttleSchedule,
  deleteShuttleScheduleException,
  deleteShuttleScheduleType,
  getShuttleRoutes,
  getShuttleScheduleExceptions,
  getShuttleScheduleStops,
  getShuttleSchedules,
  getShuttleScheduleTypes,
  getShuttleStations,
  updateShuttleSchedule,
  updateShuttleScheduleException,
  updateShuttleScheduleType,
} from "../lib/shuttleApi";
import { parseCsvRows, schedulesFromCsvRows } from "../lib/shuttleCsv";
import type {
  ShuttleRoute,
  ShuttleSchedule,
  ShuttleScheduleException,
  ShuttleScheduleExceptionPayload,
  ShuttleSchedulePayload,
  ShuttleScheduleType,
  ShuttleStation,
} from "../lib/shuttleTypes";
import { useToast } from "../toast/ToastProvider";
import {
  ExceptionForm,
  ExceptionTable,
  type ExceptionFormState,
  ScheduleTable,
  ScheduleTypeForm,
  ScheduleTypeTable,
  SummaryCard,
  type ScheduleTypeFormState,
  StopRow,
  type ShuttleStopForm,
} from "./shuttlePageParts";

type BannerState = {
  tone: "success" | "error";
  message: string;
} | null;

const EMPTY_TYPE_FORM: ScheduleTypeFormState = {
  code: "",
  name: "",
  is_activate: true,
};

const EMPTY_EXCEPTION_FORM: ExceptionFormState = {
  id: null,
  start_date: "",
  end_date: "",
  schedule_type: "",
  reason: "",
  is_activate: true,
  include_weekday: true,
  include_weekday_friday: true,
  include_saturday: false,
  include_sunday: false,
  include_holiday: false,
};

type ScheduleFormState = {
  route_id: string;
  schedule_type: string;
  start_time: string;
  end_time: string;
  stops: ShuttleStopForm[];
};

function createEmptyStop(order = 1): ShuttleStopForm {
  return { station_id: "", arrival_time: "", stop_order: order };
}

function createEmptyScheduleForm(): ScheduleFormState {
  return {
    route_id: "",
    schedule_type: "",
    start_time: "",
    end_time: "",
    stops: [createEmptyStop()],
  };
}

function toApiTime(value: string) {
  if (!value) return "";
  if (/^\d{2}:\d{2}:\d{2}$/.test(value)) return value;
  if (/^\d{1,2}:\d{2}$/.test(value)) {
    const [hours, minutes] = value.split(":");
    return `${hours.padStart(2, "0")}:${minutes}:00`;
  }
  return value;
}

function toInputTime(value: string) {
  return value ? value.slice(0, 5) : "";
}

export function ShuttlePage() {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const { showToast } = useToast();
  useDocumentTitle("셔틀 관리");

  const [banner, setBanner] = useState<BannerState>(null);
  const [routes, setRoutes] = useState<ShuttleRoute[]>([]);
  const [stations, setStations] = useState<ShuttleStation[]>([]);
  const [scheduleTypes, setScheduleTypes] = useState<ShuttleScheduleType[]>([]);
  const [exceptions, setExceptions] = useState<ShuttleScheduleException[]>([]);
  const [schedules, setSchedules] = useState<ShuttleSchedule[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState("");
  const [selectedScheduleType, setSelectedScheduleType] = useState("");
  const [selectedScheduleIds, setSelectedScheduleIds] = useState<number[]>([]);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [isCsvDragOver, setIsCsvDragOver] = useState(false);
  const [scheduleForm, setScheduleForm] = useState<ScheduleFormState>(createEmptyScheduleForm);
  const [editingScheduleId, setEditingScheduleId] = useState<number | null>(null);
  const [typeForm, setTypeForm] = useState<ScheduleTypeFormState>(EMPTY_TYPE_FORM);
  const [editingTypeCode, setEditingTypeCode] = useState<string | null>(null);
  const [exceptionForm, setExceptionForm] = useState<ExceptionFormState>(EMPTY_EXCEPTION_FORM);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isSearching, setIsSearching] = useState(false);
  const [isSavingSchedule, setIsSavingSchedule] = useState(false);
  const [isSavingType, setIsSavingType] = useState(false);
  const [isSavingException, setIsSavingException] = useState(false);
  const [isUploadingCsv, setIsUploadingCsv] = useState(false);
  const [isClearingCache, setIsClearingCache] = useState(false);

  async function handleUnauthorized() {
    await logout();
    navigate("/login", { replace: true, state: { from: "/shuttle" } });
  }

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  function showSuccessToast(message: string) {
    showToast(message, "success");
  }

  function showErrorToast(message: string) {
    showToast(message, "error");
  }

  async function handleError(error: unknown, fallbackMessage: string) {
    if (error instanceof ApiError && error.status === 401) {
      await handleUnauthorized();
      return;
    }
    const message =
      error instanceof ApiError
        ? error.message
        : error instanceof Error
          ? error.message
          : fallbackMessage;
    showErrorToast(message);
  }

  useEffect(() => {
    if (!banner) {
      return;
    }

    showToast(banner.message, banner.tone === "success" ? "success" : "error");
    setBanner(null);
  }, [banner, showToast]);

  async function loadReferences() {
    setIsBootstrapping(true);
    try {
      const [nextRoutes, nextStations, nextScheduleTypes, nextExceptions] = await Promise.all([
        getShuttleRoutes(),
        getShuttleStations(),
        getShuttleScheduleTypes(),
        getShuttleScheduleExceptions(),
      ]);
      setRoutes(nextRoutes);
      setStations(nextStations);
      setScheduleTypes(nextScheduleTypes);
      setExceptions(nextExceptions);
    } catch (error) {
      await handleError(error, "셔틀 데이터를 불러오지 못했습니다.");
    } finally {
      setIsBootstrapping(false);
    }
  }

  useEffect(() => {
    void loadReferences();
  }, []);

  function getRouteLabel(routeId: number) {
    const route = routes.find((item) => item.id === routeId);
    return route ? `${route.route_name} (${route.direction})` : `노선 ${routeId}`;
  }

  function getScheduleTypeLabel(code: string) {
    const match = scheduleTypes.find((item) => item.schedule_type === code);
    if (!match) return code;
    return `${match.schedule_type_name}${match.is_activate ? "" : " (비활성화)"}`;
  }

  function resetScheduleForm() {
    setEditingScheduleId(null);
    setScheduleForm(createEmptyScheduleForm());
  }

  function resetTypeForm() {
    setEditingTypeCode(null);
    setTypeForm(EMPTY_TYPE_FORM);
  }

  function resetExceptionForm() {
    setExceptionForm(EMPTY_EXCEPTION_FORM);
  }

  function updateStop(index: number, key: keyof ShuttleStopForm, value: string | number) {
    setScheduleForm((current) => ({
      ...current,
      stops: current.stops.map((stop, stopIndex) =>
        stopIndex === index ? { ...stop, [key]: value } : stop,
      ),
    }));
  }

  function addStop() {
    setScheduleForm((current) => ({
      ...current,
      stops: [...current.stops, createEmptyStop(current.stops.length + 1)],
    }));
  }

  function removeStop(index: number) {
    setScheduleForm((current) => {
      const nextStops = current.stops.filter((_, stopIndex) => stopIndex !== index);
      return {
        ...current,
        stops:
          nextStops.length > 0
            ? nextStops.map((stop, stopIndex) => ({
                ...stop,
                stop_order: stopIndex + 1,
              }))
            : [createEmptyStop()],
      };
    });
  }

  async function searchSchedules(routeIdOverride?: number, scheduleTypeOverride?: string) {
    const routeId = routeIdOverride ?? Number(selectedRouteId);
    const scheduleType = scheduleTypeOverride ?? selectedScheduleType;
    if (!routeId || !scheduleType) {
      setBanner({ tone: "error", message: "노선과 일정 유형을 선택하세요." });
      return;
    }
    setIsSearching(true);
    try {
      const nextSchedules = await getShuttleSchedules(routeId, scheduleType);
      setSchedules(nextSchedules);
      setSelectedScheduleIds([]);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setSchedules([]);
        setSelectedScheduleIds([]);
      } else {
        await handleError(error, "시간표를 불러오지 못했습니다.");
      }
    } finally {
      setIsSearching(false);
    }
  }

  async function editSchedule(schedule: ShuttleSchedule) {
    try {
      const stops = await getShuttleScheduleStops(schedule.id);
      setEditingScheduleId(schedule.id);
      setScheduleForm({
        route_id: String(schedule.route_id),
        schedule_type: schedule.schedule_type,
        start_time: toInputTime(schedule.start_time),
        end_time: toInputTime(schedule.end_time),
        stops:
          stops.length > 0
            ? stops.map((stop) => ({
                station_id: String(stop.station_id),
                arrival_time: toInputTime(stop.arrival_time),
                stop_order: stop.stop_order,
              }))
            : [createEmptyStop()],
      });
    } catch (error) {
      await handleError(error, "시간표 상세를 불러오지 못했습니다.");
    }
  }

  async function handleScheduleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (
      !scheduleForm.route_id ||
      !scheduleForm.schedule_type ||
      !scheduleForm.start_time ||
      !scheduleForm.end_time
    ) {
      setBanner({ tone: "error", message: "노선, 일정 유형, 시간을 모두 입력하세요." });
      return;
    }

    if (scheduleForm.stops.some((stop) => !stop.station_id || !stop.arrival_time)) {
      setBanner({ tone: "error", message: "모든 정류장 정보를 입력하세요." });
      return;
    }

    const payload: ShuttleSchedulePayload = {
      route_id: Number(scheduleForm.route_id),
      schedule_type: scheduleForm.schedule_type,
      start_time: toApiTime(scheduleForm.start_time),
      end_time: toApiTime(scheduleForm.end_time),
      stops: [...scheduleForm.stops]
        .sort((left, right) => left.stop_order - right.stop_order)
        .map((stop, index) => ({
          station_id: Number(stop.station_id),
          arrival_time: toApiTime(stop.arrival_time),
          stop_order: index + 1,
        })),
    };

    setIsSavingSchedule(true);

    try {
      if (editingScheduleId) {
        await updateShuttleSchedule(editingScheduleId, payload);
        setBanner({ tone: "success", message: "시간표를 수정했습니다." });
      } else {
        await createShuttleSchedule(payload);
        setBanner({ tone: "success", message: "시간표를 추가했습니다." });
      }

      resetScheduleForm();

      if (Number(selectedRouteId) === payload.route_id && selectedScheduleType === payload.schedule_type) {
        await searchSchedules(payload.route_id, payload.schedule_type);
      }
    } catch (error) {
      await handleError(error, "시간표 저장에 실패했습니다.");
    } finally {
      setIsSavingSchedule(false);
    }
  }

  async function removeSchedule(scheduleId: number) {
    if (!window.confirm("이 시간표를 삭제하시겠습니까?")) {
      return;
    }

    try {
      await deleteShuttleSchedule(scheduleId);
      setBanner({ tone: "success", message: "시간표를 삭제했습니다." });
      if (editingScheduleId === scheduleId) {
        resetScheduleForm();
      }
      await searchSchedules();
    } catch (error) {
      await handleError(error, "시간표 삭제에 실패했습니다.");
    }
  }

  async function removeSelectedSchedules() {
    if (selectedScheduleIds.length === 0) {
      setBanner({ tone: "error", message: "삭제할 시간표를 선택하세요." });
      return;
    }

    if (!window.confirm(`선택한 시간표 ${selectedScheduleIds.length}개를 삭제하시겠습니까?`)) {
      return;
    }

    try {
      for (const scheduleId of selectedScheduleIds) {
        await deleteShuttleSchedule(scheduleId);
      }
      setBanner({ tone: "success", message: "선택한 시간표를 삭제했습니다." });
      setSelectedScheduleIds([]);
      await searchSchedules();
    } catch (error) {
      await handleError(error, "선택 삭제에 실패했습니다.");
    }
  }

  function validateCsvFile(file: File) {
    return file.name.toLowerCase().endsWith(".csv");
  }

  async function uploadCsvFile(file: File) {
    if (!validateCsvFile(file)) {
      setBanner({ tone: "error", message: "CSV 파일만 업로드할 수 있습니다." });
      return;
    }

    setCsvFile(file);
    setIsUploadingCsv(true);

    try {
      const parsed = schedulesFromCsvRows(parseCsvRows(await file.text()));
      for (const schedule of parsed.schedules) {
        await createShuttleSchedule(schedule);
      }
      setCsvFile(null);
      setSelectedRouteId(String(parsed.routeId));
      setSelectedScheduleType(parsed.scheduleType);
      setBanner({
        tone: "success",
        message: `${parsed.schedules.length}개 시간표를 일괄 등록했습니다.`,
      });
      await searchSchedules(parsed.routeId, parsed.scheduleType);
    } catch (error) {
      await handleError(error, "CSV 처리에 실패했습니다.");
    } finally {
      setIsUploadingCsv(false);
    }
  }

  async function handleCsvUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!csvFile) {
      setBanner({ tone: "error", message: "CSV 파일을 선택하세요." });
      return;
    }

    await uploadCsvFile(csvFile);
    return;

    setIsUploadingCsv(true);

    try {
      const parsed = schedulesFromCsvRows(parseCsvRows(await csvFile!.text()));
      for (const schedule of parsed.schedules) {
        await createShuttleSchedule(schedule);
      }
      setCsvFile(null);
      setSelectedRouteId(String(parsed.routeId));
      setSelectedScheduleType(parsed.scheduleType);
      setBanner({
        tone: "success",
        message: `${parsed.schedules.length}개의 시간표를 일괄 등록했습니다.`,
      });
      await searchSchedules(parsed.routeId, parsed.scheduleType);
    } catch (error) {
      await handleError(error, "CSV 처리에 실패했습니다.");
    } finally {
      setIsUploadingCsv(false);
    }
  }

  async function handleCsvFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";

    if (!file || isUploadingCsv) {
      return;
    }

    await uploadCsvFile(file);
  }

  function handleCsvDragOver(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setIsCsvDragOver(true);
  }

  function handleCsvDragLeave(event: DragEvent<HTMLLabelElement>) {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
      return;
    }

    setIsCsvDragOver(false);
  }

  async function handleCsvDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsCsvDragOver(false);

    if (isUploadingCsv) {
      return;
    }

    const file = event.dataTransfer.files?.[0];
    if (!file) {
      return;
    }

    await uploadCsvFile(file);
  }

  async function handleTypeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!typeForm.code.trim() || !typeForm.name.trim()) {
      setBanner({ tone: "error", message: "일정 유형 코드와 이름을 입력하세요." });
      return;
    }

    setIsSavingType(true);

    try {
      if (editingTypeCode) {
        await updateShuttleScheduleType(editingTypeCode, {
          schedule_type_name: typeForm.name.trim(),
          is_activate: typeForm.is_activate,
        });
        setBanner({ tone: "success", message: "일정 유형을 수정했습니다." });
      } else {
        await createShuttleScheduleType({
          schedule_type: typeForm.code.trim(),
          schedule_type_name: typeForm.name.trim(),
          is_activate: typeForm.is_activate,
        });
        setBanner({ tone: "success", message: "일정 유형을 추가했습니다." });
      }

      resetTypeForm();
      setScheduleTypes(await getShuttleScheduleTypes());
    } catch (error) {
      await handleError(error, "일정 유형 저장에 실패했습니다.");
    } finally {
      setIsSavingType(false);
    }
  }

  async function removeScheduleType(scheduleType: string) {
    if (!window.confirm(`일정 유형 '${scheduleType}'을 삭제하시겠습니까?`)) {
      return;
    }

    try {
      await deleteShuttleScheduleType(scheduleType);
      setBanner({ tone: "success", message: "일정 유형을 삭제했습니다." });
      setScheduleTypes(await getShuttleScheduleTypes());
      resetTypeForm();
    } catch (error) {
      await handleError(error, "일정 유형 삭제에 실패했습니다.");
    }
  }

  async function handleExceptionSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (
      !exceptionForm.start_date ||
      !exceptionForm.end_date ||
      !exceptionForm.schedule_type
    ) {
      setBanner({ tone: "error", message: "예외 기간과 일정 유형을 입력하세요." });
      return;
    }

    const payload: ShuttleScheduleExceptionPayload = {
      start_date: exceptionForm.start_date,
      end_date: exceptionForm.end_date,
      schedule_type: exceptionForm.schedule_type,
      reason: exceptionForm.reason.trim(),
      is_activate: exceptionForm.is_activate,
      include_weekday: exceptionForm.include_weekday,
      include_weekday_friday: exceptionForm.include_weekday_friday,
      include_saturday: exceptionForm.include_saturday,
      include_sunday: exceptionForm.include_sunday,
      include_holiday: exceptionForm.include_holiday,
    };

    setIsSavingException(true);

    try {
      if (exceptionForm.id) {
        await updateShuttleScheduleException(exceptionForm.id, payload);
        setBanner({ tone: "success", message: "일정 예외를 수정했습니다." });
      } else {
        await createShuttleScheduleException(payload);
        setBanner({ tone: "success", message: "일정 예외를 추가했습니다." });
      }

      resetExceptionForm();
      setExceptions(await getShuttleScheduleExceptions());
    } catch (error) {
      await handleError(error, "일정 예외 저장에 실패했습니다.");
    } finally {
      setIsSavingException(false);
    }
  }

  async function removeException(exceptionId: number) {
    if (!window.confirm("이 일정 예외를 삭제하시겠습니까?")) {
      return;
    }

    try {
      await deleteShuttleScheduleException(exceptionId);
      setBanner({ tone: "success", message: "일정 예외를 삭제했습니다." });
      setExceptions(await getShuttleScheduleExceptions());
      resetExceptionForm();
    } catch (error) {
      await handleError(error, "일정 예외 삭제에 실패했습니다.");
    }
  }

  async function handleClearCache() {
    if (!window.confirm("셔틀 캐시를 모두 비우시겠습니까?")) {
      return;
    }

    setIsClearingCache(true);

    try {
      const response = await clearShuttleCache();
      setBanner({ tone: "success", message: response.message || "셔틀 캐시를 비웠습니다." });
    } catch (error) {
      await handleError(error, "캐시 비우기에 실패했습니다.");
    } finally {
      setIsClearingCache(false);
    }
  }

  const allSelected =
    schedules.length > 0 &&
    schedules.every((schedule) => selectedScheduleIds.includes(schedule.id));

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-slate-200 bg-slate-900 text-white lg:flex lg:flex-col">
        <div className="border-b border-white/10 px-6 py-5 text-lg font-semibold">
          호통 대시보드
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-4 py-4 pb-24">
          <NavLink
            to="/notices"
            className={({ isActive }) =>
              `block rounded-lg px-4 py-3 text-sm transition ${
                isActive
                  ? "bg-white/10 text-white"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`
            }
          >
            공지 관리
          </NavLink>
          <NavLink
            to="/emergency-notices"
            className={({ isActive }) =>
              `mt-2 block rounded-lg px-4 py-3 text-sm transition ${
                isActive
                  ? "bg-white/10 text-white"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`
            }
          >
            긴급공지 관리
          </NavLink>
          <NavLink
            to="/shuttle"
            className={({ isActive }) =>
              `mt-2 block rounded-lg px-4 py-3 text-sm transition ${
                isActive
                  ? "bg-white/10 text-white"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`
            }
          >
            셔틀 관리
          </NavLink>
          <NavLink
            to="/shuttle-stations"
            className={({ isActive }) =>
              `mt-2 block rounded-lg px-4 py-3 text-sm transition ${
                isActive
                  ? "bg-white/10 text-white"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`
            }
          >
            정류장 관리
          </NavLink>
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-white/10 bg-slate-900/95 p-4 backdrop-blur">
          <button
            type="button"
            onClick={handleLogout}
            className="w-full rounded-lg bg-white/10 px-4 py-3 text-sm font-medium text-white transition hover:bg-white/15"
          >
            로그아웃
          </button>
        </div>
      </aside>

      <div className="min-h-screen">
        <header className="border-b border-slate-200 bg-white">
          <div className="flex flex-col gap-4 px-4 py-4 sm:px-6 lg:px-8">
            <div className="motion-enter flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h1 className="text-2xl font-semibold text-slate-900">셔틀 시간표 관리</h1>
                <p className="mt-1 text-sm text-slate-500">
                  시간표, 일정 유형, 일정 예외를 관리합니다.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                  {user?.email}
                </div>
                <NavLink
                  to="/notices"
                  className={({ isActive }) =>
                    `rounded-lg border px-4 py-2 text-sm font-medium transition lg:hidden ${
                      isActive
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                    }`
                  }
                >
                  공지
                </NavLink>
                <NavLink
                  to="/emergency-notices"
                  className={({ isActive }) =>
                    `rounded-lg border px-4 py-2 text-sm font-medium transition lg:hidden ${
                      isActive
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                    }`
                  }
                >
                  긴급공지
                </NavLink>
                <NavLink
                  to="/shuttle"
                  className={({ isActive }) =>
                    `rounded-lg border px-4 py-2 text-sm font-medium transition lg:hidden ${
                      isActive
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                    }`
                  }
                >
                  셔틀
                </NavLink>
                <NavLink
                  to="/shuttle-stations"
                  className={({ isActive }) =>
                    `rounded-lg border px-4 py-2 text-sm font-medium transition lg:hidden ${
                      isActive
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                    }`
                  }
                >
                  정류장
                </NavLink>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 lg:hidden"
                >
                  로그아웃
                </button>
              </div>
            </div>
            <div className="motion-enter motion-enter-delay-1 grid gap-3 sm:grid-cols-3 xl:max-w-3xl">
              <SummaryCard label="노선 수" value={String(routes.length)} />
              <SummaryCard label="일정 유형" value={String(scheduleTypes.length)} />
              <SummaryCard label="예외 일정" value={String(exceptions.length)} />
            </div>
          </div>
        </header>

        <main className="motion-enter motion-enter-delay-2 px-4 py-6 sm:px-6 lg:px-8">
          {isBootstrapping ? (
            <AdminPanel title="셔틀 데이터 로딩">
              <div className="text-sm text-slate-500">관리 데이터를 불러오는 중입니다.</div>
            </AdminPanel>
          ) : (
            <>
              <div className="grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_360px]">
                <AdminPanel title="CSV 일괄 등록" description="기존 CSV 형식을 그대로 사용합니다.">
                  <div className="mb-3 space-y-3">
                    <label
                      className={`flex min-h-36 w-full flex-col items-center justify-center rounded-xl border-2 border-dashed px-5 py-6 text-center transition ${
                        isCsvDragOver
                          ? "border-blue-500 bg-blue-50"
                          : "border-slate-300 bg-slate-50 hover:border-blue-400 hover:bg-blue-50/50"
                      } ${isUploadingCsv ? "pointer-events-none opacity-70" : ""}`}
                      onDragOver={handleCsvDragOver}
                      onDragLeave={handleCsvDragLeave}
                      onDrop={(event) => void handleCsvDrop(event)}
                    >
                      <input
                        type="file"
                        accept=".csv"
                        className="hidden"
                        onChange={(event) => void handleCsvFileChange(event)}
                        disabled={isUploadingCsv}
                      />
                      <div className="text-base font-semibold text-slate-800">
                        {isUploadingCsv ? "CSV 처리 중..." : "CSV 파일을 여기로 끌어놓기"}
                      </div>
                      <div className="mt-1 text-sm text-slate-500">
                        클릭해서 파일을 선택해도 바로 등록됩니다.
                      </div>
                      <div className="mt-3 text-xs text-slate-400">.csv 파일만 업로드 가능</div>
                    </label>
                    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                      {csvFile ? (
                        <span className="block truncate">선택한 파일: {csvFile.name}</span>
                      ) : (
                        <span>선택한 파일 없음</span>
                      )}
                    </div>
                  </div>
                  <form className="hidden" onSubmit={handleCsvUpload}>
                    <input
                      type="file"
                      accept=".csv"
                      className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-700"
                      onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
                    />
                    <button
                      type="submit"
                      className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:bg-blue-300"
                      disabled={isUploadingCsv}
                    >
                      {isUploadingCsv ? "처리 중..." : "업로드 및 처리"}
                    </button>
                  </form>
                </AdminPanel>
                <AdminPanel title="캐시 관리">
                  <button
                    type="button"
                    onClick={handleClearCache}
                    className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                    disabled={isClearingCache}
                  >
                    {isClearingCache ? "비우는 중..." : "셔틀 캐시 비우기"}
                  </button>
                </AdminPanel>
              </div>

              <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(360px,0.9fr)]">
                <AdminPanel title="시간표 조회">
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
                    <select
                      className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                      value={selectedRouteId}
                      onChange={(event) => setSelectedRouteId(event.target.value)}
                    >
                      <option value="">노선 선택</option>
                      {routes.map((route) => (
                        <option key={route.id} value={route.id}>
                          {route.route_name} ({route.direction})
                        </option>
                      ))}
                    </select>
                    <select
                      className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                      value={selectedScheduleType}
                      onChange={(event) => setSelectedScheduleType(event.target.value)}
                    >
                      <option value="">일정 유형 선택</option>
                      {scheduleTypes.map((scheduleType) => (
                        <option
                          key={scheduleType.schedule_type}
                          value={scheduleType.schedule_type}
                        >
                          {getScheduleTypeLabel(scheduleType.schedule_type)}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void searchSchedules()}
                      className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:bg-blue-300"
                      disabled={isSearching}
                    >
                      {isSearching ? "조회 중..." : "조회"}
                    </button>
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-3">
                    <div className="text-sm text-slate-500">조회 결과 {schedules.length}건</div>
                    <button
                      type="button"
                      onClick={removeSelectedSchedules}
                      className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-100"
                    >
                      선택 삭제
                    </button>
                  </div>
                  <ScheduleTable
                    schedules={schedules}
                    allSelected={allSelected}
                    selectedIds={selectedScheduleIds}
                    onToggleAll={(checked) =>
                      setSelectedScheduleIds(checked ? schedules.map((schedule) => schedule.id) : [])
                    }
                    onToggleOne={(scheduleId, checked) =>
                      setSelectedScheduleIds((current) =>
                        checked ? [...current, scheduleId] : current.filter((value) => value !== scheduleId),
                      )
                    }
                    getRouteLabel={getRouteLabel}
                    getScheduleTypeLabel={getScheduleTypeLabel}
                    onEdit={(schedule) => void editSchedule(schedule)}
                    onDelete={(scheduleId) => void removeSchedule(scheduleId)}
                  />
                </AdminPanel>

                <AdminPanel title={editingScheduleId ? "시간표 수정" : "시간표 추가"}>
                  <form className="space-y-4" onSubmit={handleScheduleSubmit}>
                    <select
                      className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                      value={scheduleForm.route_id}
                      onChange={(event) =>
                        setScheduleForm((current) => ({ ...current, route_id: event.target.value }))
                      }
                    >
                      <option value="">노선 선택</option>
                      {routes.map((route) => (
                        <option key={route.id} value={route.id}>
                          {route.route_name} ({route.direction})
                        </option>
                      ))}
                    </select>
                    <select
                      className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                      value={scheduleForm.schedule_type}
                      onChange={(event) =>
                        setScheduleForm((current) => ({ ...current, schedule_type: event.target.value }))
                      }
                    >
                      <option value="">일정 유형 선택</option>
                      {scheduleTypes.map((scheduleType) => (
                        <option key={scheduleType.schedule_type} value={scheduleType.schedule_type}>
                          {getScheduleTypeLabel(scheduleType.schedule_type)}
                        </option>
                      ))}
                    </select>
                    <div className="grid gap-3 md:grid-cols-2">
                      <input
                        type="time"
                        className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                        value={scheduleForm.start_time}
                        onChange={(event) =>
                          setScheduleForm((current) => ({ ...current, start_time: event.target.value }))
                        }
                      />
                      <input
                        type="time"
                        className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
                        value={scheduleForm.end_time}
                        onChange={(event) =>
                          setScheduleForm((current) => ({ ...current, end_time: event.target.value }))
                        }
                      />
                    </div>
                    <div>
                      <div className="mb-3 flex items-center justify-between">
                        <div className="text-sm font-medium text-slate-700">정류장</div>
                        <button
                          type="button"
                          onClick={addStop}
                          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
                        >
                          정류장 추가
                        </button>
                      </div>
                      <div className="space-y-3">
                        {scheduleForm.stops.map((stop, index) => (
                          <StopRow
                            key={`${editingScheduleId ?? "new"}-${index}`}
                            stop={stop}
                            stations={stations}
                            onChange={(key, value) => updateStop(index, key, value)}
                            onRemove={() => removeStop(index)}
                          />
                        ))}
                      </div>
                    </div>
                    <div className="flex flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        onClick={resetScheduleForm}
                        className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                      >
                        양식 초기화
                      </button>
                      {editingScheduleId ? (
                        <button
                          type="button"
                          onClick={() => void removeSchedule(editingScheduleId)}
                          className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700 transition hover:bg-rose-100"
                        >
                          삭제
                        </button>
                      ) : null}
                      <button
                        type="submit"
                        className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:bg-blue-300"
                        disabled={isSavingSchedule}
                      >
                        {isSavingSchedule ? "저장 중..." : "저장"}
                      </button>
                    </div>
                  </form>
                </AdminPanel>
              </div>

              <div className="mt-6 grid gap-6 xl:grid-cols-2">
                <AdminPanel title="일정 유형">
                  <ScheduleTypeForm
                    form={typeForm}
                    editingTypeCode={editingTypeCode}
                    onChange={setTypeForm}
                    onReset={resetTypeForm}
                    onSubmit={handleTypeSubmit}
                    isSaving={isSavingType}
                  />
                  <ScheduleTypeTable
                    scheduleTypes={scheduleTypes}
                    onEdit={(scheduleType) => {
                      setEditingTypeCode(scheduleType.schedule_type);
                      setTypeForm({
                        code: scheduleType.schedule_type,
                        name: scheduleType.schedule_type_name,
                        is_activate: scheduleType.is_activate,
                      });
                    }}
                    onDelete={(scheduleType) => void removeScheduleType(scheduleType)}
                  />
                </AdminPanel>

                <AdminPanel title="일정 예외">
                  <ExceptionForm
                    form={exceptionForm}
                    scheduleTypes={scheduleTypes}
                    getScheduleTypeLabel={getScheduleTypeLabel}
                    onChange={setExceptionForm}
                    onReset={resetExceptionForm}
                    onSubmit={handleExceptionSubmit}
                    isSaving={isSavingException}
                  />
                  <ExceptionTable
                    exceptions={exceptions}
                    onEdit={(exception) =>
                      setExceptionForm({
                        id: exception.id,
                        start_date: exception.start_date,
                        end_date: exception.end_date,
                        schedule_type: exception.schedule_type,
                        reason: exception.reason ?? "",
                        is_activate: exception.is_activate,
                        include_weekday: exception.include_weekday,
                        include_weekday_friday: exception.include_weekday_friday,
                        include_saturday: exception.include_saturday,
                        include_sunday: exception.include_sunday,
                        include_holiday: exception.include_holiday,
                      })
                    }
                    onDelete={(exceptionId) => void removeException(exceptionId)}
                  />
                </AdminPanel>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
