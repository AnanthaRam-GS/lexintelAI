import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProfessionalQueryPage from './page';
import { queryApi } from '../../../lib/api';
import { mockProfessionalQueryResponse } from '../../../lib/mocks/professionalMocks';

describe('Professional Query Page', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(cleanup);

  it('renders input area, example queries, and submit button', () => {
    render(<ProfessionalQueryPage />);

    expect(
      screen.getByRole('heading', { name: /Statutory & Precedent Text Query/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/Accused charged under Section 302 IPC/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Execute Legal Research/i })).toBeInTheDocument();
    expect(screen.getByText(/Circumstantial Evidence & Murder/i)).toBeInTheDocument();
  });

  it('submits text query to queryApi.submitText and displays structured results', async () => {
    const submitSpy = vi
      .spyOn(queryApi, 'submitText')
      .mockResolvedValue(mockProfessionalQueryResponse);

    render(<ProfessionalQueryPage />);

    const textarea = screen.getByPlaceholderText(/Accused charged under Section 302 IPC/i);
    fireEvent.change(textarea, {
      target: { value: 'Bail under Section 437 CrPC based on medical records.' },
    });

    const submitBtn = screen.getByRole('button', { name: /Execute Legal Research/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(submitSpy).toHaveBeenCalledWith(
        'Bail under Section 437 CrPC based on medical records.',
      );
      expect(screen.getByTestId('professional-results-view')).toBeInTheDocument();
      expect(screen.getByText('1. Executive Summary')).toBeInTheDocument();
    });
  });

  it('populates query from example prompt click and submits', async () => {
    const submitSpy = vi
      .spyOn(queryApi, 'submitText')
      .mockResolvedValue(mockProfessionalQueryResponse);

    render(<ProfessionalQueryPage />);

    const exampleBtn = screen.getByRole('button', { name: /Circumstantial Evidence & Murder/i });
    fireEvent.click(exampleBtn);

    await waitFor(() => {
      expect(submitSpy).toHaveBeenCalled();
      expect(screen.getByTestId('professional-results-view')).toBeInTheDocument();
    });
  });
});
