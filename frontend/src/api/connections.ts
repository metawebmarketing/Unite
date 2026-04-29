import { apiClient } from "./client";

export interface ConnectionRecord {
  id: number;
  requester: number;
  recipient: number;
  status: "pending" | "accepted" | "blocked";
  created_at: string;
  updated_at: string;
}

export interface ConnectionListItem {
  connection_id: number;
  user_id: number;
  username: string;
  display_name: string;
  profile_image_url: string;
  shared_interest_count: number;
  updated_at: string;
  is_connected?: boolean;
}

export interface ConnectionListPage {
  items: ConnectionListItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface ConnectionStatus {
  user_id: number;
  relationship_status: "self" | "none" | "connected" | "pending_outgoing" | "pending_incoming" | "blocked";
  is_connected: boolean;
  is_blocked: boolean;
  is_pending_outgoing: boolean;
  is_pending_incoming: boolean;
  requires_approval: boolean;
  common_connections: Array<{
    user_id: number;
    username: string;
    display_name: string;
    profile_image_url: string;
  }>;
  common_connection_count: number;
}

export async function connectToUser(userId: number): Promise<ConnectionRecord> {
  const response = await apiClient.post<ConnectionRecord>(`/connections/${userId}/connect`);
  return response.data;
}

export async function disconnectFromUser(userId: number): Promise<{ disconnected: boolean }> {
  const response = await apiClient.post<{ disconnected: boolean }>(`/connections/${userId}/disconnect`);
  return response.data;
}

export async function fetchConnectionStatus(userId: number): Promise<ConnectionStatus> {
  const response = await apiClient.get<ConnectionStatus>(`/connections/${userId}/status`);
  return response.data;
}

export async function fetchPendingConnections(): Promise<{ items: ConnectionListItem[] }> {
  const response = await apiClient.get<{ items: ConnectionListItem[] }>("/connections/pending");
  return response.data;
}

export async function approveConnection(userId: number): Promise<{ approved: boolean }> {
  const response = await apiClient.post<{ approved: boolean }>(`/connections/${userId}/approve`);
  return response.data;
}

export async function denyConnection(userId: number): Promise<{ denied: boolean }> {
  const response = await apiClient.post<{ denied: boolean }>(`/connections/${userId}/deny`);
  return response.data;
}

export async function blockUser(userId: number): Promise<ConnectionRecord> {
  const response = await apiClient.post<ConnectionRecord>(`/connections/${userId}/block`);
  return response.data;
}

export async function unblockUser(userId: number): Promise<{ unblocked: boolean }> {
  const response = await apiClient.post<{ unblocked: boolean }>(`/connections/${userId}/unblock`);
  return response.data;
}

export async function fetchConnections(
  userId: number | null,
  options: {
    cursor?: string | null;
    search?: string;
    afterDate?: string;
    beforeDate?: string;
    fromProfile?: string;
    pageSize?: number;
    scope?: "connections" | "users";
  } = {},
): Promise<ConnectionListPage> {
  const scope = options.scope || "connections";
  const endpoint = userId ? `/connections/users/${userId}` : scope === "users" ? "/connections/search" : "/connections/";
  const response = await apiClient.get<ConnectionListPage>(endpoint, {
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
