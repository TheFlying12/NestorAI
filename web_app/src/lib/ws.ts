/**
 * WebSocket connection manager for the Nestor cloud chat endpoint.
 *
 * Usage:
 *   const ws = new NestorWS(onMessage, onStateChange, getToken);
 *   ws.connect();
 *   ws.send({ type: "message", text: "hello", skill_id: "general" });
 *   ws.disconnect();
 */

export type WsInbound =
  | { type: "reply"; text: string }
  | { type: "token"; text: string }
  | { type: "typing" }
  | { type: "pong" };

export type WsOutbound = {
  type: "message" | "ping";
  text?: string;
  skill_id?: string;
};

export type WsState = "disconnected" | "connecting" | "connected" | "error";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "";
const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 5;

export class NestorWS {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private intentionalClose = false;
  private pingInterval: ReturnType<typeof setInterval> | null = null;

  constructor(
    private readonly onMessage: (msg: WsInbound) => void,
    private readonly onStateChange: (state: WsState) => void,
    private readonly getToken: () => Promise<string | null>,
  ) {}

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    this.intentionalClose = false;
    this.reconnectAttempts = 0;
    this._open();
  }

  disconnect(): void {
    this.intentionalClose = true;
    this._cleanup();
  }

  send(msg: WsOutbound): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  private _open(): void {
    this.onStateChange("connecting");
    this.getToken()
      .then((token) => {
        const url = token
          ? `${WS_URL}/chat?token=${encodeURIComponent(token)}`
          : `${WS_URL}/chat`;
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
          this.reconnectAttempts = 0;
          this.onStateChange("connected");
          this._startPing();
        };

        this.ws.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data) as WsInbound;
            this.onMessage(data);
          } catch {
            // ignore malformed frames
          }
        };

        this.ws.onerror = () => {
          this.onStateChange("error");
        };

        this.ws.onclose = () => {
          this._cleanup();
          if (!this.intentionalClose && this.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            this.reconnectAttempts++;
            const delay = RECONNECT_DELAY_MS * Math.pow(1.5, this.reconnectAttempts - 1);
            setTimeout(() => this._open(), delay);
          } else {
            this.onStateChange("disconnected");
          }
        };
      })
      .catch(() => {
        this.onStateChange("error");
      });
  }

  private _startPing(): void {
    this.pingInterval = setInterval(() => {
      this.send({ type: "ping" });
    }, 30_000);
  }

  private _cleanup(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
  }
}
