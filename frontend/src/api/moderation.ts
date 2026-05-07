import { apiClient } from "./client";

export interface ModerationFlagRecord {
  id: number;
  profile_id: number | null;
  reporter_user_id: number | null;
  target_user_id: number | null;
  content_type: string;
  content_id: number | null;
  status: "pending" | "approved" | "denied";
  apply_penalty: boolean;
  reviewed_by_user_id: number | null;
  reviewed_at: string | null;
  review_note: string;
  category: string;
  reason: string;
  payload: Record<string, unknown>;
  policy_region: string;
  policy_version: string;
  created_at: string;
}

export interface ModerationDecisionInput {
  decision: "approved" | "denied";
  apply_penalty: boolean;
  report_outcome?: "valid_report" | "false_report";
  review_note?: string;
}

export interface ModerationAccountRecord {
  user_id: number;
  username: string;
  email: string;
  is_staff: boolean;
  is_active: boolean;
  is_banned: boolean;
  banned_at: string | null;
  banned_reason: string;
  active_penalty_count: number;
}

export interface ModerationAccountPage {
  count: number;
  page: number;
  page_size: number;
  results: ModerationAccountRecord[];
}

export interface ModerationPenaltyRecord {
  id: number;
  user_id: number;
  reason_type: "content_violation" | "false_report";
  source_flag_id: number | null;
  points: number;
  active: boolean;
  expires_at: string;
  removed_by_user_id: number | null;
  removed_at: string | null;
  removed_reason: string;
  created_at: string;
}

export async function listModerationFlags(params: {
  status?: string;
  category?: string;
  query?: string;
  limit?: number;
} = {}): Promise<ModerationFlagRecord[]> {
  const response = await apiClient.get<ModerationFlagRecord[]>("/moderation/flags", { params });
  return response.data;
}

export async function decideModerationFlag(
  flagId: number,
  payload: ModerationDecisionInput,
): Promise<ModerationFlagRecord> {
  const response = await apiClient.post<ModerationFlagRecord>(`/moderation/flags/${flagId}/decision`, payload);
  return response.data;
}

export async function searchModerationAccounts(params: {
  query?: string;
  page?: number;
  page_size?: number;
  sort_by?: "user_id" | "username" | "email" | "active_penalty_count" | "is_banned" | "banned_at";
  sort_dir?: "asc" | "desc";
}): Promise<ModerationAccountPage> {
  const response = await apiClient.get<ModerationAccountPage>("/moderation/accounts", {
    params: {
      query: String(params.query || "").trim(),
      page: params.page || 1,
      page_size: params.page_size || 25,
      sort_by: params.sort_by || "active_penalty_count",
      sort_dir: params.sort_dir || "desc",
    },
  });
  return response.data;
}

export async function listModerationPenalties(userId: number): Promise<ModerationPenaltyRecord[]> {
  const response = await apiClient.get<ModerationPenaltyRecord[]>(`/moderation/accounts/${userId}/penalties`);
  return response.data;
}

export async function removeModerationPenalty(penaltyId: number, removeReason = ""): Promise<ModerationPenaltyRecord> {
  const response = await apiClient.post<ModerationPenaltyRecord>(`/moderation/penalties/${penaltyId}/remove`, {
    remove_reason: removeReason,
  });
  return response.data;
}

export async function clearModerationPenalties(userId: number, removeReason = ""): Promise<{ cleared_count: number }> {
  const response = await apiClient.post<{ cleared_count: number }>(`/moderation/accounts/${userId}/penalties/clear`, {
    remove_reason: removeReason,
  });
  return response.data;
}

export async function banModerationAccount(userId: number, reason = ""): Promise<{ user_id: number; is_banned: boolean }> {
  const response = await apiClient.post<{ user_id: number; is_banned: boolean }>(`/moderation/accounts/${userId}/ban`, {
    reason,
  });
  return response.data;
}

export async function unbanModerationAccount(userId: number): Promise<{ user_id: number; is_banned: boolean }> {
  const response = await apiClient.post<{ user_id: number; is_banned: boolean }>(`/moderation/accounts/${userId}/unban`);
  return response.data;
}
