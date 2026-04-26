import axios from "axios";

export const API_BASE_URL = "http://localhost:8000/api/v1";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

export function setAuthToken(token: string | null): void {
  if (!token) {
    delete apiClient.defaults.headers.common.Authorization;
    return;
  }
  apiClient.defaults.headers.common.Authorization = `Bearer ${token}`;
}

export function getAuthToken(): string | null {
  const headerValue = apiClient.defaults.headers.common.Authorization;
  if (!headerValue || typeof headerValue !== "string") {
    return null;
  }
  return headerValue.replace(/^Bearer\s+/i, "").trim() || null;
}
