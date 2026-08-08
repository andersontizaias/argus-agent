import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PlaceholderPage } from './PlaceholderPage';
import { renderWithProviders } from '@/test/render';

describe('PlaceholderPage', () => {
  it('renders the given title', () => {
    renderWithProviders(<PlaceholderPage title="Execuções" />);
    expect(screen.getByText('Execuções')).toBeInTheDocument();
  });
});
