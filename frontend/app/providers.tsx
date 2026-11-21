'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, useEffect } from 'react';
import { wsClient } from '@/lib/websocket';
import { useAuthStore } from '@/lib/store';

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());

  useEffect(() => {
    useAuthStore.getState().hydrate();
    // Connect WebSocket on mount
    wsClient.connect();

    return () => {
      wsClient.disconnect();
    };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}
