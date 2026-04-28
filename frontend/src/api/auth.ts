import { apiClient } from "./client";

export interface AuthPayload {
  access: string;
  refresh: string;
  username: string;
  email: string;
}

export interface RefreshAccessResponse {
  access: string;
}

export interface SignupInput {
  username: string;
  email: string;
  password: string;
}

export interface LoginInput {
  username: string;
  password: string;
}

export interface PasswordResetRequestInput {
  email: string;
}

export interface PasswordResetConfirmInput {
  uid: string;
  token: string;
  new_password: string;
}

export async function signup(payload: SignupInput): Promise<AuthPayload> {
  const response = await apiClient.post<AuthPayload>("/auth/signup", payload);
  return response.data;
}

export async function login(payload: LoginInput): Promise<AuthPayload> {
  const response = await apiClient.post<AuthPayload>("/auth/login", payload);
  return response.data;
}

export async function refreshAccessToken(refreshToken: string): Promise<RefreshAccessResponse> {
  const response = await apiClient.post<RefreshAccessResponse>("/auth/token/refresh", { refresh: refreshToken });
  return response.data;
}

export async function requestPasswordReset(payload: PasswordResetRequestInput): Promise<{
  message: string;
}> {
  const response = await apiClient.post<{ message: string }>("/auth/password-reset/request", payload);
  return response.data;
}

export async function confirmPasswordReset(payload: PasswordResetConfirmInput): Promise<{
  message: string;
}> {
  const response = await apiClient.post<{ message: string }>("/auth/password-reset/confirm", payload);
  return response.data;
}
