import { apiClient } from "./client";

export interface TopInterest {
  tag: string;
  count: number;
}

export interface InterestPost {
  id: number;
  author_id: number;
  content: string;
  interest_tags: string[];
  created_at: string;
}

export interface InterestSuggestion {
  tag: string;
  count: number;
}

export async function fetchTopInterests(limit = 8): Promise<TopInterest[]> {
  const response = await apiClient.get<TopInterest[]>("/interests/top", {
    params: { limit },
  });
  return response.data;
}

export async function fetchTopInterestPosts(tag = "", limit = 10): Promise<InterestPost[]> {
  const response = await apiClient.get<InterestPost[]>("/interests/top-posts", {
    params: { tag, limit },
  });
  return response.data;
}

export async function fetchInterestSuggestions(
  selected: string[],
  query = "",
  limit = 8,
): Promise<InterestSuggestion[]> {
  const response = await apiClient.get<InterestSuggestion[]>("/interests/suggest", {
    params: {
      selected: selected.join(","),
      query: query || undefined,
      limit,
    },
  });
  return response.data;
}
