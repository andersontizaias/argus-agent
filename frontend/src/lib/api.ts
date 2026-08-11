import type {
  ApiKeyCreated,
  ApiKeySummary,
  HealthResponse,
  LlmProviderTestResult,
  ProjectConfig,
  RunCreateRequest,
  RunDetail,
  RunSummary,
  RunsPage,
} from '@/types/api';

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.error || `Requisição para ${path} falhou (${res.status})`);
  }
  return res.json();
}

/** GET /api/health usa o status HTTP (200 ok / 503 degraded) de propósito,
 * pra quem monitora de fora conseguir detectar degradação pelo código —
 * mas o corpo É a informação útil nos dois casos (o detalhe de cada
 * checagem). `request()` trataria o 503 como erro e descartaria esse
 * corpo, escondendo o card "Ambiente" da UI bem na hora que mais importa
 * mostrar o que está degradado (achado ao vivo). Não passa pelo helper
 * genérico por isso. */
async function getHealth(): Promise<HealthResponse> {
  const res = await fetch('/api/health', { headers: { 'Content-Type': 'application/json' }, credentials: 'include' });
  return res.json();
}

/** Sobe um .apk/.aab/.ipa/.zip local pra tela de Nova Execução — devolve o
 * caminho absoluto onde o backend guardou o arquivo (mesma máquina, já que
 * o Argus roda nativamente), pra usar como `binary_url` no POST /api/runs.
 * FormData em vez de JSON: não passa por `request()` porque o
 * `Content-Type: multipart/form-data; boundary=...` tem que ser definido
 * pelo próprio fetch (o boundary depende do conteúdo) — um header fixo
 * quebraria o parsing do multipart no FastAPI. */
async function uploadBinary(file: File): Promise<{ path: string; filename: string; size: number }> {
  const body = new FormData();
  body.append('file', file);
  const res = await fetch('/api/binaries/upload', { method: 'POST', credentials: 'include', body });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new ApiError(res.status, errBody.error || `Upload falhou (${res.status})`);
  }
  return res.json();
}

export interface RunsFilter {
  status?: string;
  platform?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  getHealth,
  uploadBinary,
  getConfig: () => request<ProjectConfig>('/api/config'),
  saveConfig: (payload: Partial<ProjectConfig>) =>
    request<{ status: string; message: string }>('/api/config', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  testLlmProvider: (providerId: string) =>
    request<LlmProviderTestResult>(`/api/config/test-llm-provider/${providerId}`, { method: 'POST' }),

  createRun: (payload: RunCreateRequest) =>
    request<RunSummary>('/api/runs', { method: 'POST', body: JSON.stringify(payload) }),
  listRuns: (filter: RunsFilter = {}) => {
    const query = new URLSearchParams();
    query.set('limit', String(filter.limit ?? 20));
    query.set('offset', String(filter.offset ?? 0));
    if (filter.status) query.set('status', filter.status);
    if (filter.platform) query.set('platform', filter.platform);
    return request<RunsPage>(`/api/runs?${query.toString()}`);
  },
  getRun: (runId: string) => request<RunDetail>(`/api/runs/${runId}`),
  cancelRun: (runId: string) =>
    request<{ id: string; cancel_requested: boolean }>(`/api/runs/${runId}/cancel`, { method: 'POST' }),
  reportUrl: (runId: string) => `/api/runs/${runId}/report.html`,
  reportJsonUrl: (runId: string) => `/api/runs/${runId}/report`,
  reportPdfUrl: (runId: string) => `/api/runs/${runId}/report.pdf`,
  artifactsZipUrl: (runId: string) => `/api/runs/${runId}/artifacts.zip`,
  evidenceUrl: (evidenceId: string) => `/api/evidences/${evidenceId}`,

  listApiKeys: () => request<ApiKeySummary[]>('/api/api-keys'),
  createApiKey: (name: string) =>
    request<ApiKeyCreated>('/api/api-keys', { method: 'POST', body: JSON.stringify({ name }) }),
  revokeApiKey: (keyId: string) =>
    request<{ status: string }>(`/api/api-keys/${keyId}`, { method: 'DELETE' }),
};

export { ApiError };
