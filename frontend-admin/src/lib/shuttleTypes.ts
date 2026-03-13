export interface ShuttleRoute {
  id: number;
  route_name: string;
  direction: string;
}

export interface ShuttleStation {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  description: string | null;
  image_url: string | null;
}

export interface ShuttleScheduleType {
  schedule_type: string;
  schedule_type_name: string;
  is_activate: boolean;
}

export interface ShuttleSchedule {
  id: number;
  route_id: number;
  schedule_type: string;
  start_time: string;
  end_time: string;
}

export interface ShuttleScheduleStop {
  station_id: number;
  arrival_time: string;
  stop_order: number;
  station_name: string;
}

export interface ShuttleScheduleStopPayload {
  station_id: number;
  arrival_time: string;
  stop_order: number;
}

export interface ShuttleSchedulePayload {
  route_id: number;
  schedule_type: string;
  start_time: string;
  end_time: string;
  stops: ShuttleScheduleStopPayload[];
}

export interface ShuttleScheduleTypePayload {
  schedule_type: string;
  schedule_type_name: string;
  is_activate: boolean;
}

export interface ShuttleScheduleTypeUpdatePayload {
  schedule_type_name: string;
  is_activate: boolean;
}

export interface ShuttleScheduleException {
  id: number;
  start_date: string;
  end_date: string;
  schedule_type: string;
  reason: string | null;
  schedule_type_name: string | null;
  is_activate: boolean;
  include_weekday: boolean;
  include_weekday_friday: boolean;
  include_saturday: boolean;
  include_sunday: boolean;
  include_holiday: boolean;
}

export interface ShuttleScheduleExceptionPayload {
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
}

export interface ShuttleMutationResponse {
  id?: number;
  message: string;
}

export interface ShuttleCacheResponse {
  message: string;
  success?: boolean;
}
