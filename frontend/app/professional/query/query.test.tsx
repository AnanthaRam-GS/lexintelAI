import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProfessionalQueryPage from './page';
import { ApiClientError, limitMessage, queryApi } from '../../../lib/api';
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

  it('explains a queued answer after 5 seconds and keeps the MODEL_BUSY message for a timeout', async () => {
    vi.useFakeTimers();
    try {
      let reject: (reason: unknown) => void = () => {};
      vi.spyOn(queryApi, 'submitText').mockReturnValue(
        new Promise((_resolve, rejectRequest) => {
          reject = rejectRequest;
        }),
      );
      render(<ProfessionalQueryPage />);
      fireEvent.change(screen.getByPlaceholderText(/Accused charged under Section 302 IPC/i), {
        target: { value: 'Bail under Section 437 CrPC.' },
      });
      fireEvent.click(screen.getByRole('button', { name: /Execute Legal Research/i }));

      await act(async () => vi.advanceTimersByTimeAsync(4_999));
      expect(screen.queryByText(/High demand/)).not.toBeInTheDocument();
      await act(async () => vi.advanceTimersByTimeAsync(1));
      const notice = screen.getByText(
        'High demand — your answer is queued and will appear shortly.',
      );
      expect(notice).toHaveAttribute('role', 'status');
      expect(notice).toHaveAttribute('aria-live', 'polite');

      // The queue gave up: the existing MODEL_BUSY limit message replaces the notice.
      await act(async () => {
        reject(new ApiClientError('busy', 503, 'MODEL_BUSY', 15));
      });
      expect(screen.queryByText(/High demand/)).not.toBeInTheDocument();
      expect(screen.getByText('Please slow down')).toBeInTheDocument();
      expect(
        screen.getByText(limitMessage(new ApiClientError('busy', 503, 'MODEL_BUSY', 15)) as string),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
