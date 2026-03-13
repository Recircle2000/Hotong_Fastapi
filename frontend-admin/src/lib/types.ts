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
