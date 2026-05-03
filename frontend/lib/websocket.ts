type MessageHandler = (data: any) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectInterval: number = 5000;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private reconnectHandlers: Set<() => void> = new Set();
  private isFirstConnect: boolean = true;

  constructor() {
    this.url = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
  }

  onReconnect(handler: () => void) {
    this.reconnectHandlers.add(handler);
    return () => this.reconnectHandlers.delete(handler);
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    this.ws = new WebSocket(`${this.url}/api/ws`);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      if (!this.isFirstConnect) {
        this.reconnectHandlers.forEach((h) => h());
      }
      this.isFirstConnect = false;
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const type = data.type;

        if (this.handlers.has(type)) {
          this.handlers.get(type)?.forEach((handler) => handler(data));
        }

        // Broadcast to all handlers
        if (this.handlers.has('*')) {
          this.handlers.get('*')?.forEach((handler) => handler(data));
        }
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };

    this.ws.onclose = () => {
      console.log('WebSocket disconnected, reconnecting...');
      setTimeout(() => this.connect(), this.reconnectInterval);
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  send(data: any) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  subscribe(type: string, handler: MessageHandler) {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }
    this.handlers.get(type)?.add(handler);

    return () => {
      this.handlers.get(type)?.delete(handler);
    };
  }

  subscribeToPrice(symbol: string) {
    this.send({ type: 'subscribe_price', symbol });
  }

  subscribeToBot(bot_id: number) {
    this.send({ type: 'subscribe_bot', bot_id });
  }
}

export const wsClient = new WebSocketClient();
