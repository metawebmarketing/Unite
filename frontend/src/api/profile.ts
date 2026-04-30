import { apiClient } from "./client";

export interface Profile {
  user_id: number;
  username: string;
  display_name: string;
  bio: string;
  location: string;
  profile_link_url: string;
  interests: string[];
  receive_notifications: boolean;
  receive_email_notifications: boolean;
  receive_push_notifications: boolean;
  is_private_profile: boolean;
  require_connection_approval: boolean;
  connection_count: number;
  is_ai_account: boolean;
  ai_badge_enabled: boolean;
  is_staff: boolean;
  profile_image_url: string;
  algorithm_profile_status: string;
  rank_overall_score?: number;
  rank_action_scores?: Record<string, { sum: number; count: number; avg: number }>;
  rank_last_500_count?: number;
  rank_provider?: string;
  date_of_birth?: string;
  gender?: string;
  gender_self_describe?: string;
  zip_code?: string;
  country?: string;
}

export interface PublicProfile extends Profile {
  is_limited_view?: boolean;
  can_view_feed?: boolean;
  is_blocked_view?: boolean;
}

export async function fetchProfile(): Promise<Profile> {
  const response = await apiClient.get<Profile>("/profile/");
  return response.data;
}

export async function updateProfile(payload: Partial<Profile>): Promise<Profile> {
  const response = await apiClient.patch<Profile>("/profile/", payload);
  return response.data;
}

export async function uploadProfileImage(payload: FormData): Promise<Profile> {
  const response = await apiClient.post<Profile>("/profile/image", payload, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
  return response.data;
}

export async function fetchPublicProfile(userId: number): Promise<PublicProfile> {
  const response = await apiClient.get<PublicProfile>(`/profile/users/${userId}`);
  return response.data;
}
