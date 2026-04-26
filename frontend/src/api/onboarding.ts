import { apiClient } from "./client";

export interface OnboardingPayload {
  interests: string[];
  location?: string;
}

export async function submitOnboardingInterests(payload: OnboardingPayload): Promise<unknown> {
  const response = await apiClient.post("/onboarding/interests", payload);
  return response.data;
}
