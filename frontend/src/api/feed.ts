import { apiClient } from "./client";

export interface FeedItem {
  item_type: "post" | "suggestion" | "ad";
  source_module: string;
  injection_reason: string;
  data: {
    id?: number;
    author_id?: number;
    author_username?: string;
    author_display_name?: string;
    author_profile_image_url?: string;
    author_is_ai?: boolean;
    author_ai_badge_enabled?: boolean;
    content?: string;
    created_at?: string;
    link_preview?: {
      url: string;
      host: string;
      title: string;
      description: string;
    };
    rank_score?: number;
    has_liked?: boolean;
    has_bookmarked?: boolean;
    is_pinned?: boolean;
    interaction_counts?: {
      like: number;
      reply: number;
      repost: number;
      quote: number;
    };
    user_id?: number;
    username?: string;
    bio?: string;
    profile_image_url?: string;
    is_ai_account?: boolean;
    ai_badge_enabled?: boolean;
    suggestion_posts_preview?: Array<{ id: number; content: string }>;
    title?: string;
    [key: string]: unknown;
  };
}

export interface FeedConfig {
  suggestion_interval: number;
  ad_interval: number;
  suggestions_enabled: boolean;
  ads_enabled: boolean;
  max_injection_ratio: number;
}

export interface FeedPage {
  items: FeedItem[];
  next_cursor: string | null;
  has_more: boolean;
  organic_count: number;
}

export async function fetchFeed(
  mode: "connections" | "suggestions" | "both" | "interest",
  cursor: string | null = null,
  interestTag: string | null = null,
  fields: string[] | null = null,
): Promise<FeedPage> {
  const normalizedFields =
    fields && fields.length > 0 ? fields.map((value) => value.trim()).filter(Boolean).join(",") : undefined;
  const response = await apiClient.get<FeedPage>("/feed/", {
    params: {
      mode,
      cursor,
      interest_tag: interestTag || undefined,
      fields: normalizedFields,
    },
  });
  return response.data;
}

export async function fetchFeedConfig(): Promise<FeedConfig> {
  const response = await apiClient.get<FeedConfig>("/feed/config");
  return response.data;
}
