import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NewRunPage } from './NewRunPage';
import { renderWithProviders } from '@/test/render';
import type { ProjectConfig } from '@/types/api';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateMock };
});

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

function fakeConfig(overrides: Partial<ProjectConfig> = {}): ProjectConfig {
  return {
    anthropic_api_key: '', openai_api_key: '', gemini_api_key: '', groq_api_key: '',
    ollama_api_key: '', ollama_base_url: '', ollama_timeout_seconds: '',
    custom_llm_api_key: '', custom_llm_base_url: '',
    default_llm_provider: '', default_llm_model: '', retention_days: '30',
    ...overrides,
  };
}

/** Mocka fetch respondendo /api/config com `config` e qualquer outra
 * chamada com um corpo vazio — usado pelos testes do dropdown de provider,
 * que dependem do GET /api/config disparado no carregamento da página. */
function stubFetchWithConfig(config: ProjectConfig) {
  const fetchMock = vi.fn((path: string) => {
    if (path === '/api/config') return Promise.resolve(jsonResponse(config));
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  navigateMock.mockClear();
});

describe('NewRunPage', () => {
  it('shows the app URL field for the web platform by default', async () => {
    renderWithProviders(<NewRunPage />);
    expect(screen.getByLabelText('URL da aplicação')).toBeInTheDocument();
    expect(screen.queryByLabelText('URL do binário')).not.toBeInTheDocument();
  });

  it('switches to binary fields when platform is android', async () => {
    const user = userEvent.setup();
    renderWithProviders(<NewRunPage />);
    await user.selectOptions(screen.getByLabelText('Plataforma'), 'android');
    expect(screen.getByLabelText('URL do binário')).toBeInTheDocument();
    expect(screen.getByLabelText('Nome do secret de autenticação')).toBeInTheDocument();
    expect(screen.queryByLabelText('URL da aplicação')).not.toBeInTheDocument();
  });

  it('shows an error for invalid JSON test data instead of submitting', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<NewRunPage />);

    await user.type(screen.getByLabelText('URL da aplicação'), 'https://example.com');
    await user.type(screen.getByPlaceholderText(/# language: pt/), 'Funcionalidade: X');
    await user.clear(screen.getByLabelText('Massa de testes (JSON)'));
    await screen.getByLabelText('Massa de testes (JSON)').focus();
    await user.paste('{not valid json');
    await user.click(screen.getByRole('button', { name: 'Criar execução' }));

    expect(await screen.findByText('Massa de testes não é um JSON válido.')).toBeInTheDocument();
    // A página busca /api/config no carregamento (pro dropdown de provider)
    // — o que não pode acontecer é criar a run com massa de testes inválida.
    expect(fetchMock).not.toHaveBeenCalledWith('/api/runs', expect.anything());
  });

  it('creates a run and navigates to its detail page on success', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((path: string) => {
      if (path === '/api/runs') return Promise.resolve(jsonResponse({ id: 'run-123', status: 'queued' }));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<NewRunPage />);

    await user.type(screen.getByLabelText('URL da aplicação'), 'https://example.com');
    await user.type(screen.getByPlaceholderText(/# language: pt/), 'Funcionalidade: X');
    await user.click(screen.getByRole('button', { name: 'Criar execução' }));

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/runs/run-123'));
    expect(fetchMock).toHaveBeenCalledWith('/api/runs', expect.objectContaining({ method: 'POST' }));
  });

  it('shows the server error message when creation fails', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ error: 'Nenhum provider LLM configurado.' }, 400)));
    renderWithProviders(<NewRunPage />);

    await user.type(screen.getByLabelText('URL da aplicação'), 'https://example.com');
    await user.type(screen.getByPlaceholderText(/# language: pt/), 'Funcionalidade: X');
    await user.click(screen.getByRole('button', { name: 'Criar execução' }));

    expect(await screen.findByText('Nenhum provider LLM configurado.')).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('rejects test data that is a JSON array instead of an object', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({})));
    renderWithProviders(<NewRunPage />);

    await user.type(screen.getByLabelText('URL da aplicação'), 'https://example.com');
    await user.type(screen.getByPlaceholderText(/# language: pt/), 'Funcionalidade: X');
    await user.clear(screen.getByLabelText('Massa de testes (JSON)'));
    await screen.getByLabelText('Massa de testes (JSON)').focus();
    await user.paste('[1,2,3]');
    await user.click(screen.getByRole('button', { name: 'Criar execução' }));

    expect(await screen.findByText('Massa de testes não é um JSON válido.')).toBeInTheDocument();
  });

  it('fills the BDD script field when uploading a .feature file', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({})));
    renderWithProviders(<NewRunPage />);

    const file = new File(['Funcionalidade: Upload de arquivo'], 'login.feature', { type: 'text/plain' });
    await user.upload(screen.getByLabelText('Enviar arquivo (.feature)'), file);

    expect(await screen.findByDisplayValue('Funcionalidade: Upload de arquivo')).toBeInTheDocument();
  });

  it('fills the test data field when uploading a .json file', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({})));
    renderWithProviders(<NewRunPage />);

    const file = new File(['{"usuario_valido": "standard_user"}'], 'massa.json', { type: 'application/json' });
    await user.upload(screen.getByLabelText('Enviar arquivo (.json)'), file);

    expect(await screen.findByDisplayValue('{"usuario_valido": "standard_user"}')).toBeInTheDocument();
  });

  it('uploads a local binary file and fills the binary URL field with the returned path', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((path: string) => {
      if (path === '/api/binaries/upload') {
        return Promise.resolve(
          jsonResponse({ path: '/Users/dev/.argus/uploads/abc123/app-debug.apk', filename: 'app-debug.apk', size: 42 })
        );
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<NewRunPage />);

    await user.selectOptions(screen.getByLabelText('Plataforma'), 'android');
    const file = new File(['conteudo-fake'], 'app-debug.apk', { type: 'application/vnd.android.package-archive' });
    await user.upload(screen.getByLabelText('Enviar arquivo local'), file);

    await waitFor(() => {
      expect(screen.getByLabelText('URL do binário')).toHaveValue('/Users/dev/.argus/uploads/abc123/app-debug.apk');
    });
    expect(fetchMock).toHaveBeenCalledWith('/api/binaries/upload', expect.objectContaining({ method: 'POST' }));
  });

  it('rejects a .aab file client-side without uploading it', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);
    renderWithProviders(<NewRunPage />);

    await user.selectOptions(screen.getByLabelText('Plataforma'), 'android');
    const file = new File(['conteudo-fake'], 'app.aab', { type: 'application/octet-stream' });
    await user.upload(screen.getByLabelText('Enviar arquivo local'), file);

    expect(screen.getByLabelText('URL do binário')).toHaveValue('');
    expect(fetchMock).not.toHaveBeenCalledWith('/api/binaries/upload', expect.anything());
  });

  it('accepts .ipa/.zip for iOS and .apk/.aab for Android in the file picker', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({})));
    renderWithProviders(<NewRunPage />);

    await user.selectOptions(screen.getByLabelText('Plataforma'), 'android');
    expect(screen.getByLabelText('Enviar arquivo local')).toHaveAttribute('accept', '.apk,.aab');

    await user.selectOptions(screen.getByLabelText('Plataforma'), 'ios');
    expect(screen.getByLabelText('Enviar arquivo local')).toHaveAttribute('accept', '.ipa,.zip');
  });

  it('disables providers without credentials configured in the dropdown', async () => {
    stubFetchWithConfig(fakeConfig({ anthropic_api_key: 'sk-a****' }));
    renderWithProviders(<NewRunPage />);

    const select = await screen.findByLabelText<HTMLSelectElement>('Provider default');
    await waitFor(() => {
      expect(select.querySelector('option[value="anthropic"]')).not.toBeDisabled();
    });
    expect(select.querySelector('option[value="openai"]')).toBeDisabled();
    expect(select.querySelector('option[value="groq"]')).toBeDisabled();
  });

  it('auto-fills the model field with the configured default when picking that provider', async () => {
    const user = userEvent.setup();
    stubFetchWithConfig(fakeConfig({
      anthropic_api_key: 'sk-a****',
      default_llm_provider: 'anthropic',
      default_llm_model: 'claude-3-5-haiku-latest',
    }));
    renderWithProviders(<NewRunPage />);

    const select = await screen.findByLabelText<HTMLSelectElement>('Provider default');
    await waitFor(() => expect(select.querySelector('option[value="anthropic"]')).not.toBeDisabled());
    await user.selectOptions(select, 'anthropic');

    expect(screen.getByLabelText('Modelo default')).toHaveValue('claude-3-5-haiku-latest');
  });

  it('auto-fills the model field with an example when picking a configured non-default provider', async () => {
    const user = userEvent.setup();
    stubFetchWithConfig(fakeConfig({
      anthropic_api_key: 'sk-a****',
      groq_api_key: 'gsk_****',
      default_llm_provider: 'anthropic',
      default_llm_model: 'claude-3-5-haiku-latest',
    }));
    renderWithProviders(<NewRunPage />);

    const select = await screen.findByLabelText<HTMLSelectElement>('Provider default');
    await waitFor(() => expect(select.querySelector('option[value="groq"]')).not.toBeDisabled());
    await user.selectOptions(select, 'groq');

    expect(screen.getByLabelText('Modelo default')).toHaveValue('llama-3.3-70b-versatile');
  });
});
