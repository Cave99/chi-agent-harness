export type FieldDef = {
  name: string;
  type: 'numerical' | 'categorical' | 'boolean' | 'freeform_text' | 'date';
  description: string;
  range?: [number, number];
};

export type GateData = {
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

export type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  type?: 'approval_gate' | 'results' | 'text';
  html?: string;
  charts?: any[];
  gateData?: GateData;
};
