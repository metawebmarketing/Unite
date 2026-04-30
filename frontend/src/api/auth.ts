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
  date_of_birth: string;
  gender: "prefer_not_to_say" | "male" | "female" | "non_binary" | "self_describe";
  gender_self_describe?: string;
  zip_code: string;
  country: string;
  invite_token?: string;
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

export interface SiteSettingsPayload {
  register_via_invite_only: boolean;
  allowed_signup_countries: string[];
  site_name: string;
  support_email: string;
  frontend_base_url: string;
  default_from_email: string;
  email_backend: string;
  email_host: string;
  email_port: number | null;
  email_host_user: string;
  email_host_password?: string;
  has_email_host_password?: boolean;
  email_use_tls: boolean | null;
  email_use_ssl: boolean | null;
  email_timeout_seconds: number | null;
  enforce_signup_ip_country_match: boolean | null;
  allow_signup_on_ip_country_lookup_failure: boolean | null;
  ip_country_lookup_timeout_seconds: number | null;
  ip_country_lookup_url_template: string;
  updated_at: string;
}

export async function fetchSiteSettings(): Promise<SiteSettingsPayload> {
  const response = await apiClient.get<SiteSettingsPayload>("/auth/site-settings");
  return response.data;
}

export async function updateSiteSettings(payload: Partial<SiteSettingsPayload>): Promise<SiteSettingsPayload> {
  const response = await apiClient.patch<SiteSettingsPayload>("/auth/site-settings", payload);
  return response.data;
}

export async function sendSignupInvite(payload: { email: string }): Promise<{ message: string; invite_expires_at: string }> {
  const response = await apiClient.post<{ message: string; invite_expires_at: string }>(
    "/auth/site-settings/send-invite",
    payload,
  );
  return response.data;
}

export interface PublicSignupConfigPayload {
  register_via_invite_only: boolean;
  allowed_signup_countries: string[];
}

export async function fetchPublicSignupConfig(): Promise<PublicSignupConfigPayload> {
  const response = await apiClient.get<PublicSignupConfigPayload>("/auth/signup-config");
  return response.data;
}

export interface InviteTokenValidationPayload {
  is_valid: boolean;
  invited_email: string;
}

export async function validateSignupInviteToken(token: string): Promise<InviteTokenValidationPayload> {
  const response = await apiClient.get<InviteTokenValidationPayload>("/auth/signup-invite/validate", {
    params: { token },
  });
  return response.data;
}
