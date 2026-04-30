import { API_BASE_URL } from "../api/client";

export interface RealtimeEvent {
  event_type: string;
  payload: Record<string, unknown>;
}

type ConnectionState = "connected" | "disconnected";

interface ConnectOptions {
  getToken: () => string | null;
  onEvent: (event: RealtimeEvent) => void;
  onStateChange?: (state: ConnectionState) => void;
  onAuthFailure?: () => Promise<boolean> | boolean;
}

class RealtimeSocketService {
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private shouldReconnect = false;
  private options: ConnectOptions | null = null;

  connect(options: ConnectOptions) {
    this.options = options;
    this.shouldReconnect = true;
    void this.openSocket();
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
    this.options?.onStateChange?.("disconnected");
  }

  private async openSocket() {
    const options = this.options;
    let token = options?.getToken() || null;
    if (!options || !token) {
      this.disconnect();
      return;
    }
    if (this.isAccessTokenExpired(token)) {
      const canRetry = await this.handleAuthFailure(options);
      if (!canRetry) {
        this.shouldReconnect = false;
        this.disconnect();
        return;
      }
      token = options.getToken() || null;
      if (!token) {
        this.disconnect();
        return;
      }
    }
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) {
      return;
    }
    const socketUrl = this.buildSocketUrl(token);
    this.socket = new WebSocket(socketUrl);
    this.socket.onopen = () => {
      this.reconnectAttempt = 0;
      options.onStateChange?.("connected");
    };
    this.socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(String(event.data || "{}")) as RealtimeEvent;
        options.onEvent(parsed);
      } catch {
        // Ignore malformed realtime payloads.
      }
    };
    this.socket.onclose = async (event) => {
      options.onStateChange?.("disconnected");
      this.socket = null;
      if (event.code === 4401 || event.code === 4403) {
        const canRetry = await this.handleAuthFailure(options);
        if (!canRetry) {
          this.shouldReconnect = false;
          return;
        }
        this.reconnectAttempt = 0;
        this.scheduleReconnect(0);
        return;
      }
      this.scheduleReconnect();
    };
    this.socket.onerror = () => {
      if (this.socket && this.socket.readyState !== WebSocket.CLOSED) {
        this.socket.close();
      }
    };
  }

  private scheduleReconnect(waitMsOverride?: number) {
    if (!this.shouldReconnect) {
      return;
    }
    const token = this.options?.getToken() || null;
    if (!token) {
      return;
    }
    const waitMs = waitMsOverride ?? Math.min(30000, 1000 * 2 ** Math.min(this.reconnectAttempt, 5));
    this.reconnectAttempt += 1;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => {
      void this.openSocket();
    }, waitMs);
  }

  private async handleAuthFailure(options: ConnectOptions): Promise<boolean> {
    if (!options.onAuthFailure) {
      return false;
    }
    try {
      return Boolean(await options.onAuthFailure());
    } catch {
      return false;
    }
  }

  private buildSocketUrl(token: string) {
    const apiUrl = new URL(API_BASE_URL);
    const wsProtocol = apiUrl.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = new URL(`${wsProtocol}//${apiUrl.host}/ws/notifications/`);
    wsUrl.searchParams.set("token", token);
    return wsUrl.toString();
  }

  private isAccessTokenExpired(token: string): boolean {
    try {
      const segments = token.split(".");
      if (segments.length < 2) {
        return false;
      }
      const payloadSegment = segments[1].replace(/-/g, "+").replace(/_/g, "/");
      const paddedSegment = payloadSegment.padEnd(Math.ceil(payloadSegment.length / 4) * 4, "=");
      const payload = JSON.parse(atob(paddedSegment)) as { exp?: number };
      const expTimestampSeconds = Number(payload.exp || 0);
      if (!expTimestampSeconds) {
        return false;
      }
      const nowSeconds = Math.floor(Date.now() / 1000);
      return expTimestampSeconds <= nowSeconds + 15;
    } catch {
      return false;
    }
  }
}

export const realtimeSocket = new RealtimeSocketService();
