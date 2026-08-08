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

export interface RunsFilter {
  status?: string;
  platform?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  getHealth: () => request<HealthResponse>('/api/health'),
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
  artifactsZipUrl: (runId: string) => `/api/runs/${runId}/artifacts.zip`,
  evidenceUrl: (evidenceId: string) => `/api/evidences/${evidenceId}`,

  listApiKeys: () => request<ApiKeySummary[]>('/api/api-keys'),
  createApiKey: (name: string) =>
    request<ApiKeyCreated>('/api/api-keys', { method: 'POST', body: JSON.stringify({ name }) }),
  revokeApiKey: (keyId: string) =>
    request<{ status: string }>(`/api/api-keys/${keyId}`, { method: 'DELETE' }),
};

export { ApiError };
