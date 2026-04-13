import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import classNames from 'clsx';
import { twMerge } from 'tailwind-merge';
import {
  ResponsiveContainer,
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts';

export function cn(...inputs: (string | undefined | null | false)[]) {
  return twMerge(classNames(inputs));
}

type FieldDef = {
  name: string;
  type: 'numerical' | 'categorical' | 'boolean' | 'freeform_text' | 'date';
  description: string;
  range?: [number, number];
};

type GateData = {
  question: string;
  where_clause: string;
  system_prompt: string;
  field_manifest: { fields: FieldDef[] };
  call_count: number;
  cost_estimate: number;
  warn_count: boolean;
  warn_cost: boolean;
  session_id: string;
  sample_transcripts: any[];
};

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  type?: 'approval_gate' | 'results' | 'text';
  html?: string;
  charts?: any[];
  gateData?: GateData;
};

// ── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_DISPLAY: Record<string, string> = {
  numerical:    'int',
  categorical:  'str',
  boolean:      'bool',
  freeform_text:'text',
  date:         'date',
};

const TYPE_COLOUR: Record<string, string> = {
  numerical:    'text-blue-600',
  categorical:  'text-violet-600',
  boolean:      'text-emerald-600',
  freeform_text:'text-amber-600',
  date:         'text-sky-600',
};

// ── Modal ─────────────────────────────────────────────────────────────────────

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
      <div
        className="relative bg-white rounded-3xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant/20 shrink-0">
          <h2 className="font-headline font-bold text-base text-on-surface">{title}</h2>
          <button onClick={onClose} className="p-1 rounded-full hover:bg-surface-container-high transition-colors text-on-surface-variant">
            <span className="material-symbols-outlined text-xl">close</span>
          </button>
        </div>
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-5">
          {children}
        </div>
      </div>
    </div>
  );
}

// ── ImproveInput — scoped AI refinement input used inside each modal ──────────

function ImproveInput({ placeholder, prefix, onRefine, isLoading }: {
  placeholder: string;
  prefix: string;
  onRefine: (instruction: string) => void;
  isLoading: boolean;
}) {
  const [text, setText] = useState('');
  const submit = () => {
    if (!text.trim()) return;
    onRefine(`${prefix}${text.trim()}`);
    setText('');
  };
  return (
    <div className="border-t border-outline-variant/20 pt-4 space-y-2">
      <p className="text-xs font-semibold uppercase tracking-widest text-on-surface-variant flex items-center gap-1.5">
        <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>auto_awesome</span>
        Improve with AI
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
          placeholder={placeholder}
          disabled={isLoading}
          className="flex-1 bg-surface-container-high text-on-surface text-sm rounded-full px-4 py-2 outline-none focus:ring-1 focus:ring-primary border border-outline-variant/20 placeholder:text-neutral-400 disabled:opacity-50"
        />
        <button
          onClick={submit}
          disabled={isLoading || !text.trim()}
          className="px-4 py-2 bg-primary/10 text-primary rounded-full text-sm font-semibold hover:bg-primary/15 disabled:opacity-40 transition-colors"
        >
          Improve
        </button>
      </div>
    </div>
  );
}

// ── GateCard ──────────────────────────────────────────────────────────────────

type GateCardProps = {
  msgId: string;
  data: GateData;
  isLoading: boolean;
  onRun: () => void;
  onPatch: (msgId: string, updates: Partial<Pick<GateData, 'where_clause' | 'system_prompt' | 'field_manifest'>>) => Promise<void>;
  onRefine: (instruction: string) => void;
};

