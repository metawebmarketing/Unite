import { API_BASE_URL, getAuthToken } from "../api/client";
import type { CreatePostInput, ReactPostInput } from "../api/posts";
import { sendSyncReplayEvent } from "../api/posts";
import { enqueueQueuedAction, getQueuedActions, removeQueuedAction } from "./queue-db";

async function registerBackgroundSync(): Promise<void> {
  if (!("serviceWorker" in navigator)) {
    return;
  }
  const registration = await navigator.serviceWorker.ready;
  const syncManager = (registration as ServiceWorkerRegistration & {
    sync?: { register: (tag: string) => Promise<void> };
  }).sync;
  if (syncManager) {
    await syncManager.register("unite-sync-queue");
  }
  registration.active?.postMessage({ type: "QUEUE_UPDATED" });
}

function buildAuthHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function buildIdempotencyKey(prefix: string): string {
  if ("crypto" in globalThis && "randomUUID" in crypto) {
    return `${prefix}:${crypto.randomUUID()}`;
  }
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

export async function enqueueCreatePost(payload: CreatePostInput): Promise<void> {
  const idemKey = buildIdempotencyKey("create-post");
  await enqueueQueuedAction({
    kind: "create_post",
    method: "POST",
    url: `${API_BASE_URL}/posts/`,
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idemKey,
      ...buildAuthHeaders(),
    },
    queuedAt: Date.now(),
  });
  await registerBackgroundSync();
}

export async function enqueueReactPost(postId: number, body: ReactPostInput): Promise<void> {
  const idemKey = buildIdempotencyKey(`react-${postId}-${body.action}`);
  await enqueueQueuedAction({
    kind: "react_post",
    method: "POST",
    url: `${API_BASE_URL}/posts/${postId}/react`,
    body: JSON.stringify(body),
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idemKey,
      ...buildAuthHeaders(),
    },
    conflictKey: `react:${postId}:${body.action}`,
    queuedAt: Date.now(),
  });
  await registerBackgroundSync();
}

export async function flushOfflineQueue(): Promise<void> {
  const actions = await getQueuedActions();
  for (const action of actions) {
    if (typeof action.id !== "number") {
      continue;
    }
    try {
      const response = await fetch(action.url, {
        method: action.method,
        headers: action.headers,
        body: action.body,
      });
      // Drop invalid/conflicting requests; keep transient failures for retry.
      if (response.ok || [400, 409, 422].includes(response.status)) {
        await sendSyncReplayEvent({
          source: "client",
          kind: action.kind,
          endpoint: action.url,
          outcome: response.ok ? "success" : "dropped",
          status_code: response.status,
          idempotency_key: action.headers["Idempotency-Key"] || action.headers["idempotency-key"] || "",
        });
        await removeQueuedAction(action.id);
      } else {
        await sendSyncReplayEvent({
          source: "client",
          kind: action.kind,
          endpoint: action.url,
          outcome: "retry",
          status_code: response.status,
          idempotency_key: action.headers["Idempotency-Key"] || action.headers["idempotency-key"] || "",
        });
      }
    } catch {
      // network failure, keep queued
      await sendSyncReplayEvent({
        source: "client",
        kind: action.kind,
        endpoint: action.url,
        outcome: "retry",
        idempotency_key: action.headers["Idempotency-Key"] || action.headers["idempotency-key"] || "",
        detail: "network_failure",
      }).catch(() => undefined);
    }
  }
}
