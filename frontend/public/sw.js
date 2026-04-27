const SHELL_CACHE = "unite-shell-v2";
const FEED_CACHE = "unite-feed-v2";
const SHELL_ASSETS = ["/", "/manifest.webmanifest", "/favicon.svg"];
const QUEUE_DB_NAME = "unite-offline-db";
const QUEUE_DB_VERSION = 1;
const QUEUE_STORE = "request_queue";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => ![SHELL_CACHE, FEED_CACHE].includes(key))
          .map((key) => caches.delete(key)),
      ),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const requestUrl = new URL(event.request.url);
  if (isMutableApiRequest(event.request, requestUrl)) {
    event.respondWith(handleMutableApiRequest(event.request));
    return;
  }
  if (requestUrl.pathname.startsWith("/api/v1/feed")) {
    event.respondWith(networkFirstWithCacheFallback(event.request, FEED_CACHE));
    return;
  }
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match("/")),
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request)),
  );
});

self.addEventListener("sync", (event) => {
  if (event.tag === "unite-sync-queue") {
    event.waitUntil(flushQueue());
  }
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "QUEUE_UPDATED") {
    event.waitUntil(registerSync());
  }
});

async function networkFirstWithCacheFallback(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }
    return new Response(
      JSON.stringify({ items: [], next_cursor: null, has_more: false, organic_count: 0 }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
}

function isMutableApiRequest(request, requestUrl) {
  if (!["POST", "PUT", "PATCH", "DELETE"].includes(request.method)) {
    return false;
  }
  if (requestUrl.pathname.endsWith("/api/v1/posts/sync/events")) {
    return false;
  }
  return requestUrl.href.includes("/api/v1/");
}

function buildConflictKey(requestUrl, bodyText) {
  if (requestUrl.href.includes("/api/v1/posts/") && requestUrl.href.endsWith("/react")) {
    try {
      const parsed = JSON.parse(bodyText || "{}");
      const postId = requestUrl.pathname.split("/").filter(Boolean).slice(-2)[0];
      return `react:${postId}:${parsed.action || "unknown"}`;
    } catch {
      return undefined;
    }
  }
  return undefined;
}

async function handleMutableApiRequest(request) {
  try {
    return await fetch(request.clone());
  } catch {
    const bodyText = await request.clone().text();
    await enqueueRequest({
      kind: request.url.includes("/react") ? "react_post" : "create_post",
      method: request.method,
      url: request.url,
      body: bodyText,
      headers: extractHeaders(request.headers),
      conflictKey: buildConflictKey(new URL(request.url), bodyText),
      queuedAt: Date.now(),
    });
    await registerSync();
    return new Response(JSON.stringify({ queued: true }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    });
  }
}

function extractHeaders(headers) {
  const allowed = ["authorization", "content-type", "idempotency-key"];
  const result = {};
  for (const [key, value] of headers.entries()) {
    if (allowed.includes(key.toLowerCase())) {
      result[key] = value;
    }
  }
  return result;
}

function openQueueDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(QUEUE_DB_NAME, QUEUE_DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(QUEUE_STORE)) {
        const store = db.createObjectStore(QUEUE_STORE, { keyPath: "id", autoIncrement: true });
        store.createIndex("by_conflict_key", "conflictKey", { unique: false });
        store.createIndex("by_queued_at", "queuedAt", { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function enqueueRequest(action) {
  if (!action.headers["Idempotency-Key"] && !action.headers["idempotency-key"]) {
    action.headers["Idempotency-Key"] = createIdempotencyKey(action.kind);
  }
  const db = await openQueueDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, "readwrite");
    const store = tx.objectStore(QUEUE_STORE);
    if (action.conflictKey) {
      const index = store.index("by_conflict_key");
      const request = index.getAll(action.conflictKey);
      request.onsuccess = () => {
        const existing = request.result || [];
        existing.forEach((item) => {
          if (typeof item.id === "number") {
            store.delete(item.id);
          }
        });
        store.add(action);
      };
      request.onerror = () => reject(request.error);
    } else {
      store.add(action);
    }
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

function createIdempotencyKey(prefix) {
  if (self.crypto && self.crypto.randomUUID) {
    return `${prefix}:${self.crypto.randomUUID()}`;
  }
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
}

async function readQueue() {
  const db = await openQueueDb();
  return await new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, "readonly");
    const request = tx.objectStore(QUEUE_STORE).getAll();
    request.onsuccess = () => {
      const items = request.result || [];
      items.sort((a, b) => a.queuedAt - b.queuedAt);
      resolve(items);
    };
    request.onerror = () => reject(request.error);
  });
}

async function deleteQueued(id) {
  const db = await openQueueDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, "readwrite");
    tx.objectStore(QUEUE_STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function flushQueue() {
  const queue = await readQueue();
  for (const item of queue) {
    try {
      const response = await fetch(item.url, {
        method: item.method,
        headers: item.headers,
        body: item.body,
      });
      if (response.ok || [400, 409, 422].includes(response.status)) {
        await sendSyncEvent({
          source: "service_worker",
          kind: item.kind,
          endpoint: item.url,
          outcome: response.ok ? "success" : "dropped",
          status_code: response.status,
          idempotency_key: item.headers["Idempotency-Key"] || item.headers["idempotency-key"] || "",
        }, item.headers);
        await deleteQueued(item.id);
      } else {
        await sendSyncEvent({
          source: "service_worker",
          kind: item.kind,
          endpoint: item.url,
          outcome: "retry",
          status_code: response.status,
          idempotency_key: item.headers["Idempotency-Key"] || item.headers["idempotency-key"] || "",
        }, item.headers);
      }
    } catch {
      // keep item for next retry
      await sendSyncEvent({
        source: "service_worker",
        kind: item.kind,
        endpoint: item.url,
        outcome: "retry",
        idempotency_key: item.headers["Idempotency-Key"] || item.headers["idempotency-key"] || "",
        detail: "network_failure",
      }, item.headers).catch(() => undefined);
    }
  }
}

async function registerSync() {
  const registration = await self.registration;
  if (registration.sync) {
    await registration.sync.register("unite-sync-queue");
  }
}

async function sendSyncEvent(payload, headers) {
  const authHeader = headers["Authorization"] || headers["authorization"];
  const requestHeaders = { "Content-Type": "application/json" };
  if (authHeader) {
    requestHeaders.Authorization = authHeader;
  }
  await fetch("/api/v1/posts/sync/events", {
    method: "POST",
    headers: requestHeaders,
    body: JSON.stringify(payload),
  });
}
