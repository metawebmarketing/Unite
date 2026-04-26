import { apiClient } from "./client";

export interface AdEventPayload {
  event_type: "impression" | "click";
  ad_event_key: string;
  placement?: string;
  region_code?: string;
  metadata?: Record<string, unknown>;
}

export async function sendAdEvent(payload: AdEventPayload): Promise<void> {
  await apiClient.post("/ads/events", payload);
}

export interface AdSlotConfig {
  id: number;
  region_code: string;
  campaign_key: string;
  experiment_key: string;
  interval: number;
  enabled: boolean;
  account_tier_target: "any" | "human" | "ai";
  target_interest_tags: string[];
  updated_at: string;
}

export interface AdMetrics {
  impressions: number;
  clicks: number;
  ctr: number;
  by_region: Record<string, { impressions: number; clicks: number }>;
  by_campaign: Record<string, { impressions: number; clicks: number }>;
}

export async function listAdConfigs(region = ""): Promise<AdSlotConfig[]> {
  const response = await apiClient.get<AdSlotConfig[]>("/ads/configs", {
    params: { region: region || undefined },
  });
  return response.data;
}

export async function createAdConfig(payload: {
  region_code: string;
  campaign_key?: string;
  experiment_key?: string;
  interval: number;
  enabled: boolean;
  account_tier_target?: "any" | "human" | "ai";
  target_interest_tags?: string[];
}): Promise<AdSlotConfig> {
  const response = await apiClient.post<AdSlotConfig>("/ads/configs", payload);
  return response.data;
}

export async function updateAdConfig(
  configId: number,
  payload: Partial<
    Pick<
      AdSlotConfig,
      | "region_code"
      | "campaign_key"
      | "experiment_key"
      | "interval"
      | "enabled"
      | "account_tier_target"
      | "target_interest_tags"
    >
  >,
): Promise<AdSlotConfig> {
  const response = await apiClient.patch<AdSlotConfig>(`/ads/configs/${configId}`, payload);
  return response.data;
}

export async function fetchAdMetrics(region = "", campaign = ""): Promise<AdMetrics> {
  const response = await apiClient.get<AdMetrics>("/ads/metrics", {
    params: { region: region || undefined, campaign: campaign || undefined },
  });
  return response.data;
}
