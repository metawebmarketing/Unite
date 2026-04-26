export interface QueuedRequestAction {
  id?: number;
  kind: "create_post" | "react_post";
  method: "POST";
  url: string;
  body: string;
  headers: Record<string, string>;
  conflictKey?: string;
  queuedAt: number;
}

const DB_NAME = "unite-offline-db";
const DB_VERSION = 1;
const STORE_NAME = "request_queue";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: "id", autoIncrement: true });
        store.createIndex("by_conflict_key", "conflictKey", { unique: false });
        store.createIndex("by_queued_at", "queuedAt", { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function enqueueQueuedAction(action: QueuedRequestAction): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    if (action.conflictKey) {
      const index = store.index("by_conflict_key");
      const getAll = index.getAll(action.conflictKey);
      getAll.onsuccess = () => {
        const existing = getAll.result as QueuedRequestAction[];
        for (const item of existing) {
          if (typeof item.id === "number") {
            store.delete(item.id);
          }
        }
        store.add(action);
      };
      getAll.onerror = () => reject(getAll.error);
    } else {
      store.add(action);
    }
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function getQueuedActions(): Promise<QueuedRequestAction[]> {
  const db = await openDb();
  return await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const request = store.getAll();
    request.onsuccess = () => {
      const items = (request.result as QueuedRequestAction[]).sort((a, b) => a.queuedAt - b.queuedAt);
      resolve(items);
    };
    request.onerror = () => reject(request.error);
  });
}

export async function removeQueuedAction(id: number): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
