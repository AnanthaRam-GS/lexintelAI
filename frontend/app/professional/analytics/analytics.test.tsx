import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProfessionalAnalyticsPage from './page';
import { analyticsApi } from '../../../lib/api';
import {
  mockIpcBnsMappingData,
  mockNcrbStatData,
  mockOffenseFrequencyData,
  mockOutcomeDistributionData,
  mockSectionCooccurrenceData,
} from '../../../lib/mocks/professionalMocks';

vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="mock-responsive-container">{children}</div>
    ),
  };
});

describe('Professional Analytics Dashboard', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(analyticsApi, 'getOffenseFrequency').mockResolvedValue(mockOffenseFrequencyData);
    vi.spyOn(analyticsApi, 'getOutcomeDistribution').mockResolvedValue(mockOutcomeDistributionData);
    vi.spyOn(analyticsApi, 'getSectionCooccurrence').mockResolvedValue(mockSectionCooccurrenceData);
    vi.spyOn(analyticsApi, 'getIpcBnsMap').mockResolvedValue(mockIpcBnsMappingData);
    vi.spyOn(analyticsApi, 'getNcrbStats').mockResolvedValue(mockNcrbStatData);
  });

  afterEach(cleanup);

  it('renders all 5 tab buttons and displays Offense Trends by default', async () => {
    render(<ProfessionalAnalyticsPage />);

    // Check tabs
    expect(screen.getByRole('button', { name: /Offense Trends/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Outcome Distribution/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Section Co-occurrence/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /IPC-BNS Map/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /NCRB Statistics/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId('tab-offense-trends')).toBeInTheDocument();
      expect(screen.getByText(/Annual Offense Frequency by Section/i)).toBeInTheDocument();
    });
  });

  it('switches to Outcome Distribution tab on click', async () => {
    render(<ProfessionalAnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('tab-offense-trends')).toBeInTheDocument();
    });

    const outcomeTabBtn = screen.getByRole('button', { name: /Outcome Distribution/i });
    fireEvent.click(outcomeTabBtn);

    expect(screen.getByTestId('tab-outcome-distribution')).toBeInTheDocument();
    expect(screen.getByText(/Judicial Outcome Distribution by Court Level/i)).toBeInTheDocument();
  });

  it('switches to IPC-BNS Map and filters rows by search term', async () => {
    render(<ProfessionalAnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('tab-offense-trends')).toBeInTheDocument();
    });

    const ipcBnsTabBtn = screen.getByRole('button', { name: /IPC-BNS Map/i });
    fireEvent.click(ipcBnsTabBtn);

    expect(screen.getByTestId('tab-ipc-bns')).toBeInTheDocument();
    expect(screen.getByText(/Statutory Crosswalk/i)).toBeInTheDocument();
    expect(screen.getByText('Section 302')).toBeInTheDocument();

    // Filter search
    const searchInput = screen.getByPlaceholderText(/Search section or description.../i);
    fireEvent.change(searchInput, { target: { value: 'sedition' } });

    // Section 124A sedition should match
    expect(screen.getByText('Section 124A')).toBeInTheDocument();
    expect(screen.queryByText('Section 302')).not.toBeInTheDocument();
  });

  it('switches to NCRB Statistics tab and renders state crime metrics', async () => {
    render(<ProfessionalAnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('tab-offense-trends')).toBeInTheDocument();
    });

    const ncrbTabBtn = screen.getByRole('button', { name: /NCRB Statistics/i });
    fireEvent.click(ncrbTabBtn);

    expect(screen.getByTestId('tab-ncrb-stats')).toBeInTheDocument();
    expect(screen.getByText(/National Crime Records Bureau/i)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Maharashtra' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Uttar Pradesh' })).toBeInTheDocument();
  });

  it('renders an unreported NCRB case count as a dash instead of failing', async () => {
    vi.spyOn(analyticsApi, 'getNcrbStats').mockResolvedValue([
      {
        year: 2024,
        state: 'Unreported State',
        offense_category: 'Murder',
        ipc_section: '302',
        case_count: null,
        conviction_count: null,
        acquittal_count: null,
      },
    ]);
    render(<ProfessionalAnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('tab-offense-trends')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /NCRB Statistics/i }));

    const card = screen.getByRole('heading', { name: 'Unreported State' })
      .parentElement as HTMLElement;
    expect(card).toHaveTextContent('Total Cases—');
  });

  it('labels the offence-only default and the NCRB aggregate exclusion', async () => {
    render(<ProfessionalAnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('tab-offense-trends')).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Procedural \(CrPC\/BNSS\), definitional and liability-linking provisions/i),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Section Co-occurrence/i }));
    expect(
      screen.getByText(/Procedural, definitional and liability-linking provisions are excluded/i),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /NCRB Statistics/i }));
    expect(
      screen.getByText(/subtotal rows are excluded to avoid double counting/i),
    ).toBeInTheDocument();
  });

  it('shows empty states when no offence provisions or NCRB rows are available', async () => {
    vi.spyOn(analyticsApi, 'getOffenseFrequency').mockResolvedValue([]);
    vi.spyOn(analyticsApi, 'getSectionCooccurrence').mockResolvedValue([]);
    vi.spyOn(analyticsApi, 'getNcrbStats').mockResolvedValue([]);
    render(<ProfessionalAnalyticsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('offense-empty')).toHaveTextContent(
        'No offence provisions have been identified in the analysed judgments yet.',
      );
    });
    fireEvent.click(screen.getByRole('button', { name: /Section Co-occurrence/i }));
    expect(screen.getByTestId('cooccurrence-empty')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /NCRB Statistics/i }));
    expect(screen.getByTestId('ncrb-empty')).toHaveTextContent(
      'No NCRB statistics have been loaded yet.',
    );
  });
});
