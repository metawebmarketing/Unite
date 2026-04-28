import { apiClient } from "./client";

export interface NotificationRecord {
  id: number;
  recipient_id: number;
  actor_user_id: number | null;
  event_type: string;
  title: string;
  message: string;
  payload: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationRecord[];
  unread_count: number;
  next_cursor: string | null;
  has_more: boolean;
}

export async function fetchNotifications(params?: { cursor?: string | null; pageSize?: number }) {
  const response = await apiClient.get<NotificationListResponse>("/notifications/", {
    params: {
      cursor: params?.cursor || undefined,
      page_size: params?.pageSize || 30,
    },
  });
  return response.data;
}

export async function markAllNotificationsRead() {
  const response = await apiClient.post<{ unread_count: number }>("/notifications/mark-all-read");
  return response.data;
}
