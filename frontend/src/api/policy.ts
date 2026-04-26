import { apiClient } from "./client";

export interface PolicyPack {
  id: number;
  region_code: string;
  version: string;
  prohibited_categories: string[];
  enabled: boolean;
  rollout_percentage: number;
  effective_from: string;
  effective_to: string | null;
  notes: string;
}

export interface PolicyResolveResponse {
  region_code: string;
  version: string;
  prohibited_categories: string[];
  rollout_percentage: number;
  source: string;
}

export async function listPolicyPacks(regionCode = "global"): Promise<PolicyPack[]> {
  const response = await apiClient.get<PolicyPack[]>("/policy/packs", {
    params: { region_code: regionCode },
  });
  return response.data;
}

export async function createPolicyPack(payload: Partial<PolicyPack>): Promise<PolicyPack> {
  const response = await apiClient.post<PolicyPack>("/policy/packs", payload);
  return response.data;
}

export async function resolvePolicy(
  regionCode: string,
  userKey: string,
): Promise<PolicyResolveResponse> {
  const response = await apiClient.post<PolicyResolveResponse>("/policy/resolve", {
    region_code: regionCode,
    user_key: userKey,
  });
  return response.data;
}
