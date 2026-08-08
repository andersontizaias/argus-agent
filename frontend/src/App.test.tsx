import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { renderWithProviders } from '@/test/render';

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('App', () => {
  it('redirects the root route to the runs list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path.startsWith('/api/runs')) return Promise.resolve(jsonResponse({ runs: [], total: 0, limit: 20, offset: 0 }));
        return Promise.resolve(jsonResponse({ status: 'ok', checks: [] }));
      })
    );
    renderWithProviders(<App />, { route: '/' });
    expect(await screen.findByText('Nenhuma execução ainda.')).toBeInTheDocument();
  });

  it('renders the config page at /config', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', checks: [] })));
    renderWithProviders(<App />, { route: '/config' });
    expect(await screen.findByText('Chaves de provider LLM e endpoints locais (Ollama / custom).')).toBeInTheDocument();
  });

  it('renders the new run page at /runs/new', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', checks: [] })));
    renderWithProviders(<App />, { route: '/runs/new' });
    expect(await screen.findByText('Configure o alvo e o script BDD que o Argus vai executar.')).toBeInTheDocument();
  });

  it('redirects unknown routes to the runs list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path.startsWith('/api/runs')) return Promise.resolve(jsonResponse({ runs: [], total: 0, limit: 20, offset: 0 }));
        return Promise.resolve(jsonResponse({ status: 'ok', checks: [] }));
      })
    );
    renderWithProviders(<App />, { route: '/rota-que-nao-existe' });
    expect(await screen.findByText('Nenhuma execução ainda.')).toBeInTheDocument();
  });
});
