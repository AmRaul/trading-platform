import { getAccessToken, onAccessTokenChange, setAccessToken } from './auth';

type MessageHandler = (data: any) => void;

// Сервер закрывает с этим кодом, если токен не принят — обновить и переподключиться
const UNAUTHORIZED = 4401;

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
  private wanted = false;      // connect() вызван и disconnect() — нет
  private connecting = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    this.url = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
    // не вошли — сокет не открываем; вошли (или токен обновился) — подключаемся
    onAccessTokenChange((token) => {
      if (token && this.wanted) this.connect();
      if (!token) this.ws?.close();  // вышли / сессия кончилась — события больше не получаем
    });
  }

  onReconnect(handler: () => void) {
    this.reconnectHandlers.add(handler);
    return () => this.reconnectHandlers.delete(handler);
  }

  async connect() {
    this.wanted = true;
    if (this.connecting || this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return;
    }
    this.connecting = true;
    let token: string | null;
    try {
      token = await getAccessToken();
    } finally {
      this.connecting = false;
    }
    if (!token || !this.wanted) return;  // ждём входа — onAccessTokenChange

    this.ws = new WebSocket(`${this.url}/api/ws`);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      // первым сообщением — токен (не в URL: URL попадает в логи прокси)
      this.ws?.send(JSON.stringify({ type: 'auth', token }));
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

    this.ws.onclose = (event) => {
      this.ws = null;
      if (!this.wanted) return;
      if (event.code === UNAUTHORIZED) {
        setAccessToken(null);  // следующий connect() возьмёт новый через refresh
      }
      console.log('WebSocket disconnected, reconnecting...');
      if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => this.connect(), this.reconnectInterval);
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
    this.wanted = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
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
