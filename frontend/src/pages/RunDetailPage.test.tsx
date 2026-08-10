import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RunDetailPage } from './RunDetailPage';
import { renderWithProviders } from '@/test/render';
import type { RunDetail } from '@/types/api';

// RunDetailPage lê o :runId via useParams — precisa de uma Route de verdade
// casando o path, não só um MemoryRouter solto (que deixaria runId undefined).
function renderRunDetail(route: string) {
  return renderWithProviders(<Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes>, { route });
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener() {}
  close() {}
}

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

function makeRunDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 'run-1',
    platform: 'web',
    app_url: 'https://example.com',
    binary_url: null,
    status: 'running',
    error: null,
    cancel_requested: false,
    llm_provider: 'anthropic',
    llm_model: 'claude-3-5-haiku-latest',
    scenarios_total: 1,
    scenarios_passed: 0,
    scenarios_failed: 0,
    tokens_in: 0,
    tokens_out: 0,
    cost_usd: 0.01,
    created_at: '2026-01-01T00:00:00',
    started_at: '2026-01-01T00:00:01',
    finished_at: null,
    bdd_script: '...',
    test_data_keys: [],
    scenarios: [
      {
        id: 'sc-1',
        position: 0,
        name: 'Login válido',
        tags: [],
        status: 'running',
        failure_reason: null,
        started_at: null,
        finished_at: null,
        steps: [
          {
            id: 'step-1',
            position: 0,
            keyword: 'Dado',
            text: 'que estou na página',
            status: 'passed',
            error: null,
            attempts: 1,
            duration_ms: 500,
            evidences: [],
          },
        ],
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('RunDetailPage', () => {
  it('shows a loading state before the run data arrives', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    renderRunDetail('/runs/run-1');
    expect(screen.getByText('Carregando execução...')).toBeInTheDocument();
  });

  it('renders scenarios and steps for a running run', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(makeRunDetail())));
    renderRunDetail('/runs/run-1');

    expect(await screen.findByText('Login válido')).toBeInTheDocument();
    expect(screen.getByText('que estou na página')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeInTheDocument();
  });

  it('does not show cancel/report actions inconsistently for a terminal run', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(makeRunDetail({ status: 'passed' }))));
    renderRunDetail('/runs/run-1');

    await screen.findByText('Login válido');
    expect(screen.queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ver relatório' })).toHaveAttribute('href', '/api/runs/run-1/report.html');
    expect(screen.getByRole('link', { name: 'Exportar PDF' })).toHaveAttribute('href', '/api/runs/run-1/report.pdf');
    expect(screen.getByRole('link', { name: 'Baixar artefatos (.zip)' })).toHaveAttribute('href', '/api/runs/run-1/artifacts.zip');
  });

  it('shows the run-level error message when present', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(makeRunDetail({ status: 'error', error: 'Falha ao provisionar o navegador.' }))));
    renderRunDetail('/runs/run-1');
    expect(await screen.findByText('Falha ao provisionar o navegador.')).toBeInTheDocument();
  });

  it('cancels the run when the cancel button is clicked', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((path: string, opts?: RequestInit) => {
      if (path === '/api/runs/run-1/cancel') return Promise.resolve(jsonResponse({ id: 'run-1', cancel_requested: true }));
      if (path.startsWith('/api/runs/run-1') && !opts) return Promise.resolve(jsonResponse(makeRunDetail()));
      return Promise.resolve(jsonResponse(makeRunDetail()));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderRunDetail('/runs/run-1');

    const cancelButton = await screen.findByRole('button', { name: 'Cancelar' });
    await user.click(cancelButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/runs/run-1/cancel', expect.objectContaining({ method: 'POST' }));
    });
  });

  it('shows a placeholder message when there are no scenarios yet', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(makeRunDetail({ scenarios: [], status: 'provisioning' }))));
    renderRunDetail('/runs/run-1');
    expect(await screen.findByText('Ainda não há cenários — a run está sendo processada.')).toBeInTheDocument();
  });
});
