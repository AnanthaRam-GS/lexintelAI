import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { adminLawyerVerificationApi } from '../../../lib/api';
import AdminLawyerVerificationPage from './page';

const application = {
  id: 4,
  user_id: 2,
  applicant_email: 'applicant@example.test',
  applicant_name: 'Applicant One',
  bar_council: 'State Bar Council',
  enrollment_number: 'ENR-9',
  enrollment_year: 2024,
  jurisdiction: 'Kerala',
  organization: 'Legal Aid Office',
  proof_file_name: 'proof.pdf',
  proof_content_type: 'application/pdf',
  status: 'PENDING' as const,
  submitted_at: '2026-09-17T00:00:00Z',
};

describe('AdminLawyerVerificationPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('loads application detail and updates status after approval', async () => {
    vi.spyOn(adminLawyerVerificationApi, 'list').mockResolvedValue({ applications: [application] });
    vi.spyOn(adminLawyerVerificationApi, 'approve').mockResolvedValue({
      ...application,
      status: 'VERIFIED',
      reviewed_by: 1,
    });
    const user = userEvent.setup();
    render(<AdminLawyerVerificationPage />);

    expect(await screen.findAllByText('Applicant One')).toHaveLength(2);
    expect(screen.getByText('ENR-9 (2024)')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(adminLawyerVerificationApi.approve).toHaveBeenCalledWith(4));
    expect(screen.getAllByText('VERIFIED')).toHaveLength(2);
  });

  it('sends safe rejection reason', async () => {
    vi.spyOn(adminLawyerVerificationApi, 'list').mockResolvedValue({ applications: [application] });
    const reject = vi
      .spyOn(adminLawyerVerificationApi, 'reject')
      .mockResolvedValue({ ...application, status: 'REJECTED', review_note: 'Could not verify.' });
    const user = userEvent.setup();
    render(<AdminLawyerVerificationPage />);

    await screen.findAllByText('Applicant One');
    await user.type(
      screen.getByPlaceholderText('Review reason for rejection or resubmission'),
      'Could not verify.',
    );
    await user.click(screen.getByRole('button', { name: 'Reject' }));

    await waitFor(() => expect(reject).toHaveBeenCalledWith(4, 'Could not verify.'));
    expect(screen.getAllByText('REJECTED')).toHaveLength(2);
  });
});
