import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RunsListPage } from './RunsListPage';
import { renderWithProviders } from '@/test/render';
import type { RunSummary } from '@/types/api';

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
}

function makeRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: 'run-1',
    platform: 'web',
    mode: 'execute',
    app_url: 'https://example.com',
    binary_url: null,
    status: 'passed',
    error: null,
    cancel_requested: false,
    llm_provider: 'anthropic',
    llm_model: 'claude-3-5-haiku-latest',
    scenarios_total: 3,
    scenarios_passed: 2,
    scenarios_failed: 1,
    tokens_in: 0,
    tokens_out: 0,
    cost_usd: 0,
    max_actions: 25,
    generated_bdd_script: null,
    created_at: '2026-01-01T00:00:00',
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('RunsListPage', () => {
  it('shows an empty state when there are no runs', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ runs: [], total: 0, limit: 20, offset: 0 })));
    renderWithProviders(<RunsListPage />);
    expect(await screen.findByText('Nenhuma execução ainda.')).toBeInTheDocument();
  });

  it('lists runs with status and scenario counts', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ runs: [makeRun()], total: 1, limit: 20, offset: 0 }))
    );
    renderWithProviders(<RunsListPage />);
    const link = await screen.findByRole('link', { name: /example\.com/ });
    expect(link).toHaveTextContent('passed');
    expect(screen.getByText('2/3 cenários')).toBeInTheDocument();
  });

  it('requests the selected status filter', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ runs: [], total: 0, limit: 20, offset: 0 }));
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<RunsListPage />);

    await user.selectOptions(screen.getAllByRole('combobox')[0], 'failed');

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(urls.some((url) => url.includes('status=failed'))).toBe(true);
    });
  });

  it('disables pagination controls appropriately', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ runs: [makeRun()], total: 25, limit: 20, offset: 0 }))
    );
    renderWithProviders(<RunsListPage />);

    const prevButton = await screen.findByRole('button', { name: 'Anterior' });
    const nextButton = screen.getByRole('button', { name: 'Próxima' });
    expect(prevButton).toBeDisabled();
    expect(nextButton).not.toBeDisabled();
  });

  it('requests the selected platform filter', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ runs: [], total: 0, limit: 20, offset: 0 }));
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<RunsListPage />);

    await user.selectOptions(screen.getAllByRole('combobox')[1], 'android');

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(urls.some((url) => url.includes('platform=android'))).toBe(true);
    });
  });

  it('advances to the next page and back when pagination buttons are clicked', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ runs: [makeRun()], total: 25, limit: 20, offset: 0 }));
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<RunsListPage />);

    const nextButton = await screen.findByRole('button', { name: 'Próxima' });
    await user.click(nextButton);

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(urls.some((url) => url.includes('offset=20'))).toBe(true);
    });

    const prevButton = screen.getByRole('button', { name: 'Anterior' });
    await user.click(prevButton);

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(urls.some((url) => url.includes('offset=0'))).toBe(true);
    });
  });

  it('has a link to create a new run', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ runs: [], total: 0, limit: 20, offset: 0 })));
    renderWithProviders(<RunsListPage />);
    expect(await screen.findByRole('link', { name: 'Nova Execução' })).toHaveAttribute('href', '/runs/new');
  });
});
