import { apiClient } from "./client";

export interface Profile {
  display_name: string;
  bio: string;
  location: string;
  interests: string[];
  is_ai_account: boolean;
  ai_badge_enabled: boolean;
  is_staff: boolean;
  profile_image_url: string;
  algorithm_profile_status: string;
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
