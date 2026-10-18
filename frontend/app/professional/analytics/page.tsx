'use client';

import React, { useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { analyticsApi } from '../../../lib/api';
import { ErrorMessage, LoadingSpinner } from '../../../components/shared';
import type {
  IpcBnsMappingRow,
  NcrbStatPoint,
  OffenseFrequencyPoint,
  OutcomeDistributionPoint,
  SectionCooccurrencePoint,
} from '../../../lib/types/api';

type AnalyticsTab =
  'offense-trends' | 'outcome-distribution' | 'section-cooccurrence' | 'ipc-bns' | 'ncrb-stats';

const TABS: { id: AnalyticsTab; label: string; description: string }[] = [
  {
    id: 'offense-trends',
    label: 'Offense Trends',
    description: 'Statutory frequency by section and year',
  },
  {
    id: 'outcome-distribution',
    label: 'Outcome Distribution',
    description: 'Trial and appellate conviction outcomes',
  },
  {
    id: 'section-cooccurrence',
    label: 'Section Co-occurrence',
    description: 'Joint charges and co-filed penal provisions',
  },
  {
    id: 'ipc-bns',
    label: 'IPC-BNS Map',
    description: 'Penal code transition crosswalk and revisions',
  },
  {
    id: 'ncrb-stats',
    label: 'NCRB Statistics',
    description: 'State-level crime data and conviction figures',
  },
];

export default function ProfessionalAnalyticsPage() {
  const [activeTab, setActiveTab] = useState<AnalyticsTab>('offense-trends');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Datasets
  const [offenseData, setOffenseData] = useState<OffenseFrequencyPoint[]>([]);
  const [outcomeData, setOutcomeData] = useState<OutcomeDistributionPoint[]>([]);
  const [cooccurrenceData, setCooccurrenceData] = useState<SectionCooccurrencePoint[]>([]);
  const [ipcBnsData, setIpcBnsData] = useState<IpcBnsMappingRow[]>([]);
  const [ncrbData, setNcrbData] = useState<NcrbStatPoint[]>([]);

  // Filters
  const [selectedSection, setSelectedSection] = useState<string>('All');
  const [selectedCourtLevel, setSelectedCourtLevel] = useState<string>('All');
  const [bnsSearchTerm, setBnsSearchTerm] = useState<string>('');
  const [selectedState, setSelectedState] = useState<string>('All');

  const [reloadTrigger, setReloadTrigger] = useState(0);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [offenses, outcomes, cooccurrences, ipcBns, ncrb] = await Promise.all([
          analyticsApi.getOffenseFrequency(),
          analyticsApi.getOutcomeDistribution(),
          analyticsApi.getSectionCooccurrence(),
          analyticsApi.getIpcBnsMap(),
          analyticsApi.getNcrbStats(),
        ]);
        if (!active) return;
        setOffenseData(offenses);
        setOutcomeData(outcomes);
        setCooccurrenceData(cooccurrences);
        setIpcBnsData(ipcBns);
        setNcrbData(ncrb);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : 'Failed to fetch analytics metrics.');
      } finally {
        if (active) setIsLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [reloadTrigger]);

  // 1. Offense Trends Processing
  const filteredOffenseData = React.useMemo(() => {
    if (selectedSection === 'All') return offenseData;
    return offenseData.filter((d) => d.section === selectedSection);
  }, [offenseData, selectedSection]);

  const uniqueSections = React.useMemo(() => {
    return Array.from(new Set(offenseData.map((d) => d.section)));
  }, [offenseData]);

  // Aggregate year totals or multi-line mapping
  const trendChartData = React.useMemo(() => {
    const yearMap = new Map<number, Record<string, number | string>>();
    filteredOffenseData.forEach((point) => {
      if (!yearMap.has(point.year)) {
        yearMap.set(point.year, { year: point.year });
      }
      const existing = yearMap.get(point.year)!;
      existing[point.section] = point.count;
    });
    return Array.from(yearMap.values()).sort((a, b) => (a.year as number) - (b.year as number));
  }, [filteredOffenseData]);

  // 2. Outcome Distribution Processing
  const filteredOutcomeData = React.useMemo(() => {
    if (selectedCourtLevel === 'All') return outcomeData;
    return outcomeData.filter((d) => d.court_level === selectedCourtLevel);
  }, [outcomeData, selectedCourtLevel]);

  // 3. IPC-BNS Filtering
  const filteredIpcBnsData = React.useMemo(() => {
    if (!bnsSearchTerm.trim()) return ipcBnsData;
    const term = bnsSearchTerm.toLowerCase();
    return ipcBnsData.filter(
      (row) =>
        row.ipc_section.toLowerCase().includes(term) ||
        row.ipc_description.toLowerCase().includes(term) ||
        (row.bns_section && row.bns_section.toLowerCase().includes(term)) ||
        (row.bns_description && row.bns_description.toLowerCase().includes(term)) ||
        row.change_type.toLowerCase().includes(term),
    );
  }, [ipcBnsData, bnsSearchTerm]);

  // 4. NCRB Filtering
  const filteredNcrbData = React.useMemo(() => {
    if (selectedState === 'All') return ncrbData;
    return ncrbData.filter((d) => d.state === selectedState);
  }, [ncrbData, selectedState]);

  const uniqueStates = React.useMemo(() => {
    return Array.from(new Set(ncrbData.map((d) => d.state)));
  }, [ncrbData]);

  return (
    <div className="space-y-6" data-testid="professional-analytics-page">
      {/* Page Header */}
      <div>
        <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-brass)]">
          Judicial &amp; Statutory Analytics
        </span>
        <h1 className="font-display text-2xl font-bold tracking-tight text-[var(--color-ink)] sm:text-3xl">
          Empirical Legal Intelligence Dashboard
        </h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Interactive metrics covering offense trends across penal sections, conviction and appeal
          outcome distributions, statutory co-occurrences, IPC-BNS crosswalks, and NCRB crime
          statistics.
        </p>
      </div>

      {/* 5-Tab Navigation Header */}
      <div className="border-b border-[var(--color-border)]">
        <nav className="flex space-x-2 sm:space-x-8 overflow-x-auto" aria-label="Analytics tabs">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`cursor-pointer whitespace-nowrap pb-3.5 text-sm font-semibold transition-colors border-b-2 ${
                  isActive
                    ? 'border-[var(--color-brass)] text-[var(--color-ink)]'
                    : 'border-transparent text-[var(--color-muted)] hover:text-[var(--color-ink)]'
                }`}
                aria-current={isActive ? 'page' : undefined}
              >
                {tab.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Loading & Error Indicators */}
      {isLoading && (
        <div className="flex h-64 items-center justify-center rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-8">
          <LoadingSpinner size="lg" label="Loading judicial analytics data" />
        </div>
      )}

      {error && (
        <ErrorMessage
          variant="inline"
          title="Failed to Load Analytics"
          message={error}
          onRetry={() => {
            setIsLoading(true);
            setReloadTrigger((c) => c + 1);
          }}
        />
      )}

      {!isLoading && !error && (
        <div className="space-y-6">
          {/* TAB 1: OFFENSE TRENDS */}
          {activeTab === 'offense-trends' && (
            <div className="space-y-6" data-testid="tab-offense-trends">
              <div className="flex flex-col gap-3 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="font-display text-base font-bold text-[var(--color-ink)]">
                    Annual Offense Frequency by Section
                  </h2>
                  <p className="text-xs text-[var(--color-muted)]">
                    Judgments in the corpus citing each offence provision, by decision year.
                    Procedural (CrPC/BNSS), definitional and liability-linking provisions (e.g. IPC
                    34, 149) are excluded.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <label
                    htmlFor="section-filter"
                    className="text-xs font-semibold text-[var(--color-body)]"
                  >
                    Filter Section:
                  </label>
                  <select
                    id="section-filter"
                    value={selectedSection}
                    onChange={(e) => setSelectedSection(e.target.value)}
                    className="rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-2.5 py-1 text-xs text-[var(--color-ink)]"
                  >
                    <option value="All">All Sections</option>
                    {uniqueSections.map((sec) => (
                      <option key={sec} value={sec}>
                        {sec}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {offenseData.length === 0 && (
                <p
                  data-testid="offense-empty"
                  className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 text-sm text-[var(--color-muted)]"
                >
                  No offence provisions have been identified in the analysed judgments yet.
                </p>
              )}

              {/* Chart Container */}
              <div className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-xs">
                <div className="h-80 w-full" data-testid="offense-chart-container">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={trendChartData}
                      margin={{ top: 10, right: 30, left: 20, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2ddd5" />
                      <XAxis dataKey="year" stroke="#606c7c" />
                      <YAxis stroke="#606c7c" />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#ffffff',
                          borderColor: '#d7d0c2',
                          borderRadius: '6px',
                        }}
                      />
                      <Legend />
                      <Line
                        type="monotone"
                        dataKey="IPC 302"
                        stroke="#a06824"
                        strokeWidth={2}
                        name="IPC 302 (Murder)"
                      />
                      <Line
                        type="monotone"
                        dataKey="IPC 420"
                        stroke="#1f67b1"
                        strokeWidth={2}
                        name="IPC 420 (Cheating)"
                      />
                      <Line
                        type="monotone"
                        dataKey="IPC 376"
                        stroke="#ad4339"
                        strokeWidth={2}
                        name="IPC 376 (Sexual Offence)"
                      />
                      <Line
                        type="monotone"
                        dataKey="IPC 307"
                        stroke="#237b53"
                        strokeWidth={2}
                        name="IPC 307 (Attempt to Murder)"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: OUTCOME DISTRIBUTION */}
          {activeTab === 'outcome-distribution' && (
            <div className="space-y-6" data-testid="tab-outcome-distribution">
              <div className="flex flex-col gap-3 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="font-display text-base font-bold text-[var(--color-ink)]">
                    Judicial Outcome Distribution by Court Level
                  </h2>
                  <p className="text-xs text-[var(--color-muted)]">
                    Convictions, acquittals, and appellate reversal patterns.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <label
                    htmlFor="court-filter"
                    className="text-xs font-semibold text-[var(--color-body)]"
                  >
                    Court Level:
                  </label>
                  <select
                    id="court-filter"
                    value={selectedCourtLevel}
                    onChange={(e) => setSelectedCourtLevel(e.target.value)}
                    className="rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-2.5 py-1 text-xs text-[var(--color-ink)]"
                  >
                    <option value="All">All Court Levels</option>
                    <option value="Sessions Court">Sessions Court</option>
                    <option value="High Court">High Court</option>
                    <option value="Supreme Court">Supreme Court</option>
                  </select>
                </div>
              </div>

              {/* Stacked Bar Chart */}
              <div className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-xs">
                <div className="h-80 w-full" data-testid="outcome-chart-container">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={filteredOutcomeData.map((d) => ({
                        label: `${d.section} · ${d.court_level}`,
                        Convicted: d.convicted,
                        Acquitted: d.acquitted,
                        'Appeal Allowed': d.appeal_allowed,
                        'Appeal Dismissed': d.appeal_dismissed,
                      }))}
                      margin={{ top: 20, right: 30, left: 20, bottom: 60 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2ddd5" />
                      <XAxis
                        dataKey="label"
                        angle={-15}
                        textAnchor="end"
                        height={60}
                        stroke="#606c7c"
                        tick={{ fontSize: 11 }}
                      />
                      <YAxis stroke="#606c7c" />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#ffffff', borderColor: '#d7d0c2' }}
                      />
                      <Legend verticalAlign="top" />
                      <Bar dataKey="Convicted" fill="#237b53" />
                      <Bar dataKey="Acquitted" fill="#ad4339" />
                      <Bar dataKey="Appeal Allowed" fill="#a06824" />
                      <Bar dataKey="Appeal Dismissed" fill="#1f67b1" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: SECTION CO-OCCURRENCE */}
          {activeTab === 'section-cooccurrence' && (
            <div className="space-y-6" data-testid="tab-section-cooccurrence">
              <div className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                <h2 className="font-display text-base font-bold text-[var(--color-ink)]">
                  Statutory Section Co-occurrence Matrix
                </h2>
                <p className="text-xs text-[var(--color-muted)]">
                  Number of judgments in the corpus citing both offence provisions. Procedural,
                  definitional and liability-linking provisions are excluded.
                </p>
              </div>

              {cooccurrenceData.length === 0 && (
                <p
                  data-testid="cooccurrence-empty"
                  className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 text-sm text-[var(--color-muted)]"
                >
                  No judgment cites two or more offence provisions yet.
                </p>
              )}

              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {cooccurrenceData.map((pair, idx) => (
                  <div
                    key={`${pair.section_a}-${pair.section_b}-${idx}`}
                    className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="rounded bg-[var(--color-surface-subtle)] px-2 py-0.5 text-xs font-bold text-[var(--color-ink)]">
                        {pair.section_a}
                      </span>
                      <span className="text-xs font-bold text-[var(--color-muted)]">+</span>
                      <span className="rounded bg-[var(--color-surface-subtle)] px-2 py-0.5 text-xs font-bold text-[var(--color-brass)]">
                        {pair.section_b.split(' ')[0]} {pair.section_b.split(' ')[1]}
                      </span>
                    </div>

                    <p
                      className="mt-3 text-xs text-[var(--color-muted)] truncate"
                      title={pair.section_b}
                    >
                      {pair.section_b}
                    </p>

                    <div className="mt-4 flex items-baseline justify-between border-t border-[var(--color-border)] pt-2">
                      <span className="text-xs text-[var(--color-muted)]">Joint Filings:</span>
                      <span className="font-display text-base font-bold text-[var(--color-ink)]">
                        {pair.count.toLocaleString()}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 4: IPC-BNS TRANSITION MAP */}
          {activeTab === 'ipc-bns' && (
            <div className="space-y-6" data-testid="tab-ipc-bns">
              <div className="flex flex-col gap-3 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="font-display text-base font-bold text-[var(--color-ink)]">
                    IPC (1860) to BNS (2023) Statutory Crosswalk
                  </h2>
                  <p className="text-xs text-[var(--color-muted)]">
                    Comparative mapping of classic Indian Penal Code provisions to the Bharatiya
                    Nyaya Sanhita.
                  </p>
                </div>

                <div className="w-full sm:w-72">
                  <input
                    type="search"
                    placeholder="Search section or description..."
                    value={bnsSearchTerm}
                    onChange={(e) => setBnsSearchTerm(e.target.value)}
                    className="w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-1.5 text-xs text-[var(--color-ink)] focus:outline-none focus:ring-1 focus:ring-[var(--color-focus)]"
                  />
                </div>
              </div>

              {/* Mapping Table */}
              <div className="overflow-x-auto rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-xs">
                <table className="min-w-full divide-y divide-[var(--color-border)] text-left text-xs">
                  <thead className="bg-[var(--color-surface-subtle)] font-bold text-[var(--color-ink)] uppercase tracking-wider">
                    <tr>
                      <th className="px-4 py-3">IPC Provision</th>
                      <th className="px-4 py-3">IPC Description</th>
                      <th className="px-4 py-3">BNS Provision</th>
                      <th className="px-4 py-3">BNS Reformulation</th>
                      <th className="px-4 py-3">Nature of Change</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--color-border)]">
                    {filteredIpcBnsData.map((row, idx) => (
                      <tr key={idx} className="hover:bg-[var(--color-canvas)] transition-colors">
                        <td className="whitespace-nowrap px-4 py-3 font-bold text-[var(--color-brass)]">
                          {row.ipc_section}
                        </td>
                        <td className="px-4 py-3 text-[var(--color-body)] max-w-xs">
                          {row.ipc_description}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 font-bold text-[var(--color-info-foreground)]">
                          {row.bns_section || 'Repealed/Omitted'}
                        </td>
                        <td className="px-4 py-3 text-[var(--color-body)] max-w-sm">
                          {row.bns_description || 'N/A'}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3">
                          <span className="rounded-full bg-[var(--color-surface-subtle)] border border-[var(--color-border)] px-2 py-0.5 text-[0.6875rem] font-medium text-[var(--color-body)]">
                            {row.change_type}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 5: NCRB STATISTICS */}
          {activeTab === 'ncrb-stats' && (
            <div className="space-y-6" data-testid="tab-ncrb-stats">
              <div className="flex flex-col gap-3 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="font-display text-base font-bold text-[var(--color-ink)]">
                    National Crime Records Bureau (NCRB) State Statistics
                  </h2>
                  <p className="text-xs text-[var(--color-muted)]">
                    State/UT-wise cases registered (Crime in India 2024, Table 1A.4). National,
                    state/UT total and subtotal rows are excluded to avoid double counting.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <label
                    htmlFor="state-filter"
                    className="text-xs font-semibold text-[var(--color-body)]"
                  >
                    Filter State:
                  </label>
                  <select
                    id="state-filter"
                    value={selectedState}
                    onChange={(e) => setSelectedState(e.target.value)}
                    className="rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-canvas)] px-2.5 py-1 text-xs text-[var(--color-ink)]"
                  >
                    <option value="All">All States</option>
                    {uniqueStates.map((st) => (
                      <option key={st} value={st}>
                        {st}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {ncrbData.length === 0 && (
                <p
                  data-testid="ncrb-empty"
                  className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 text-sm text-[var(--color-muted)]"
                >
                  No NCRB statistics have been loaded yet.
                </p>
              )}

              {/* State Comparison Cards */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {filteredNcrbData.map((stat, idx) => (
                  <article
                    key={`${stat.state}-${stat.offense_category}-${idx}`}
                    className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-[var(--color-brass)] uppercase tracking-wider">
                        {stat.year} · {stat.offense_category}
                      </span>
                      {stat.ipc_section && (
                        <span className="rounded bg-[var(--color-surface-subtle)] px-1.5 py-0.5 font-mono text-[0.6875rem]">
                          {stat.ipc_section}
                        </span>
                      )}
                    </div>

                    <h3 className="font-display mt-2 text-lg font-bold text-[var(--color-ink)]">
                      {stat.state}
                    </h3>

                    <div className="mt-4 grid grid-cols-3 gap-2 border-t border-[var(--color-border)] pt-3 text-center">
                      <div>
                        <p className="text-[0.6875rem] text-[var(--color-muted)]">Total Cases</p>
                        <p className="font-display text-sm font-bold text-[var(--color-ink)]">
                          {stat.case_count?.toLocaleString() ?? '—'}
                        </p>
                      </div>
                      <div>
                        <p className="text-[0.6875rem] text-[var(--color-success)]">Convictions</p>
                        <p className="font-display text-sm font-bold text-[var(--color-success)]">
                          {stat.conviction_count?.toLocaleString() ?? '—'}
                        </p>
                      </div>
                      <div>
                        <p className="text-[0.6875rem] text-[var(--color-error)]">Acquittals</p>
                        <p className="font-display text-sm font-bold text-[var(--color-error)]">
                          {stat.acquittal_count?.toLocaleString() ?? '—'}
                        </p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
