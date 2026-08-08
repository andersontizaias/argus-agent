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
  it('redirects the root route to /runs', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', checks: [] })));
    renderWithProviders(<App />, { route: '/' });
    expect(await screen.findByText('Em construção — chega nas próximas fases do plano.')).toBeInTheDocument();
  });

  it('renders the config page at /config', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', checks: [] })));
    renderWithProviders(<App />, { route: '/config' });
    expect(await screen.findByText('Chaves de provider LLM e endpoints locais (Ollama / custom).')).toBeInTheDocument();
  });
});
