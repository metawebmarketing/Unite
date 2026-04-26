import { apiClient } from "./client";

export interface AiAuditRecord {
  id: number;
  user_id: number;
  action_name: string;
  endpoint: string;
  method: string;
  status_code: number | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AiAuditQuery {
  user_id?: number;
  action_name?: string;
  method?: string;
  status_code?: number;
  limit?: number;
}

export async function fetchAiAuditRecords(query: AiAuditQuery = {}): Promise<AiAuditRecord[]> {
  const response = await apiClient.get<AiAuditRecord[]>("/ai/audit", {
    params: {
      user_id: query.user_id || undefined,
      action_name: query.action_name || undefined,
      method: query.method || undefined,
      status_code: query.status_code || undefined,
      limit: query.limit || undefined,
    },
  });
  return response.data;
}
