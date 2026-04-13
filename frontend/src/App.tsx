import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Message, GateData } from './types';
import { cn } from './services/utils';
import { API_ENDPOINTS } from './services/api';
import { GateCard } from './features/Pipeline/GateCard';
import { ChartCard } from './features/Analytics/ChartCard';
import { useSSE } from './hooks/useSSE';

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  
  const {
    statusMessage,
    setStatusMessage,
    streamingText,
    setStreamingText,
    lastBgLine,
    setLastBgLine,
    isRefiningRef,
    listenToStream
  } = useSSE();

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingText, lastBgLine]);

  const onGate = (data: GateData, wasRefining: boolean) => {
    setMessages((prev) => {
      const newMsg = {
        id: crypto.randomUUID(),
        role: 'assistant' as const,
        content: '',
        type: 'approval_gate' as const,
        gateData: data,
      };
      if (wasRefining) {
        const lastGateIdx = [...prev].map((m, i) => ({ m, i })).reverse().find(({ m }) => m.type === 'approval_gate')?.i;
        if (lastGateIdx !== undefined) {
          return prev.map((m, i) => i === lastGateIdx ? { ...newMsg, id: m.id } : m);
        }
      }
      return [...prev, newMsg];
    });
    setIsLoading(false);
  };

  const onComplete = (data: any) => {
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: data.summary || 'Analysis complete.',
        type: 'results',
        html: data.html,
        charts: data.charts,
      },
    ]);
    setIsLoading(false);
  };

  const onError = (message: string) => {
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: 'assistant', content: `Error: ${message}` },
    ]);
    setIsLoading(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputMessage.trim() || isLoading) return;

    const query = inputMessage.trim();
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content: query }]);
    setInputMessage('');
    setIsLoading(true);
    setStreamingText('');

    try {
      const chatForm = new FormData();
      chatForm.append('question', query);
      if (sessionId) chatForm.append('session_id', sessionId);
      const res = await fetch(API_ENDPOINTS.CHAT, {
        method: 'POST',
        body: chatForm,
      });
      const data = await res.json();
      setSessionId(data.session_id);
      listenToStream(data.session_id, onGate, onComplete, onError);
    } catch (err: any) {
      onError(err.message);
    }
  };

  const handleRefine = async (instruction: string) => {
    if (isLoading) return;
    setIsLoading(true);
    isRefiningRef.current = true;
    setLastBgLine('Preparing refinement…');

    try {
      const refineForm = new FormData();
      refineForm.append('instruction', instruction);
      if (sessionId) refineForm.append('session_id', sessionId);
      const res = await fetch(API_ENDPOINTS.REFINE, {
        method: 'POST',
        body: refineForm,
      });
      const data = await res.json();
      listenToStream(data.session_id, onGate, onComplete, onError);
    } catch (err: any) {
      isRefiningRef.current = false;
      onError(err.message);
    }
  };

  const handlePatch = async (msgId: string, updates: Partial<GateData>) => {
    try {
      const res = await fetch(API_ENDPOINTS.PATCH, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates, session_id: sessionId }),
      });
      const data = await res.json();
      // Update the local message state with the new gateData
      setMessages(prev => prev.map(m => m.id === msgId ? { ...m, gateData: data.gate_data } : m));
    } catch (err: any) {
      console.error('Patch failed:', err);
    }
  };

  const handleRun = async () => {
    if (isLoading) return;
    setIsLoading(true);
    setStatusMessage('Starting pipeline…');

    try {
      const runForm = new FormData();
      if (sessionId) runForm.append('session_id', sessionId);
      const res = await fetch(API_ENDPOINTS.RUN, {
        method: 'POST',
        body: runForm,
      });
      const data = await res.json();
      listenToStream(data.session_id, onGate, onComplete, onError);
    } catch (err: any) {
      onError(err.message);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-surface">
      {/* Header */}
      <header className="px-8 py-6 border-b border-outline-variant/15 flex items-center justify-between bg-white/80 backdrop-blur-xl sticky top-0 z-10">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-primary to-primary-container flex items-center justify-center shadow-lg shadow-primary/20">
            <span className="material-symbols-outlined text-white text-2xl" style={{ fontVariationSettings: '"FILL" 1' }}>bolt</span>
          </div>
          <div>
            <h1 className="font-headline font-black text-xl tracking-tight text-on-surface">CHI Explorer</h1>
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant/60">Radiant Editorial Engine</p>
          </div>
        </div>
        <button 
          onClick={() => window.location.reload()}
          className="p-2.5 rounded-2xl hover:bg-surface-container-high transition-all text-on-surface-variant active:scale-90"
        >
          <span className="material-symbols-outlined">restart_alt</span>
        </button>
      </header>

      {/* Chat Area */}
      <main className="flex-1 overflow-y-auto px-6 py-8 space-y-10 scroll-smooth">
        <div className="max-w-4xl mx-auto w-full space-y-10">
          {messages.length === 0 && (
            <div className="py-20 text-center space-y-6">
              <h2 className="font-headline font-black text-4xl md:text-6xl text-on-surface leading-[1.1] tracking-tight">
                What would you like to<br/>
                <span className="text-primary italic">uncover</span> today?
              </h2>
              <p className="text-on-surface-variant max-w-md mx-auto text-lg leading-relaxed">
                Connect your call transcripts to the CHI scoring engine for deep editorial insights.
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} className={cn('flex flex-col animate-in fade-in slide-in-from-bottom-4 duration-500', msg.role === 'user' ? 'items-end' : 'items-start')}>
              <div className={cn(
                'max-w-[85%] rounded-[2rem] px-7 py-5 shadow-sm transition-all',
                msg.role === 'user' 
                  ? 'bg-primary text-white font-medium rounded-tr-lg shadow-primary/10' 
                  : 'bg-white border border-outline-variant/10 text-on-surface rounded-tl-lg'
              )}>
                {msg.type === 'approval_gate' && msg.gateData ? (
                  <GateCard 
                    msgId={msg.id}
                    data={msg.gateData} 
                    isLoading={isLoading} 
                    onRun={handleRun}
                    onPatch={handlePatch}
                    onRefine={handleRefine}
                  />
                ) : msg.type === 'results' ? (
                  <div className="space-y-8 min-w-[300px] md:min-w-[600px]">
                    <div className="prose prose-sm prose-neutral max-w-none">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                    
                    {msg.charts && msg.charts.length > 0 && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {msg.charts.map((c, i) => <ChartCard key={i} chart={c} />)}
                      </div>
                    )}

                    {msg.html && (
                      <div className="rounded-2xl border border-outline-variant/20 overflow-hidden bg-surface-container-low p-4">
                        <div dangerouslySetInnerHTML={{ __html: msg.html }} className="text-xs font-mono" />
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="prose prose-sm max-w-none leading-relaxed">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Streaming Assistant Response */}
          {streamingText && (
            <div className="flex flex-col items-start animate-in fade-in duration-300">
              <div className="max-w-[85%] bg-white border border-outline-variant/10 text-on-surface rounded-[2rem] rounded-tl-lg px-7 py-5 shadow-sm">
                <div className="prose prose-sm max-w-none leading-relaxed">
                  <ReactMarkdown>{streamingText}</ReactMarkdown>
                </div>
              </div>
            </div>
          )}

          {/* Status / Background Stream Indicator */}
          {(statusMessage || lastBgLine) && (
            <div className="flex items-center gap-4 text-on-surface-variant/60 py-2 px-4 bg-surface-container-low/50 rounded-2xl w-fit animate-pulse">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" />
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce [animation-delay:0.2s]" />
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce [animation-delay:0.4s]" />
              </div>
              <div className="flex flex-col">
                {statusMessage && <span className="text-xs font-bold uppercase tracking-wider">{statusMessage}</span>}
                {lastBgLine && <span className="text-[10px] font-mono opacity-70 truncate max-w-md">{lastBgLine}</span>}
              </div>
            </div>
          )}
          
          <div ref={bottomRef} className="h-4" />
        </div>
      </main>

      {/* Input Area */}
      <div className="p-6 bg-white border-t border-outline-variant/15">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto relative group">
          <input
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            placeholder="Type your question..."
            disabled={isLoading}
            className="w-full bg-surface-container-low text-on-surface rounded-[2.5rem] pl-8 pr-16 py-5 outline-none focus:ring-2 focus:ring-primary/20 border border-outline-variant/10 transition-all placeholder:text-on-surface-variant/40 group-hover:border-outline-variant/30"
          />
          <button
            type="submit"
            disabled={!inputMessage.trim() || isLoading}
            className="absolute right-3 top-1/2 -translate-y-1/2 w-12 h-12 bg-primary text-white rounded-full flex items-center justify-center hover:bg-surface-tint disabled:opacity-30 disabled:grayscale transition-all shadow-lg shadow-primary/20 active:scale-90"
          >
            <span className="material-symbols-outlined">arrow_upward</span>
          </button>
        </form>
        <p className="text-center text-[10px] text-on-surface-variant/40 mt-4 font-medium uppercase tracking-widest">
          Powered by CHI Editorial Engine • Built with Precision
        </p>
      </div>
    </div>
  );
}
