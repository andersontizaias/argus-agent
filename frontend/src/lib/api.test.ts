import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api', () => {
  it('getHealth requests /api/health', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', checks: [] })));
    const result = await api.getHealth();
    expect(result.status).toBe('ok');
    expect(fetch).toHaveBeenCalledWith('/api/health', expect.objectContaining({ credentials: 'include' }));
  });

  it('getHealth returns the body even when the response is a 503 (degraded)', async () => {
    // /api/health responde 503 de propósito quando degradado — diferente
    // de todo outro endpoint, o corpo (o detalhe de cada checagem) é
    // informação válida nesse caso, não um erro a ser descartado.
    const checks = [{ name: 'appium', ok: false, detail: 'not found in PATH' }];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'degraded', checks }, 503)));
    const result = await api.getHealth();
    expect(result.status).toBe('degraded');
    expect(result.checks).toEqual(checks);
  });

  it('saveConfig posts the payload as JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', message: 'saved' })));
    await api.saveConfig({ anthropic_api_key: 'sk-ant-123' });
    expect(fetch).toHaveBeenCalledWith(
      '/api/config',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ anthropic_api_key: 'sk-ant-123' }) })
    );
  });

  it('throws ApiError with the server-provided message on failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ error: 'boom' }, 400)));
    await expect(api.getConfig()).rejects.toBeInstanceOf(ApiError);
    await expect(api.getConfig()).rejects.toThrow('boom');
  });

  it('falls back to a generic message when the error body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => { throw new Error('not json'); } })
    );
    await expect(api.getConfig()).rejects.toThrow('Requisição para /api/config falhou (500)');
  });
});
