import axios from "axios";

import { API_BASE_URL, apiClient } from "./client";

export interface ActiveTheme {
  id: number;
  name: string;
  version: string;
  tokens: Record<string, unknown>;
  is_active: boolean;
}

export async function fetchActiveTheme(): Promise<ActiveTheme | null> {
  try {
    const response = await axios.get<ActiveTheme>(`${API_BASE_URL}/themes/active`);
    return response.data;
  } catch {
    return null;
  }
}

export interface ThemeUploadPayload {
  name: string;
  version: string;
  tokens: Record<string, unknown>;
}

export async function uploadTheme(payload: ThemeUploadPayload): Promise<ActiveTheme> {
  const response = await apiClient.post<ActiveTheme>("/themes/upload", payload);
  return response.data;
}
