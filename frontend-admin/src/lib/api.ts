import type {
  AdminShuttleStation,
  AdminShuttleStationPayload,
  EmergencyNotice,
  EmergencyNoticePayload,
  Notice,
  NoticePayload,
  SessionResponse,
} from "./types";

const API_BASE = "/api/admin-v2";

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: BodyInit | object;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const { body, ...rest } = options;
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

  headers.set("Accept", "application/json");

  const response = await fetch(`${API_BASE}${path}`, requestInit);
  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String(payload.detail)
        : "요청을 처리하지 못했습니다.";
    throw new ApiError(response.status, detail);
  }

  return payload as T;
}

export function loginAdmin(payload: { email: string; password: string }) {
  return apiRequest<SessionResponse>("/auth/login", {
    method: "POST",
    body: payload,
  });
}

export function logoutAdmin() {
  return apiRequest<void>("/auth/logout", {
    method: "POST",
  });
}

export function getSession() {
  return apiRequest<SessionResponse>("/auth/session");
}

export function getNotices() {
  return apiRequest<Notice[]>("/notices");
}

export function createNotice(payload: NoticePayload) {
  return apiRequest<Notice>("/notices", {
    method: "POST",
    body: payload,
  });
}

export function updateNotice(id: number, payload: NoticePayload) {
  return apiRequest<Notice>(`/notices/${id}`, {
    method: "PUT",
    body: payload,
  });
}

export function deleteNotice(id: number) {
  return apiRequest<void>(`/notices/${id}`, {
    method: "DELETE",
  });
}

export function getEmergencyNotices() {
  return apiRequest<EmergencyNotice[]>("/emergency-notices");
}

export function createEmergencyNotice(payload: EmergencyNoticePayload) {
  return apiRequest<EmergencyNotice>("/emergency-notices", {
    method: "POST",
    body: payload,
  });
}

export function updateEmergencyNotice(id: number, payload: EmergencyNoticePayload) {
  return apiRequest<EmergencyNotice>(`/emergency-notices/${id}`, {
    method: "PUT",
    body: payload,
  });
}

export function deleteEmergencyNotice(id: number) {
  return apiRequest<void>(`/emergency-notices/${id}`, {
    method: "DELETE",
  });
}

export function getAdminShuttleStations() {
  return apiRequest<AdminShuttleStation[]>("/shuttle-stations");
}

export function createAdminShuttleStation(payload: AdminShuttleStationPayload) {
  return apiRequest<AdminShuttleStation>("/shuttle-stations", {
    method: "POST",
    body: payload,
  });
}

export function updateAdminShuttleStation(
  id: number,
  payload: AdminShuttleStationPayload,
) {
  return apiRequest<AdminShuttleStation>(`/shuttle-stations/${id}`, {
    method: "PUT",
    body: payload,
  });
}

export function deleteAdminShuttleStation(id: number) {
  return apiRequest<void>(`/shuttle-stations/${id}`, {
    method: "DELETE",
  });
}
