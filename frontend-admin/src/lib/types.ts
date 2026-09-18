export type NoticeType = "App" | "update" | "shuttle" | "citybus";

export interface SessionUser {
  id: number;
  email: string;
  is_admin: boolean;
}

export interface SessionResponse {
  authenticated: boolean;
  user: SessionUser;
}

export interface Notice {
  id: number;
  title: string;
  content: string;
  notice_type: NoticeType;
  is_pinned: boolean;
  created_at: string | null;
}

export interface NoticePayload {
  title: string;
  content: string;
  notice_type: NoticeType;
  is_pinned: boolean;
}

export type EmergencyNoticeCategory =
  | "shuttle"
  | "asan_citybus"
  | "cheonan_citybus"
  | "subway";

export type EmergencyNoticeStatus = "pending" | "active" | "expired";

export interface EmergencyNotice {
  id: number;
  category: EmergencyNoticeCategory;
  category_label: string;
  title: string;
  content: string;
  created_at: string;
  end_at: string;
  status: EmergencyNoticeStatus;
}

export interface EmergencyNoticePayload {
  category: EmergencyNoticeCategory;
  title: string;
  content: string;
  created_at: string;
  end_at: string;
}

export interface AdminShuttleStation {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  description: string | null;
  image_url: string | null;
  is_active: boolean;
}

export interface AdminShuttleStationPayload {
  name: string;
  latitude: number;
  longitude: number;
  description: string | null;
  image_url: string | null;
  is_active: boolean;
}

export type TaxiLocationCategory = "campus" | "station" | "terminal" | "other";

export interface AdminTaxiLocation {
  id: number;
  name: string;
  category: TaxiLocationCategory;
  sort_order: number;
  is_active: boolean;
}

export interface AdminTaxiLocationPayload {
  name: string;
  category: TaxiLocationCategory;
  sort_order: number;
  is_active: boolean;
}

export interface AdminTaxiParty {
  id: string;
  departure_location_name: string;
  destination_location_name: string;
  departure_summary: string;
  destination_summary: string | null;
  departure_at: string;
  current_members: number;
  max_members: number;
  status: string;
  cancellation_reason: string | null;
  created_at: string;
}

export interface AdminTaxiPartyList {
  items: AdminTaxiParty[];
  next_cursor: string | null;
}
