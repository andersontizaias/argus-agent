import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConfigPage } from './ConfigPage';
import { renderWithProviders } from '@/test/render';

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

const BASE_CONFIG = {
  anthropic_api_key: '',
  openai_api_key: '',
  gemini_api_key: '',
  groq_api_key: '',
  ollama_base_url: '',
  custom_llm_api_key: '',
  custom_llm_base_url: '',
  default_llm_provider: '',
  default_llm_model: '',
};

const BASE_HEALTH = { status: 'ok', checks: [{ name: 'database', ok: true, detail: 'SQLite ok' }] };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ConfigPage', () => {
  it('loads the saved config and shows a masked secret', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path === '/api/config') return Promise.resolve(jsonResponse({ ...BASE_CONFIG, anthropic_api_key: 'sk-a****5678' }));
        if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
        return Promise.resolve(jsonResponse({}));
      })
    );
    renderWithProviders(<ConfigPage />);

    expect(await screen.findByDisplayValue('sk-a****5678')).toBeInTheDocument();
  });

  it('shows environment health badges', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
        if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
        return Promise.resolve(jsonResponse({}));
      })
    );
    renderWithProviders(<ConfigPage />);

    expect(await screen.findByText(/database/)).toBeInTheDocument();
  });

  it('still shows environment health badges when the environment is degraded (503)', async () => {
    // GET /api/health responde 503 de propósito quando degradado — o card
    // "Ambiente" precisa aparecer mesmo assim, é justamente quando importa
    // mostrar qual checagem falhou (achado ao vivo: sumia da tela).
    const degradedHealth = {
      status: 'degraded',
      checks: [
        { name: 'database', ok: true, detail: 'SQLite ok' },
        { name: 'appium', ok: false, detail: 'not found in PATH' },
      ],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
        if (path === '/api/health') return Promise.resolve(jsonResponse(degradedHealth, 503));
        return Promise.resolve(jsonResponse({}));
      })
    );
    renderWithProviders(<ConfigPage />);

    expect(await screen.findByText(/database/)).toBeInTheDocument();
    expect(await screen.findByText(/appium/)).toBeInTheDocument();
  });

  it('saves the config and shows a success toast', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((path: string, opts?: RequestInit) => {
      if (path === '/api/config' && opts?.method === 'POST') return Promise.resolve(jsonResponse({ status: 'ok', message: 'saved' }));
      if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
      if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<ConfigPage />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Salvar' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/config', expect.objectContaining({ method: 'POST' }));
    });
  });

  it('lets the user type into every field, including base URL for providers that need one', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
        if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
        return Promise.resolve(jsonResponse({}));
      })
    );
    renderWithProviders(<ConfigPage />);

    const apiKeyInputs = await screen.findAllByPlaceholderText('Chave de API');
    await user.type(apiKeyInputs[0], 'sk-ant-xyz');
    expect(apiKeyInputs[0]).toHaveValue('sk-ant-xyz');

    const baseUrlInputs = screen.getAllByPlaceholderText('Base URL');
    await user.type(baseUrlInputs[0], 'http://localhost:11434');
    expect(baseUrlInputs[0]).toHaveValue('http://localhost:11434');

    const providerInput = screen.getByPlaceholderText('anthropic');
    await user.type(providerInput, 'anthropic');
    expect(providerInput).toHaveValue('anthropic');

    const modelInput = screen.getByPlaceholderText('claude-3-5-haiku-latest');
    await user.type(modelInput, 'claude-3-5-haiku-latest');
    expect(modelInput).toHaveValue('claude-3-5-haiku-latest');
  });

  it('does not crash when saving fails (error handled via toast)', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((path: string, opts?: RequestInit) => {
      if (path === '/api/config' && opts?.method === 'POST') return Promise.resolve(jsonResponse({ error: 'falhou' }, 400));
      if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
      if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<ConfigPage />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Salvar' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/config', expect.objectContaining({ method: 'POST' }));
    });
    expect(screen.getByRole('button', { name: 'Salvar' })).toBeInTheDocument();
  });

  it('shows the provider error message when the test call fails', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
        if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
        if (path.startsWith('/api/config/test-llm-provider/')) return Promise.resolve(jsonResponse({ error: 'não configurado' }, 400));
        return Promise.resolve(jsonResponse({}));
      })
    );
    renderWithProviders(<ConfigPage />);

    const buttons = await screen.findAllByRole('button', { name: 'Testar provider' });
    await user.click(buttons[0]);

    expect(await screen.findByText('não configurado')).toBeInTheDocument();
  });

  it('saves the current form values before testing (not just what was already saved)', async () => {
    // Bug real reportado pelo usuário: digitar uma chave/URL nova e clicar
    // em "Testar provider" sem clicar em "Salvar" antes sempre dava "não
    // configurado", porque o teste lia só o que já estava persistido.
    const user = userEvent.setup();
    const callOrder: string[] = [];
    const fetchMock = vi.fn((path: string, opts?: RequestInit) => {
      if (path === '/api/config' && opts?.method === 'POST') {
        callOrder.push('save');
        return Promise.resolve(jsonResponse({ status: 'ok', message: 'saved' }));
      }
      if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
      if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
      if (path.startsWith('/api/config/test-llm-provider/')) {
        callOrder.push('test');
        return Promise.resolve(jsonResponse({ ok: true, provider: 'anthropic', model: 'claude-3-5-haiku-latest' }));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<ConfigPage />);

    const apiKeyInputs = await screen.findAllByPlaceholderText('Chave de API');
    await user.type(apiKeyInputs[0], 'sk-ant-recem-digitada');

    const buttons = screen.getAllByRole('button', { name: 'Testar provider' });
    await user.click(buttons[0]);

    await waitFor(() => expect(callOrder).toEqual(['save', 'test']));
    expect(await screen.findByText('Conexão ok')).toBeInTheDocument();
  });

  it('tests a provider and shows the result', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
        if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
        if (path.startsWith('/api/config/test-llm-provider/')) {
          return Promise.resolve(jsonResponse({ ok: true, provider: 'anthropic', model: 'claude-3-5-haiku-latest' }));
        }
        return Promise.resolve(jsonResponse({}));
      })
    );
    renderWithProviders(<ConfigPage />);

    const buttons = await screen.findAllByRole('button', { name: 'Testar provider' });
    await user.click(buttons[0]);

    expect(await screen.findByText('Conexão ok')).toBeInTheDocument();
  });

  it('lists existing API keys', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
        if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
        if (path === '/api/api-keys') {
          return Promise.resolve(jsonResponse([
            { id: 'k1', name: 'pipeline-ci', prefix: 'abcd1234', created_at: '2026-01-01T00:00:00', last_used_at: null, revoked: false },
          ]));
        }
        return Promise.resolve(jsonResponse({}));
      })
    );
    renderWithProviders(<ConfigPage />);
    expect(await screen.findByText('pipeline-ci')).toBeInTheDocument();
    expect(screen.getByText('argus_abcd1234_...')).toBeInTheDocument();
  });

  it('creates an API key and shows the full value once', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string, opts?: RequestInit) => {
        if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
        if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
        if (path === '/api/api-keys' && opts?.method === 'POST') {
          return Promise.resolve(jsonResponse({
            id: 'k1', name: 'pipeline-ci', prefix: 'abcd1234', key: 'argus_abcd1234_supersecretvalue', created_at: '2026-01-01T00:00:00',
          }));
        }
        if (path === '/api/api-keys') return Promise.resolve(jsonResponse([]));
        return Promise.resolve(jsonResponse({}));
      })
    );
    renderWithProviders(<ConfigPage />);

    await user.type(await screen.findByPlaceholderText('Nome da chave (ex.: pipeline-ci)'), 'pipeline-ci');
    await user.click(screen.getByRole('button', { name: 'Criar chave' }));

    expect(await screen.findByText('argus_abcd1234_supersecretvalue')).toBeInTheDocument();
    expect(screen.getByText('Copie agora — essa chave não será mostrada de novo.')).toBeInTheDocument();
  });

  it('revokes an API key', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((path: string, opts?: RequestInit) => {
      if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
      if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
      if (path === '/api/api-keys/k1' && opts?.method === 'DELETE') return Promise.resolve(jsonResponse({ status: 'ok' }));
      if (path === '/api/api-keys') {
        return Promise.resolve(jsonResponse([
          { id: 'k1', name: 'pipeline-ci', prefix: 'abcd1234', created_at: '2026-01-01T00:00:00', last_used_at: null, revoked: false },
        ]));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<ConfigPage />);

    const revokeButton = await screen.findByRole('button', { name: 'Revogar' });
    await user.click(revokeButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/api-keys/k1', expect.objectContaining({ method: 'DELETE' }));
    });
  });

  it('shows an empty state when there are no API keys', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        if (path === '/api/config') return Promise.resolve(jsonResponse(BASE_CONFIG));
        if (path === '/api/health') return Promise.resolve(jsonResponse(BASE_HEALTH));
        if (path === '/api/api-keys') return Promise.resolve(jsonResponse([]));
        return Promise.resolve(jsonResponse({}));
      })
    );
    renderWithProviders(<ConfigPage />);
    expect(await screen.findByText('Nenhuma chave criada ainda.')).toBeInTheDocument();
  });
});
