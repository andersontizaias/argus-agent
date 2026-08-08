import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Navbar } from './Navbar';
import { renderWithProviders } from '@/test/render';

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
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

  it('toggles the theme when the button is clicked', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', checks: [] })));
    document.documentElement.dataset.theme = 'light';
    renderWithProviders(<Navbar />);

    await user.click(screen.getByRole('button', { name: 'Alternar tema' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
  });
});
