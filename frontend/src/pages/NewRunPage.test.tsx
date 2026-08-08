import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NewRunPage } from './NewRunPage';
import { renderWithProviders } from '@/test/render';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => navigateMock };
});

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
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
    expect(fetchMock).not.toHaveBeenCalled();
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
});
