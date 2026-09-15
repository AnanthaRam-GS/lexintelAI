import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProfessionalUploadPage from './page';
import { queryApi } from '../../../lib/api';
import { mockProfessionalQueryResponse } from '../../../lib/mocks/professionalMocks';

describe('Professional Upload Page', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(cleanup);

  it('renders confidential document heading, dropzone, and privacy assurance banner', () => {
    render(<ProfessionalUploadPage />);

    expect(screen.getByRole('heading', { name: /Private Case File & Brief Analysis/i })).toBeInTheDocument();
    expect(screen.getByText(/Privileged Legal Document Safeguard/i)).toBeInTheDocument();
    expect(screen.getByText(/never indexed, stored, or added to the global corpus/i)).toBeInTheDocument();
  });

  it('selects PDF file and submits to queryApi.submitPdf without calling ingestion', async () => {
    const submitPdfSpy = vi.spyOn(queryApi, 'submitPdf').mockResolvedValue(mockProfessionalQueryResponse);

    render(<ProfessionalUploadPage />);

    // Simulate file input
    const file = new File(['%PDF-1.4 test case file'], 'bail_appeal_brief.pdf', {
      type: 'application/pdf',
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeInTheDocument();

    Object.defineProperty(fileInput, 'files', {
      value: [file],
    });
    fireEvent.change(fileInput);

    await waitFor(() => {
      expect(screen.getAllByText('bail_appeal_brief.pdf').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByRole('button', { name: /Begin Private Analysis/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Begin Private Analysis/i }));

    await waitFor(() => {
      expect(submitPdfSpy).toHaveBeenCalledWith(file);
      expect(screen.getByTestId('professional-results-view')).toBeInTheDocument();
      expect(screen.getByText('1. Executive Summary')).toBeInTheDocument();
    });
  });
});
