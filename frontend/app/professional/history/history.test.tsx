import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProfessionalHistoryPage from './page';
import { historyApi } from '../../../lib/api';
import { mockQueryHistoryData } from '../../../lib/mocks/professionalMocks';

describe('Professional Query History Page', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(historyApi, 'getQueryHistory').mockResolvedValue(mockQueryHistoryData);
  });

  afterEach(cleanup);

  it('renders history items with query text, mode, and expand action', async () => {
    render(<ProfessionalHistoryPage />);

    expect(screen.getByRole('heading', { name: /Query & Document History/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId('history-list')).toBeInTheDocument();
      expect(screen.getByText(/Circumstantial evidence murder case/i)).toBeInTheDocument();
      expect(screen.getByText(/Brief_State_v_Verma/i)).toBeInTheDocument();
    });
  });

  it('filters history items using search input', async () => {
    render(<ProfessionalHistoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId('history-list')).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/Search past queries or models/i);
    fireEvent.change(searchInput, { target: { value: 'commercial dispute' } });

    expect(
      screen.getByText(/Quashing petition under Section 482 CrPC for commercial dispute/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Circumstantial evidence murder case/i)).not.toBeInTheDocument();
  });

  it('filters history items by input mode selector', async () => {
    render(<ProfessionalHistoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId('history-list')).toBeInTheDocument();
    });

    const modeSelect = screen.getByLabelText(/Input Mode:/i);
    fireEvent.change(modeSelect, { target: { value: 'pdf' } });

    // Should only show PDF items
    expect(screen.getByText(/Brief_State_v_Verma/i)).toBeInTheDocument();
    expect(screen.queryByText(/Circumstantial evidence murder case/i)).not.toBeInTheDocument();
  });

  it('expands stored case brief on button click', async () => {
    render(<ProfessionalHistoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId('history-list')).toBeInTheDocument();
    });

    const expandButtons = screen.getAllByRole('button', { name: /View Stored Brief/i });
    expect(expandButtons.length).toBeGreaterThan(0);

    fireEvent.click(expandButtons[0]);

    // Structured case brief should now be visible
    expect(screen.getByText(/1. Executive Summary/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Hide Brief/i })).toBeInTheDocument();

    // Clicking Hide Brief collapses it
    fireEvent.click(screen.getByRole('button', { name: /Hide Brief/i }));
    expect(screen.queryByText(/1. Executive Summary/i)).not.toBeInTheDocument();
  });

  it('supports client-side pagination across pages', async () => {
    render(<ProfessionalHistoryPage />);

    await waitFor(() => {
      expect(screen.getByTestId('history-list')).toBeInTheDocument();
      expect(screen.getByText(/Showing Page/i)).toBeInTheDocument();
    });

    const nextBtn = screen.getByRole('button', { name: /Next/i });
    expect(nextBtn).not.toBeDisabled();

    fireEvent.click(nextBtn);

    // Page 2 should be active
    expect(screen.getByText(/Showing Page/i)).toHaveTextContent('Showing Page 2 of 2');
  });
});
