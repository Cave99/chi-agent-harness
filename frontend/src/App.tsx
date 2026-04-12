import React, { useState, useEffect, useRef } from 'react';
import { Send, Cpu, User } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import classNames from 'clsx';
import { twMerge } from 'tailwind-merge';

// Simple utility for tailwind class merging
export function cn(...inputs: (string | undefined | null | false)[]) {
  return twMerge(classNames(inputs));
}

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  type?: 'approval_gate' | 'results' | 'text';
  html?: string;
  charts?: any[];
};

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom on new message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const listenToStream = (sid: string) => {
    const eventSource = new EventSource(`http://localhost:5001/stream/${sid}`);

    eventSource.onmessage = (event) => {
      // Parse general progress status if any
      console.log('SSE:', event.data);
    };

    eventSource.addEventListener('status', (e) => {
      const data = JSON.parse(e.data);
      // You can implement temporary status messages or a typing indicator
      console.log('Status update:', data);
    });

    eventSource.addEventListener('gate', (e) => {
      const data = JSON.parse(e.data);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: 'I have prepared an analysis plan.',
          type: 'approval_gate',
          html: data.html, // Legacy HTMX support can be rendered as pure HTML or we use the data natively
        },
      ]);
      setIsLoading(false);
      eventSource.close();
    });

    eventSource.addEventListener('complete', (e) => {
      const data = JSON.parse(e.data);
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
      eventSource.close();
    });

    eventSource.addEventListener('error', (e) => {
      const data = JSON.parse(e.data);
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: 'assistant', content: `Error: ${data.message}` },
      ]);
      setIsLoading(false);
      eventSource.close();
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputMessage.trim() || isLoading) return;

    const query = inputMessage.trim();
    setInputMessage('');
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content: query }]);
    setIsLoading(true);

    try {
      const formData = new FormData();
      formData.append('question', query);

      const res = await fetch('http://localhost:5001/chat', {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();
      if (data.session_id) {
        setSessionId(data.session_id);
        listenToStream(data.session_id);
      }
    } catch (err) {
      console.error(err);
      setIsLoading(false);
    }
  };

  const renderMessageContent = (msg: Message) => {
    if (msg.type === 'approval_gate' || msg.type === 'results') {
      // As we transition to fully native React components, we can parse data. 
      // For now, dangerouslySetInnerHTML handles the legacy HTML fragments if they still arrive, 
      // but we will eventually swap this with a native React component.
      return <div dangerouslySetInnerHTML={{ __html: msg.html || msg.content }} />;
    }
    return <ReactMarkdown className="prose prose-sm dark:prose-invert">{msg.content}</ReactMarkdown>;
  };

  return (
    <div className="flex flex-col h-screen bg-slate-50 dark:bg-slate-900 font-sans text-slate-800 dark:text-slate-200">
      <header className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white">
            <Cpu size={18} />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Chi Explorer</h1>
        </div>
        <button
          onClick={async () => {
            await fetch('http://localhost:5001/reset', { method: 'POST' });
            setMessages([]);
            setSessionId(null);
          }}
          className="text-sm font-medium text-slate-500 hover:text-slate-900 dark:hover:text-white"
        >
          New Session
        </button>
      </header>

      <main className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500">
            <Cpu size={48} className="mb-4 text-slate-300 dark:text-slate-700" />
            <h2 className="text-2xl font-medium mb-2">Welcome to Chi Explorer</h2>
            <p className="max-w-md text-center">
              Ask questions about call center operations, team performance, and more.
            </p>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto space-y-6">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  'flex gap-4 p-4 rounded-xl',
                  msg.role === 'user'
                    ? 'bg-transparent border border-slate-200 dark:border-slate-800'
                    : 'bg-white dark:bg-slate-800 shadow-sm border border-slate-100 dark:border-slate-700'
                )}
              >
                <div className={cn(
                  'w-8 h-8 rounded-full flex items-center justify-center shrink-0',
                  msg.role === 'user' ? 'bg-slate-200 dark:bg-slate-700' : 'bg-indigo-100 text-indigo-600'
                )}>
                  {msg.role === 'user' ? <User size={16} /> : <Cpu size={16} />}
                </div>
                <div className="flex-1 min-w-0 pt-1">
                  {renderMessageContent(msg)}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="flex gap-4 p-4 bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-100 dark:border-slate-700 animate-pulse">
                <div className="w-8 h-8 rounded-full bg-indigo-100 shrink-0" />
                <div className="flex-1 pt-2 space-y-2">
                  <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-1/4"></div>
                  <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-1/2"></div>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </main>

      <footer className="p-4 bg-white dark:bg-slate-950 border-t border-slate-200 dark:border-slate-800">
        <div className="max-w-4xl mx-auto relative">
          <form onSubmit={handleSubmit} className="flex gap-2 relative shadow-sm">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              placeholder="Ask a question about the call transcripts..."
              className="w-full pl-5 pr-14 py-4 rounded-full border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !inputMessage.trim()}
              className="absolute right-2 top-2 bottom-2 aspect-square flex items-center justify-center bg-indigo-600 text-white rounded-full hover:bg-indigo-700 disabled:opacity-50 disabled:hover:bg-indigo-600 transition-colors"
            >
              <Send size={18} />
            </button>
          </form>
        </div>
      </footer>
    </div>
  );
}
