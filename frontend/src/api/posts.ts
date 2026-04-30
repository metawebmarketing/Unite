import { apiClient } from "./client";

export interface CreatePostInput {
  content: string;
  link_url?: string;
  interest_tags?: string[];
  tagged_user_ids?: number[];
  attachments?: Array<{ media_type: "image"; media_url: string }>;
}

export async function createPost(payload: CreatePostInput): Promise<unknown> {
  const response = await apiClient.post("/posts/", payload);
  return response.data;
}

export async function uploadPostImage(file: File): Promise<{ media_type: "image"; media_url: string }> {
  const payload = new FormData();
  payload.append("image", file);
  const response = await apiClient.post<{ media_type: "image"; media_url: string }>("/posts/upload-image", payload);
  return response.data;
}

export interface ReactPostInput {
  action: "like" | "reply" | "repost" | "quote" | "bookmark" | "report";
  content?: string;
  link_url?: string;
  tagged_user_ids?: number[];
  attachments?: Array<{ media_type: "image"; media_url: string }>;
}

export interface PostAuthorSummary {
  author_id: number;
  author_username: string;
  author_display_name: string;
  author_profile_image_url: string;
  author_profile_rank_score?: number;
  author_is_ai: boolean;
  author_ai_badge_enabled: boolean;
  author_is_connected?: boolean;
}

export interface PostRecord extends PostAuthorSummary {
  id: number;
  content: string;
  created_at: string;
  sentiment_label?: string;
  sentiment_score?: number;
  is_pinned?: boolean;
  link_preview?: {
    url: string;
    host: string;
    title: string;
    description: string;
    image_url?: string;
  };
  tagged_user_ids?: number[];
  attachments?: Array<{ media_type: "image"; media_url: string }>;
  has_liked: boolean;
  has_bookmarked?: boolean;
  interaction_counts: {
    like: number;
    reply: number;
    repost: number;
    quote: number;
  };
}

export interface PostDetailResponse {
  post: PostRecord;
  replies: PostRecord[];
}

export async function reactToPost(postId: number, payload: ReactPostInput): Promise<unknown> {
  const response = await apiClient.post(`/posts/${postId}/react`, payload);
  return response.data;
}

export async function fetchPostDetail(postId: number): Promise<PostDetailResponse> {
  const response = await apiClient.get<PostDetailResponse>(`/posts/${postId}`);
  return response.data;
}

export async function fetchPostsByUser(userId: number): Promise<PostRecord[]> {
  const response = await apiClient.get<PostRecord[]>(`/posts/user/${userId}`);
  return response.data;
}

export async function fetchBookmarkedPosts(): Promise<PostRecord[]> {
  const response = await apiClient.get<PostRecord[]>("/posts/bookmarks");
  return response.data;
}

export async function fetchPinnedPosts(): Promise<PostRecord[]> {
  const response = await apiClient.get<PostRecord[]>("/posts/pinned");
  return response.data;
}

export async function togglePostPin(postId: number): Promise<{ is_pinned: boolean }> {
  const response = await apiClient.post<{ is_pinned: boolean }>(`/posts/${postId}/pin`);
  return response.data;
}

export interface SyncMetrics {
  active_idempotency_records: number;
  replay_total: number;
  conflict_total: number;
  sync_events?: {
    success: number;
    dropped: number;
    retry: number;
  };
  latest_record_at: string | null;
}

export async function fetchSyncMetrics(): Promise<SyncMetrics> {
  const response = await apiClient.get<SyncMetrics>("/posts/sync/metrics");
  return response.data;
}

export interface SyncReplayEventPayload {
  source: "client" | "service_worker";
  kind: "create_post" | "react_post";
  endpoint: string;
  outcome: "success" | "dropped" | "retry";
  status_code?: number;
  idempotency_key?: string;
  detail?: string;
}

export async function sendSyncReplayEvent(payload: SyncReplayEventPayload): Promise<void> {
  await apiClient.post("/posts/sync/events", payload);
}
