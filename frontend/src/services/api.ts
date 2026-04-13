const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5001';

export const API_ENDPOINTS = {
  CHAT: `${API_BASE_URL}/chat`,
  REFINE: `${API_BASE_URL}/refine`,
  PATCH: `${API_BASE_URL}/patch`,
  VALIDATE_SQL: `${API_BASE_URL}/validate-sql`,
  RUN: `${API_BASE_URL}/run`,
  STREAM: (sid: string) => `${API_BASE_URL}/stream/${sid}`,
  RESET: `${API_BASE_URL}/reset`,
};
