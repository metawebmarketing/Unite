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
    this.openSocket();
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

  private openSocket() {
    const options = this.options;
    const token = options?.getToken() || null;
    if (!options || !token) {
      this.disconnect();
      return;
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
    this.socket.onclose = () => {
      options.onStateChange?.("disconnected");
      this.socket = null;
      this.scheduleReconnect();
    };
    this.socket.onerror = () => {
      if (this.socket && this.socket.readyState !== WebSocket.CLOSED) {
        this.socket.close();
      }
    };
  }

  private scheduleReconnect() {
    if (!this.shouldReconnect) {
      return;
    }
    const token = this.options?.getToken() || null;
    if (!token) {
      return;
    }
    const waitMs = Math.min(30000, 1000 * 2 ** Math.min(this.reconnectAttempt, 5));
    this.reconnectAttempt += 1;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => {
      this.openSocket();
    }, waitMs);
  }

  private buildSocketUrl(token: string) {
    const apiUrl = new URL(API_BASE_URL);
    const wsProtocol = apiUrl.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = new URL(`${wsProtocol}//${apiUrl.host}/ws/notifications`);
    wsUrl.searchParams.set("token", token);
    return wsUrl.toString();
  }
}

export const realtimeSocket = new RealtimeSocketService();
