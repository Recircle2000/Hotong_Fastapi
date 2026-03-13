import { ApiError } from "./api";
import type {
  ShuttleCacheResponse,
  ShuttleMutationResponse,
  ShuttleRoute,
  ShuttleSchedule,
  ShuttleScheduleException,
  ShuttleScheduleExceptionPayload,
  ShuttleSchedulePayload,
  ShuttleScheduleStop,
  ShuttleScheduleType,
  ShuttleScheduleTypePayload,
  ShuttleScheduleTypeUpdatePayload,
  ShuttleStation,
} from "./shuttleTypes";

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: BodyInit | object;
};

const SHUTTLE_API_BASE = "/shuttle";

async function requestShuttleAccessToken() {
  const response = await fetch("/auth/token/refresh", {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
    },
  });

  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String(payload.detail)
        : "인증이 필요합니다.";
    throw new ApiError(response.status, detail);
  }

  if (
    typeof payload !== "object" ||
    payload === null ||
    !("access_token" in payload) ||
    typeof payload.access_token !== "string"
  ) {
    throw new ApiError(500, "토큰 발급에 실패했습니다.");
  }

  return payload.access_token;
}

async function shuttleRequest<T>(
  path: string,
  options: RequestOptions = {},
  retry = true,
): Promise<T> {
  const token = await requestShuttleAccessToken();
  const headers = new Headers(options.headers);
  const { body, ...rest } = options;

  headers.set("Accept", "application/json");
  headers.set("Authorization", `Bearer ${token}`);

  const requestInit: RequestInit = {
    ...rest,
    credentials: "include",
    headers,
  };

  if (body !== undefined) {
    if (
      typeof body === "string" ||
      body instanceof FormData ||
      body instanceof Blob
    ) {
      requestInit.body = body;
    } else {
      headers.set("Content-Type", "application/json");
      requestInit.body = JSON.stringify(body);
    }
  }

  const response = await fetch(`${SHUTTLE_API_BASE}${path}`, requestInit);

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    if (response.status === 401 && retry) {
      return shuttleRequest<T>(path, options, false);
    }

    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String(payload.detail)
        : "요청 처리에 실패했습니다.";
    throw new ApiError(response.status, detail);
  }

  return payload as T;
}

export function getShuttleRoutes() {
  return shuttleRequest<ShuttleRoute[]>("/routes");
}

export function getShuttleStations() {
  return shuttleRequest<ShuttleStation[]>("/stations");
}

export function getShuttleScheduleTypes() {
  return shuttleRequest<ShuttleScheduleType[]>("/schedule-types");
}

export function getShuttleSchedules(routeId: number, scheduleType: string) {
  return shuttleRequest<ShuttleSchedule[]>(
    `/schedules?route_id=${routeId}&schedule_type=${encodeURIComponent(scheduleType)}`,
  );
}

export function getShuttleScheduleStops(scheduleId: number) {
  return shuttleRequest<ShuttleScheduleStop[]>(`/schedules/${scheduleId}/stops`);
}

export function createShuttleSchedule(payload: ShuttleSchedulePayload) {
  return shuttleRequest<ShuttleMutationResponse>("/admin/schedules", {
    method: "POST",
    body: payload,
  });
}

export function updateShuttleSchedule(scheduleId: number, payload: ShuttleSchedulePayload) {
  return shuttleRequest<ShuttleMutationResponse>(`/admin/schedules/${scheduleId}`, {
    method: "PUT",
    body: payload,
  });
}

export function deleteShuttleSchedule(scheduleId: number) {
  return shuttleRequest<ShuttleMutationResponse>(`/admin/schedules/${scheduleId}`, {
    method: "DELETE",
  });
}

export function createShuttleScheduleType(payload: ShuttleScheduleTypePayload) {
  return shuttleRequest<ShuttleScheduleType>("/admin/schedule-types", {
    method: "POST",
    body: payload,
  });
}

export function updateShuttleScheduleType(
  scheduleType: string,
  payload: ShuttleScheduleTypeUpdatePayload,
) {
  return shuttleRequest<ShuttleScheduleType>(
    `/admin/schedule-types/${encodeURIComponent(scheduleType)}`,
    {
      method: "PUT",
      body: payload,
    },
  );
}

export function deleteShuttleScheduleType(scheduleType: string) {
  return shuttleRequest<ShuttleMutationResponse>(
    `/admin/schedule-types/${encodeURIComponent(scheduleType)}`,
    {
      method: "DELETE",
    },
  );
}

export function getShuttleScheduleExceptions() {
  return shuttleRequest<ShuttleScheduleException[]>("/schedule-exceptions");
}

export function createShuttleScheduleException(payload: ShuttleScheduleExceptionPayload) {
  return shuttleRequest<ShuttleScheduleException>("/admin/schedule-exceptions", {
    method: "POST",
    body: payload,
  });
}

export function updateShuttleScheduleException(
  exceptionId: number,
  payload: ShuttleScheduleExceptionPayload,
) {
  return shuttleRequest<ShuttleScheduleException>(
    `/admin/schedule-exceptions/${exceptionId}`,
    {
      method: "PUT",
      body: payload,
    },
  );
}

export function deleteShuttleScheduleException(exceptionId: number) {
  return shuttleRequest<ShuttleMutationResponse>(`/admin/schedule-exceptions/${exceptionId}`, {
    method: "DELETE",
  });
}

export function clearShuttleCache() {
  return shuttleRequest<ShuttleCacheResponse>("/admin/clear-cache", {
    method: "POST",
  });
}
