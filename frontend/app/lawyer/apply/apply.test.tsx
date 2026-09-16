import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { authApi, lawyerApplicationApi } from '../../../lib/api';
import LawyerApplyPage from './page';

const pendingApplication = {
  id: 7,
  user_id: 1,
  bar_council: 'State Bar Council',
  enrollment_number: 'ENR-1',
  enrollment_year: 2024,
  jurisdiction: 'Kerala',
  organization: null,
  proof_file_name: 'proof.pdf',
  proof_content_type: 'application/pdf',
  status: 'PENDING' as const,
  submitted_at: '2026-09-17T00:00:00Z',
};

describe('LawyerApplyPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders current pending status', async () => {
    vi.spyOn(authApi, 'me').mockResolvedValue({
      id: 1,
      email: 'public@example.test',
      role: 'public',
      email_verified: true,
    });
    vi.spyOn(lawyerApplicationApi, 'getMine').mockResolvedValue({
      application: pendingApplication,
    });
    render(<LawyerApplyPage />);

    expect(await screen.findByText('PENDING')).toBeInTheDocument();
    expect(screen.getByText(/ENR-1/)).toBeInTheDocument();
  });

  it('submits multipart lawyer application fields and proof', async () => {
    vi.spyOn(authApi, 'me').mockResolvedValue({
      id: 1,
      email: 'public@example.test',
      role: 'public',
      email_verified: true,
    });
    vi.spyOn(lawyerApplicationApi, 'getMine').mockResolvedValue({ application: null });
    const submit = vi
      .spyOn(lawyerApplicationApi, 'submit')
      .mockResolvedValue({ ...pendingApplication, status: 'PENDING' });
    const user = userEvent.setup();
    render(<LawyerApplyPage />);

    expect(await screen.findByLabelText('Bar Council')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Bar Council'), 'State Bar Council');
    await user.type(screen.getByLabelText('Enrollment number'), 'ENR-1');
    await user.clear(screen.getByLabelText('Enrollment year'));
    await user.type(screen.getByLabelText('Enrollment year'), '2024');
    await user.type(screen.getByLabelText('State / jurisdiction'), 'Kerala');
    const proofInput = screen.getByLabelText('Proof document');
    fireEvent.change(proofInput, {
      target: { files: [new File(['%PDF-1.4'], 'proof.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.submit(proofInput.closest('form')!);

    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0][0]).toMatchObject({
      barCouncil: 'State Bar Council',
      enrollmentNumber: 'ENR-1',
      enrollmentYear: 2024,
      jurisdiction: 'Kerala',
    });
    expect(submit.mock.calls[0][0].proof.name).toBe('proof.pdf');
  });
});
