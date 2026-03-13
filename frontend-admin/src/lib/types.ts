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
