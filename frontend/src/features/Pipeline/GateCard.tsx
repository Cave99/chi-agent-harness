import { useState, useEffect } from 'react';
import type { GateData } from '../../types';
import { cn, TYPE_DISPLAY, TYPE_COLOUR } from '../../services/utils';
import { Modal } from '../../components/Modal';
import { ImproveInput } from '../../components/ImproveInput';
import { API_ENDPOINTS } from '../../services/api';

type GateCardProps = {
  msgId: string;
  data: GateData;
  isLoading: boolean;
  onRun: () => void;
  onPatch: (msgId: string, updates: Partial<Pick<GateData, 'where_clause' | 'system_prompt' | 'field_manifest'>>) => Promise<void>;
  onRefine: (instruction: string) => void;
};

export function GateCard({ msgId, data, isLoading, onRun, onPatch, onRefine }: GateCardProps) {
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
      const res = await fetch(API_ENDPOINTS.VALIDATE_SQL, {
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
            <div className="flex_gap-2 mt-3 justify-end">
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
