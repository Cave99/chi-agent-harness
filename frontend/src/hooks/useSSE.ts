import { useState, useRef } from 'react';
import { API_ENDPOINTS } from '../services/api';
import type { GateData } from '../types';

export function useSSE() {
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [lastBgLine, setLastBgLine] = useState<string>('');
  const isRefiningRef = useRef(false);

  const listenToStream = (
    sid: string,
    onGate: (data: GateData, wasRefining: boolean) => void,
    onComplete: (data: any) => void,
    onError: (message: string) => void
  ) => {
    const eventSource = new EventSource(API_ENDPOINTS.STREAM(sid));

    const t0 = Date.now();
    const elapsed = () => `${((Date.now() - t0) / 1000).toFixed(1)}s`;

    eventSource.onmessage = (event: MessageEvent) => {
      console.log(`[SSE ${elapsed()}]`, event.data);
    };

    eventSource.addEventListener('status', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      const msg = data.message || '';
      setStatusMessage(msg);
      console.log(`[STATUS ${elapsed()}] ${msg}`);
    });

    eventSource.addEventListener('token', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setStreamingText((prev) => (prev ?? '') + (data.text || ''));
    });

    eventSource.addEventListener('background_token', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      const chunk: string = data.text || '';
      setLastBgLine((prev) => {
        const combined = prev + chunk;
        const lines = combined.split('\n');
        return lines[lines.length - 1].slice(-150);
      });
    });

    eventSource.addEventListener('gate', (e) => {
      const data = JSON.parse((e as MessageEvent).data) as GateData;
      setStatusMessage('');
      setLastBgLine('');
      const wasRefining = isRefiningRef.current;
      isRefiningRef.current = false;
      onGate(data, wasRefining);
      eventSource.close();
    });

    eventSource.addEventListener('complete', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setStreamingText(null);
      setStatusMessage('');
      setLastBgLine('');
      onComplete(data);
      eventSource.close();
    });

    eventSource.addEventListener('error', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setStreamingText(null);
      setStatusMessage('');
      setLastBgLine('');
      onError(data.message);
      eventSource.close();
    });

    return eventSource;
  };

  return {
    statusMessage,
    setStatusMessage,
    streamingText,
    setStreamingText,
    lastBgLine,
    setLastBgLine,
    isRefiningRef,
    listenToStream
  };
}
