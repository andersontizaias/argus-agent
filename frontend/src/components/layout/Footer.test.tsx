import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Footer } from './Footer';
import { renderWithProviders } from '@/test/render';

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Footer', () => {
  it('shows the version reported by the backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'ok', version: '0.1.0', checks: [] })));
    renderWithProviders(<Footer />);
    expect(await screen.findByText('Argus Agent v0.1.0')).toBeInTheDocument();
  });

  it('renders without a version while health has not loaded yet', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    renderWithProviders(<Footer />);
    expect(screen.getByText('Argus Agent')).toBeInTheDocument();
  });
});
