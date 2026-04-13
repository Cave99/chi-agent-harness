import { useState } from 'react';

export function ImproveInput({ placeholder, prefix, onRefine, isLoading }: {
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
