import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Navbar } from './Navbar';
import { renderWithProviders } from '@/test/render';

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Navbar', () => {
  it('renders the brand and nav links', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', checks: [] })));
    renderWithProviders(<Navbar />);

    expect(screen.getByText('Argus Agent')).toBeInTheDocument();
    expect(screen.getByText('Execuções')).toBeInTheDocument();
    expect(screen.getByText('Configuração')).toBeInTheDocument();
  });

  it('shows the degraded (warn) health dot for a 503 response instead of hiding it', async () => {
    // GET /api/health responde 503 de propósito quando degradado — a
    // bolinha precisa refletir isso (amarela), não desaparecer/ficar presa
    // no estado anterior por a query "falhar" (achado ao vivo).
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ status: 'degraded', checks: [{ name: 'appium', ok: false, detail: 'not found in PATH' }] }, 503))
    );
    renderWithProviders(<Navbar />);

    expect(await screen.findByTitle('Ambiente degradado')).toBeInTheDocument();
  });

  it('toggles the theme when the button is clicked', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', checks: [] })));
    document.documentElement.dataset.theme = 'light';
    renderWithProviders(<Navbar />);

    await user.click(screen.getByRole('button', { name: 'Alternar tema' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
  });
});
