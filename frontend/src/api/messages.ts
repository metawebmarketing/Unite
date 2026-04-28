import { apiClient } from "./client";

export interface DMThreadListItem {
  thread_id: number;
  other_user_id: number;
  other_username: string;
  other_display_name: string;
  other_profile_image_url: string;
  latest_message_preview: string;
  latest_message_at: string;
  updated_at: string;
  unread_count: number;
}

export interface DMThreadListPage {
  items: DMThreadListItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface DMUserSuggestion {
  user_id: number;
  username: string;
  display_name: string;
  profile_image_url: string;
  is_connected: boolean;
  rank_overall_score: number;
}

export interface DMMessageRecord {
  id: number;
  thread_id: number;
  sender_id: number;
  content: string;
  attachments: Array<{ media_type: "image" | "video"; media_url: string }>;
  link_preview?: {
    url?: string;
    host?: string;
    title?: string;
    description?: string;
  };
  created_at: string;
  status: "sent" | "read";
}

export interface DMMessageListPage {
  items: DMMessageRecord[];
  next_cursor: string | null;
  has_more: boolean;
  thread_id: number;
}

export interface CreateDMThreadInput {
  recipient_id: number;
}

export interface CreateDMThreadResponse {
  thread_id: number;
  created: boolean;
}

export interface CreateDMMessageInput {
  content?: string;
  link_url?: string;
  attachments?: Array<{ media_type: "image" | "video"; media_url: string }>;
}

export async function fetchDMThreads(options: {
  cursor?: string | null;
  search?: string;
  afterDate?: string;
  beforeDate?: string;
  fromProfile?: string;
  pageSize?: number;
} = {}): Promise<DMThreadListPage> {
  const response = await apiClient.get<DMThreadListPage>("/messages/threads", {
    params: {
      cursor: options.cursor || undefined,
      search: options.search || undefined,
      after_date: options.afterDate || undefined,
      before_date: options.beforeDate || undefined,
      from_profile: options.fromProfile || undefined,
      page_size: options.pageSize || undefined,
    },
  });
  return response.data;
}

export async function createDMThread(payload: CreateDMThreadInput): Promise<CreateDMThreadResponse> {
  const response = await apiClient.post<CreateDMThreadResponse>("/messages/threads", payload);
  return response.data;
}

export async function fetchDMUserSuggestions(query: string, limit = 50): Promise<DMUserSuggestion[]> {
  const response = await apiClient.get<{ items: DMUserSuggestion[] }>("/messages/user-suggestions", {
    params: {
      query: query.trim(),
      limit,
    },
  });
  return response.data.items;
}

export async function fetchDMThreadUserSuggestions(query: string, limit = 50): Promise<DMUserSuggestion[]> {
  const response = await apiClient.get<{ items: DMUserSuggestion[] }>("/messages/thread-user-suggestions", {
    params: {
      query: query.trim(),
      limit,
    },
  });
  return response.data.items;
}

export async function fetchThreadMessages(
  threadId: number,
  options: { cursor?: string | null; pageSize?: number } = {},
): Promise<DMMessageListPage> {
  const response = await apiClient.get<DMMessageListPage>(`/messages/threads/${threadId}/messages`, {
    params: {
      cursor: options.cursor || undefined,
      page_size: options.pageSize || undefined,
    },
  });
  return response.data;
}

export async function sendThreadMessage(
  threadId: number,
  payload: CreateDMMessageInput,
  options: { idempotencyKey?: string } = {},
): Promise<DMMessageRecord> {
  const response = await apiClient.post<DMMessageRecord>(`/messages/threads/${threadId}/messages`, payload, {
    headers: {
      "Idempotency-Key": options.idempotencyKey || undefined,
    },
  });
  return response.data;
}
