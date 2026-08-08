import type { HealthResponse, LlmProviderTestResult, ProjectConfig } from '@/types/api';

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
};

export { ApiError };
