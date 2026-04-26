import axios from "axios";
import { API_BASE_URL, apiClient } from "./client";

export interface InstallStatus {
  installed: boolean;
  installed_at: string | null;
  seed_requested: boolean;
  seed_status: string;
  seed_task_id: string;
  seed_total_users: number;
  seed_total_posts: number;
  seed_created_users: number;
  seed_created_posts: number;
  seed_last_message: string;
}

export interface InstallRunInput {
  username: string;
  email: string;
  password: string;
  display_name?: string;
  location?: string;
  seed_demo_data?: boolean;
}

export interface InstallRunResult {
  auth: {
    access: string;
    refresh: string;
    username: string;
    email: string;
  };
  seed_requested: boolean;
  seed_status: string;
  seed_task_id: string;
}

export interface DemoDataResetResult {
  removed_users: number;
  removed_posts: number;
  seed_status: string;
  seed_task_id: string;
}

export async function fetchInstallStatus(): Promise<InstallStatus> {
  const response = await axios.get<InstallStatus>(`${API_BASE_URL}/install/status`, {
    params: { t: Date.now() },
  });
  return response.data;
}

export async function runInstall(payload: InstallRunInput): Promise<InstallRunResult> {
  const response = await apiClient.post<InstallRunResult>("/install/run", payload);
  return response.data;
}

export async function resetDemoData(): Promise<DemoDataResetResult> {
  const response = await apiClient.post<DemoDataResetResult>("/install/demo-data/reset", {});
  return response.data;
}
