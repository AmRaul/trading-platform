type MessageHandler = (data: any) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectInterval: number = 5000;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private reconnectHandlers: Set<() => void> = new Set();
  private isFirstConnect: boolean = true;
  // Subscriptions must survive both the initial connect (which can still be
  // in CONNECTING state when a page calls subscribeToPrice on mount — send()
  // would silently drop the message) and any later reconnect, since the
  // server-side manager has no memory of what a fresh socket was subscribed
  // to before it dropped.
  private subscribedSymbols: Set<string> = new Set();
  private subscribedBotIds: Set<number> = new Set();

  constructor() {
    this.url = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
  }

  onReconnect(handler: () => void) {
    this.reconnectHandlers.add(handler);
    return () => this.reconnectHandlers.delete(handler);
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return;
    }

    this.ws = new WebSocket(`${this.url}/api/ws`);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.resubscribeAll();
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

  private resubscribeAll() {
    this.subscribedSymbols.forEach((symbol) => this.rawSend({ type: 'subscribe_price', symbol }));
    this.subscribedBotIds.forEach((bot_id) => this.rawSend({ type: 'subscribe_bot', bot_id }));
  }

  private rawSend(data: any) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  send(data: any) {
    this.rawSend(data);
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
    this.subscribedSymbols.add(symbol);
    this.rawSend({ type: 'subscribe_price', symbol });
  }

  subscribeToBot(bot_id: number) {
    this.subscribedBotIds.add(bot_id);
    this.rawSend({ type: 'subscribe_bot', bot_id });
  }
}

export const wsClient = new WebSocketClient();