function GateCard({ msgId, data, isLoading, onRun, onPatch, onRefine }: GateCardProps) {
  const [modal, setModal] = useState<'sql' | 'fields' | 'prompt' | null>(null);
  const [patching, setPatching] = useState(false);

  // ── SQL modal state ─────────────────────────────────────────────────────────
  const [whereClause, setWhereClause] = useState(data.where_clause);
  const [sqlErrors, setSqlErrors]     = useState<string[]>([]);

  // ── Prompt modal state ──────────────────────────────────────────────────────
  const [promptDraft, setPromptDraft] = useState(data.system_prompt);

  // Reset drafts when data changes (after patch/refine)
  useEffect(() => {
    setWhereClause(data.where_clause);
    setPromptDraft(data.system_prompt);
    setSqlErrors([]);
  }, [data.where_clause, data.system_prompt]);

  const validateSql = async (clause: string) => {
    try {
      const res = await fetch('http://localhost:5001/validate-sql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ where_clause: clause }),
      });
      return (await res.json()).errors as string[] ?? [];
    } catch { return []; }
  };

  const saveWhere = async () => {
    const errors = await validateSql(whereClause);
    setSqlErrors(errors);
    if (errors.length > 0) return;
    setPatching(true);
    await onPatch(msgId, { where_clause: whereClause });
    setPatching(false);
    setModal(null);
  };

  const savePrompt = async () => {
    setPatching(true);
    await onPatch(msgId, { system_prompt: promptDraft });
    setPatching(false);
    setModal(null);
  };

  const removeField = async (name: string) => {
    setPatching(true);
    await onPatch(msgId, {
      field_manifest: { fields: data.field_manifest.fields.filter(f => f.name !== name) },
    });
    setPatching(false);
  };

  const closeModal = () => { setModal(null); setSqlErrors([]); };

  return (
    <>
      <div className="space-y-4 min-w-[300px] max-w-lg">
        {/* Header */}
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-primary" style={{ fontVariationSettings: '"FILL" 1' }}>fact_check</span>
          <h3 className="font-headline font-bold text-base">Analysis plan ready</h3>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 gap-2">
          <div className={cn('rounded-2xl px-4 py-3', data.warn_count ? 'bg-amber-50' : 'bg-surface-container-high')}>
            <p className="text-xs text-on-surface-variant mb-0.5">Calls matched</p>
            <p className={cn('text-xl font-headline font-black', data.warn_count ? 'text-amber-700' : 'text-on-surface')}>
              {data.warn_count && <span className="material-symbols-outlined text-base mr-1 align-middle">warning</span>}
              {data.call_count.toLocaleString()}
            </p>
          </div>
          <div className={cn('rounded-2xl px-4 py-3', data.warn_cost ? 'bg-amber-50' : 'bg-surface-container-high')}>
            <p className="text-xs text-on-surface-variant mb-0.5">Estimated cost</p>
            <p className={cn('text-xl font-headline font-black', data.warn_cost ? 'text-amber-700' : 'text-on-surface')}>
              {data.warn_cost && <span className="material-symbols-outlined text-base mr-1 align-middle">warning</span>}
              ${data.cost_estimate.toFixed(2)}
            </p>
          </div>
        </div>

        {/* Fields table */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold uppercase tracking-widest text-on-surface-variant">
              Fields ({data.field_manifest.fields.length})
            </p>
            <button
              onClick={() => setModal('fields')}
              className="text-xs text-primary hover:underline flex items-center gap-0.5"
            >
              <span className="material-symbols-outlined text-sm">edit</span> Edit
            </button>
          </div>
          <div className="rounded-2xl overflow-hidden border border-outline-variant/20">
            <table className="w-full text-sm">
              <tbody>
                {data.field_manifest.fields.map((f, i) => (
                  <tr key={f.name} className={cn('border-b border-outline-variant/10 last:border-0', i % 2 === 0 ? 'bg-surface-container-lowest' : 'bg-surface-container-high/40')}>
                    <td className="px-4 py-2.5 font-mono text-xs text-on-surface font-medium">{f.name}</td>
                    <td className="px-4 py-2.5 text-right">
                      <span className={cn('text-xs font-mono font-semibold', TYPE_COLOUR[f.type] ?? 'text-on-surface-variant')}>
                        {TYPE_DISPLAY[f.type] ?? f.type}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Action buttons */}
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => setModal('sql')}
            className="flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-2xl bg-surface-container-high hover:bg-surface-container-highest text-on-surface text-sm font-medium transition-colors"
          >
            <span className="material-symbols-outlined text-base text-primary">filter_alt</span>
            SQL Filter
          </button>
          <button
            onClick={() => setModal('prompt')}
            className="flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-2xl bg-surface-container-high hover:bg-surface-container-highest text-on-surface text-sm font-medium transition-colors"
          >
            <span className="material-symbols-outlined text-base text-primary">prompt_suggestion</span>
            System Prompt
          </button>
        </div>

        {/* Run */}
        <button
          onClick={onRun}
          disabled={isLoading || patching}
          className="w-full py-3 bg-primary text-white rounded-full font-headline font-bold text-sm tracking-wide hover:bg-surface-tint active:scale-95 transition-all shadow-md shadow-primary/25 disabled:opacity-50 flex items-center justify-center gap-2"
        >
          <span className="material-symbols-outlined text-base" style={{ fontVariationSettings: '"FILL" 1' }}>play_arrow</span>
          Run Analysis
        </button>
      </div>

      {/* ── SQL Filter Modal ─────────────────────────────────────────────────── */}
      {modal === 'sql' && (
        <Modal title="SQL Filter" onClose={closeModal}>
          <div>
            <p className="text-xs text-on-surface-variant mb-2">
              SQLite WHERE clause applied to the <code className="font-mono bg-surface-container-high px-1 rounded">calls</code> table.
              Leave empty to analyse all calls.
            </p>
            <textarea
              value={whereClause}
              onChange={e => { setWhereClause(e.target.value); setSqlErrors([]); }}
              className="w-full bg-surface-container-high text-on-surface text-xs rounded-xl px-4 py-3 font-mono resize-none outline-none focus:ring-1 focus:ring-primary border border-outline-variant/20"
              rows={4}
              spellCheck={false}
            />
            {sqlErrors.map((err, i) => (
              <p key={i} className="text-xs text-red-600 flex items-center gap-1 mt-1">
                <span className="material-symbols-outlined text-sm">error</span>{err}
              </p>
            ))}
            <div className="flex gap-2 mt-3 justify-end">
              <button onClick={closeModal} className="px-4 py-2 text-sm text-on-surface-variant hover:underline">Cancel</button>
              <button
                onClick={saveWhere}
                disabled={patching}
                className="px-5 py-2 bg-primary text-white rounded-full text-sm font-semibold hover:bg-surface-tint disabled:opacity-50 transition-colors"
              >
                {patching ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
          <ImproveInput
            placeholder="e.g. Only include calls longer than 2 minutes from the Retention team"
            prefix="Update only the SQL WHERE clause filter. Do not change the system_prompt or field_manifest. Instruction: "
            onRefine={instruction => { closeModal(); onRefine(instruction); }}
            isLoading={isLoading}
          />
        </Modal>
      )}

      {/* ── Fields Modal ─────────────────────────────────────────────────────── */}
      {modal === 'fields' && (
        <Modal title="Analysis Fields" onClose={closeModal}>
          <div>
            <p className="text-xs text-on-surface-variant mb-3">
              Each field will be extracted from every call transcript. Click × to remove a field.
            </p>
            <div className="rounded-2xl overflow-hidden border border-outline-variant/20">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-surface-container-high border-b border-outline-variant/20">
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-on-surface-variant uppercase tracking-wide">Field</th>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-on-surface-variant uppercase tracking-wide">Type</th>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-on-surface-variant uppercase tracking-wide">Description</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {data.field_manifest.fields.map((f, i) => (
                    <tr key={f.name} className={cn('border-b border-outline-variant/10 last:border-0', i % 2 === 0 ? '' : 'bg-surface-container-high/30')}>
                      <td className="px-4 py-3 font-mono text-xs text-on-surface font-medium whitespace-nowrap">{f.name}</td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className={cn('text-xs font-mono font-semibold', TYPE_COLOUR[f.type] ?? 'text-on-surface-variant')}>
                          {TYPE_DISPLAY[f.type] ?? f.type}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-on-surface-variant">{f.description}</td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => removeField(f.name)}
                          disabled={patching}
                          className="text-on-surface-variant/40 hover:text-red-500 transition-colors disabled:opacity-30"
                          title="Remove field"
                        >
                          <span className="material-symbols-outlined text-base">close</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <ImproveInput
            placeholder="e.g. Add a field tracking whether the agent offered a callback, and remove the freeform summary"
            prefix="Update only the field_manifest (add, remove, or edit fields as needed). Do not change the where_clause or system_prompt. Instruction: "
            onRefine={instruction => { closeModal(); onRefine(instruction); }}
            isLoading={isLoading}
          />
        </Modal>
      )}

      {/* ── System Prompt Modal ───────────────────────────────────────────────── */}
      {modal === 'prompt' && (
        <Modal title="System Prompt" onClose={closeModal}>
          <div>
            <p className="text-xs text-on-surface-variant mb-2">
              This prompt is injected before each call transcript and tells the LLM what to extract.
            </p>
            <textarea
              value={promptDraft}
              onChange={e => setPromptDraft(e.target.value)}
              className="w-full bg-surface-container-high text-on-surface text-xs rounded-xl px-4 py-3 font-mono resize-y outline-none focus:ring-1 focus:ring-primary border border-outline-variant/20"
              rows={16}
              spellCheck={false}
            />
            <div className="flex gap-2 mt-3 justify-end">
              <button onClick={() => { setPromptDraft(data.system_prompt); closeModal(); }} className="px-4 py-2 text-sm text-on-surface-variant hover:underline">Cancel</button>
              <button
                onClick={savePrompt}
                disabled={patching}
                className="px-5 py-2 bg-primary text-white rounded-full text-sm font-semibold hover:bg-surface-tint disabled:opacity-50 transition-colors"
              >
                {patching ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
          <ImproveInput
            placeholder="e.g. Make the scoring rubric stricter and add more detail to the reasoning instructions"
            prefix="Update only the system_prompt. Do not change the where_clause or field_manifest. Instruction: "
            onRefine={instruction => { closeModal(); onRefine(instruction); }}
            isLoading={isLoading}
          />
        </Modal>
      )}
    </>
  );
}

// ── ChartCard ─────────────────────────────────────────────────────────────────

const PIE_COLOURS = ['#ac3500', '#ffb233', '#6366f1', '#5f5e5e', '#22c55e', '#0ea5e9'];

function ChartCard({ chart }: { chart: any }) {
  const { title, type, data, xAxisKey = 'name', dataKey = 'value', color = '#ac3500' } = chart;

  const renderChart = () => {
    if (type === 'pie') {
      return (
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie data={data} dataKey={dataKey} nameKey={xAxisKey} cx="50%" cy="50%" outerRadius={90} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`} labelLine={false}>
              {data.map((_: any, i: number) => (
                <Cell key={i} fill={PIE_COLOURS[i % PIE_COLOURS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(v: any) => [v, dataKey]} />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      );
    }
    if (type === 'line') {
      return (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey={xAxisKey} tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      );
    }
    // default: bar
    return (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey={xAxisKey} tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip />
          <Bar dataKey={dataKey} fill={color} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  };

  return (
    <div className="bg-white rounded-2xl border border-outline-variant/20 shadow-sm p-4 space-y-3">
      <p className="text-sm font-headline font-bold text-on-surface">{title}</p>
      {renderChart()}
    </div>
  );
}

// ── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [streamingText, setStreamingText] = useState<string | null>(null);
  // lastBgLine: the most-recently-written line from the LLM background stream
  const [lastBgLine, setLastBgLine] = useState<string>('');
  const bottomRef = useRef<HTMLDivElement>(null);
  // Track whether we're refining so the gate SSE handler replaces rather than adds
  const isRefiningRef = useRef(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const listenToStream = (sid: string) => {
    const eventSource = new EventSource(`http://localhost:5001/stream/${sid}`);

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

    // background_token: LLM generation in-progress (e.g. Business Agent writing JSON).
    // We show only the last partial line as a subtle progress indicator.
    eventSource.addEventListener('background_token', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      const chunk: string = data.text || '';
      setLastBgLine((prev) => {
        const combined = prev + chunk;
        // Keep only the text after the last newline (the current line being written)
        const lines = combined.split('\n');
        return lines[lines.length - 1].slice(-150);
      });
    });

    eventSource.addEventListener('gate', (e) => {
      const data = JSON.parse((e as MessageEvent).data) as GateData & { html: null };
      console.log(`[GATE ${elapsed()}]`);
      setStatusMessage('');
      setLastBgLine('');
      const wasRefining = isRefiningRef.current;
      isRefiningRef.current = false;
      setMessages((prev) => {
        const newMsg = {
          id: crypto.randomUUID(),
          role: 'assistant' as const,
          content: '',
          type: 'approval_gate' as const,
          gateData: data,
        };
        if (wasRefining) {
          // Replace the most recent gate message in-place
          const lastGateIdx = [...prev].map((m, i) => ({ m, i })).reverse().find(({ m }) => m.type === 'approval_gate')?.i;
          if (lastGateIdx !== undefined) {
            return prev.map((m, i) => i === lastGateIdx ? { ...newMsg, id: m.id } : m);
          }
        }
        return [...prev, newMsg];
      });
      setIsLoading(false);
      eventSource.close();
    });

    eventSource.addEventListener('complete', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      console.log(`[COMPLETE ${elapsed()}]`);
      setStreamingText(null);
      setStatusMessage('');
      setLastBgLine('');
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
      const data = JSON.parse((e as MessageEvent).data);
      console.error(`[ERROR ${elapsed()}]`, data.message);
      setStreamingText(null);
      setStatusMessage('');
      setLastBgLine('');
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
    setStatusMessage('');
    setStreamingText(null);
    setLastBgLine('');

    try {
      const formData = new FormData();
      formData.append('question', query);
      if (sessionId) formData.append('session_id', sessionId);

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

  const handleRun = async () => {
    if (!sessionId || isLoading) return;
    setIsLoading(true);
    setStatusMessage('');
    setStreamingText(null);
    setLastBgLine('');

    try {
      const formData = new FormData();
      formData.append('session_id', sessionId);
      const res = await fetch('http://localhost:5001/run', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.ok) {
        listenToStream(sessionId);
      } else {
        setIsLoading(false);
      }
    } catch (err) {
      console.error(err);
      setIsLoading(false);
    }
  };

  const handlePatch = useCallback(async (
    msgId: string,
    updates: Partial<Pick<GateData, 'where_clause' | 'system_prompt' | 'field_manifest'>>
  ) => {
    if (!sessionId) return;
    const res = await fetch('http://localhost:5001/patch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, ...updates }),
    });
    const { ok, data } = await res.json();
    if (ok) {
      setMessages(prev => prev.map(m =>
        m.id === msgId ? { ...m, gateData: { ...m.gateData!, ...data } } : m
      ));
    }
  }, [sessionId]);

  const handleRefine = useCallback((instruction: string) => {
    if (!sessionId || isLoading) return;
    isRefiningRef.current = true;
    setIsLoading(true);
    setStatusMessage('');
    setLastBgLine('');

    const formData = new FormData();
    formData.append('session_id', sessionId);
    formData.append('instruction', instruction);

    fetch('http://localhost:5001/refine', { method: 'POST', body: formData })
      .then(res => res.json())
      .then(data => {
        if (data.ok) listenToStream(sessionId);
        else { setIsLoading(false); isRefiningRef.current = false; }
      })
      .catch(() => { setIsLoading(false); isRefiningRef.current = false; });
  }, [sessionId, isLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  const renderMessageContent = (msg: Message) => {
    if (msg.type === 'approval_gate' && msg.gateData) {
      return (
        <GateCard
          msgId={msg.id}
          data={msg.gateData}
          isLoading={isLoading}
          onRun={handleRun}
          onPatch={handlePatch}
          onRefine={handleRefine}
        />
      );
    }

    if (msg.type === 'results') {
      return (
        <div className="space-y-5 w-full">
          {msg.charts && msg.charts.length > 0 && (
            <div className={cn('grid gap-4', msg.charts.length === 1 ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2')}>
              {msg.charts.map((c: any, i: number) => <ChartCard key={i} chart={c} />)}
            </div>
          )}
          <div className="prose prose-orange max-w-none text-on-surface">
            <ReactMarkdown>{msg.content}</ReactMarkdown>
          </div>
        </div>
      );
    }

    return (
      <div className="prose prose-orange max-w-none text-on-surface">
        <ReactMarkdown>{msg.content}</ReactMarkdown>
      </div>
    );
  };

  return (
    <div className="flex h-screen overflow-hidden bg-surface text-on-surface selection:bg-secondary-fixed">
      {/* Main Content Area */}
      <main className="flex-1 flex flex-col relative bg-surface-container-low overflow-hidden">

        {/* TopAppBar Component */}
        <header className="absolute top-0 right-0 left-0 z-50 bg-white/80 backdrop-blur-xl shadow-sm shadow-primary/5 px-6 py-3 flex justify-between items-center">
          <div className="flex items-center gap-4">
            <h1 className="font-headline font-black text-xl tracking-tight text-primary">Chi Explorer</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={async () => {
                await fetch('http://localhost:5001/reset', { method: 'POST' });
                setMessages([]);
                setSessionId(null);
              }}
              className="px-4 py-2 text-sm font-headline font-bold uppercase tracking-widest text-on-surface-variant hover:text-primary hover:bg-primary/5 rounded-full transition-colors"
            >
              Reset Session
            </button>
          </div>
        </header>

        {/* Scrollable Conversation / Empty Canvas */}
        <div className="flex-1 overflow-y-auto mt-[80px] pb-32">
          {messages.length === 0 ? (
            <section className="h-full flex flex-col items-center justify-center px-6 md:px-12">
              <div className="max-w-3xl w-full text-center space-y-8">
                {/* Branding Icon */}
                <div className="inline-flex w-16 h-16 rounded-full bg-gradient-to-br from-primary to-primary-container items-center justify-center shadow-2xl shadow-primary/30 mb-2">
                  <span className="material-symbols-outlined text-white text-3xl" style={{ fontVariationSettings: '"FILL" 1' }}>bolt</span>
                </div>

                {/* Welcoming Headline */}
                <div className="space-y-4">
                  <h2 className="text-4xl md:text-5xl lg:text-6xl font-headline font-black text-on-surface leading-tight">
                    Chi Explorer
                  </h2>
                  <p className="text-lg md:text-xl text-on-surface-variant max-w-2xl mx-auto font-medium opacity-80">
                    Ask a business question in plain English to get an AI-powered answer drawn from the actual content of your calls. Analyze scripts, trends, and customer behaviors at scale.
                  </p>
                </div>

                {/* Suggestion Chips */}
                <div className="flex flex-wrap justify-center gap-3 pt-4">
                  {[
                    'Which agents have the lowest CHI scores this month?',
                    'What objections are customers raising most often on Retention calls?',
                    'Are agents offering digital self-service options during calls?',
                  ].map(text => (
                    <button
                      key={text}
                      onClick={() => setInputMessage(text)}
                      className="px-5 py-2 rounded-full border border-outline-variant hover:bg-primary/5 hover:border-primary transition-all text-sm font-headline font-bold text-on-surface-variant hover:text-primary"
                    >
                      {text}
                    </button>
                  ))}
                </div>
              </div>
            </section>
          ) : (
            <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={cn(
                    'flex gap-4 fade-in',
                    msg.role === 'user' ? 'justify-end' : 'justify-start'
                  )}
                >
                  {msg.role === 'assistant' && (
                    <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary to-primary-container shrink-0 flex items-center justify-center shadow-lg shadow-primary/20">
                      <span className="material-symbols-outlined text-white text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>bolt</span>
                    </div>
                  )}
                  <div className={cn(
                    'rounded-3xl px-6 py-5',
                    msg.type === 'results' ? 'w-full' : 'max-w-[85%]',
                    msg.role === 'user'
                      ? 'bg-surface-container-highest text-on-surface rounded-br-sm shadow-sm'
                      : 'bg-surface-container-lowest text-on-surface border border-outline-variant/30 rounded-bl-sm shadow-[0_10px_40px_rgba(26,28,28,0.06)]'
                  )}>
                    {renderMessageContent(msg)}
                  </div>
                </div>
              ))}
              {/* Streaming summary bubble — appears token-by-token as Vision Agent writes */}
              {streamingText !== null && (
                <div className="flex gap-4 justify-start fade-in">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary to-primary-container shrink-0 flex items-center justify-center shadow-lg shadow-primary/20">
                    <span className="material-symbols-outlined text-white text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>bolt</span>
                  </div>
                  <div className="max-w-[85%] rounded-3xl px-6 py-5 bg-surface-container-lowest text-on-surface border border-outline-variant/30 rounded-bl-sm shadow-[0_10px_40px_rgba(26,28,28,0.06)]">
                    <div className="prose prose-orange max-w-none text-on-surface">
                      <ReactMarkdown>{streamingText}</ReactMarkdown>
                    </div>
                    {/* Blinking cursor */}
                    <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 animate-pulse align-middle" />
                  </div>
                </div>
              )}

              {/* Loading indicator with live status + background LLM stream hint */}
              {isLoading && (
                <div className="flex gap-4 justify-start fade-in pb-4">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary/30 to-primary-container/30 shrink-0 flex items-center justify-center">
                    <span className="material-symbols-outlined text-primary text-sm animate-spin" style={{ fontVariationSettings: '"FILL" 1' }}>progress_activity</span>
                  </div>
                  <div className="max-w-[85%] rounded-3xl px-6 py-4 bg-surface-container-lowest rounded-bl-sm border border-outline-variant/20 shadow-sm space-y-1.5">
                    {statusMessage ? (
                      <p className="text-sm text-on-surface-variant font-medium">{statusMessage}</p>
                    ) : (
                      <div className="space-y-2 w-52">
                        <div className="h-3 bg-surface-container-high rounded-full w-2/3 animate-pulse" />
                        <div className="h-3 bg-surface-container-high rounded-full w-4/5 animate-pulse" />
                      </div>
                    )}
                    {/* Secondary: last line being written by the LLM */}
                    {lastBgLine && (
                      <p className="text-xs text-neutral-400 font-mono truncate max-w-xs leading-relaxed">
                        {lastBgLine}
                        <span className="inline-block w-1 h-3 bg-neutral-300 ml-0.5 animate-pulse align-middle rounded-sm" />
                      </p>
                    )}
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* Bottom Input Bar */}
        <div className="absolute bottom-0 left-0 right-0 p-4 md:px-8 md:pb-6 md:pt-16 bg-gradient-to-t from-surface via-surface/95 to-transparent z-40">
          <div className="max-w-4xl mx-auto">
            <form
              onSubmit={handleSubmit}
              className="relative flex items-center gap-2 p-2 bg-white rounded-full shadow-lg shadow-primary/10 ring-1 ring-neutral-200"
            >
              <button type="button" className="p-2 text-neutral-400 hover:text-primary transition-colors">
                <span className="material-symbols-outlined text-xl">attach_file</span>
              </button>
              <textarea
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit(e as any);
                  }
                }}
                className="w-full border-0 bg-transparent py-2 px-1 focus:ring-0 text-on-surface placeholder:text-neutral-400 text-base resize-none outline-none"
                placeholder="Message Chi Explorer..."
                rows={1}
                disabled={isLoading}
              />
              <button
                type="submit"
                disabled={isLoading || !inputMessage.trim()}
                className="p-3 bg-primary text-white rounded-full flex items-center justify-center hover:bg-surface-tint active:scale-95 transition-all shadow-md shadow-primary/30 disabled:opacity-50 disabled:hover:bg-primary"
              >
                <span className="material-symbols-outlined text-base" style={{ fontVariationSettings: '"FILL" 1' }}>send</span>
              </button>
            </form>
          </div>
        </div>

      </main>
    </div>
  );
}
