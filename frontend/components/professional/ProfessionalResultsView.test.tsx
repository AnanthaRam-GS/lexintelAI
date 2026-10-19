import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProfessionalResultsView } from './ProfessionalResultsView';
import { mockProfessionalQueryResponse } from '../../lib/mocks/professionalMocks';

describe('ProfessionalResultsView Component', () => {
  afterEach(cleanup);

  it('renders identified statutory sections, case brief sections, and precedent tabs', () => {
    render(<ProfessionalResultsView result={mockProfessionalQueryResponse} />);

    // Check identified sections
    expect(screen.getByText('Section 302')).toBeInTheDocument();
    expect(screen.getByText('Section 103(1)')).toBeInTheDocument();

    // Check Case Brief headers
    expect(screen.getByText('1. Executive Summary')).toBeInTheDocument();
    expect(screen.getByText('2. Key Legal Issues')).toBeInTheDocument();
    expect(screen.getByText('Applicable Law')).toBeInTheDocument();
    expect(screen.getByText('Limitations & Legal Risks')).toBeInTheDocument();
  });

  it('switches between structured case brief and precedents tab', () => {
    render(<ProfessionalResultsView result={mockProfessionalQueryResponse} />);

    // Initially Brief tab is active
    expect(screen.getByText('1. Executive Summary')).toBeInTheDocument();

    // Click Precedent Citations tab
    const precedentTabBtn = screen.getByRole('button', { name: /Precedent Citations/i });
    fireEvent.click(precedentTabBtn);

    // Precedent items are now visible
    expect(
      screen.getByRole('heading', { name: 'Sharad Birdhichand Sarda v. State of Maharashtra' }),
    ).toBeInTheDocument();
  });

  it('renders parties, chronology and evidence as separate sections from procedural considerations', () => {
    const result = {
      ...mockProfessionalQueryResponse,
      case_brief: {
        ...mockProfessionalQueryResponse.case_brief,
        parties_and_roles: [
          'Complainant: Meera Placeholder [P1, p. 1]',
          'Accused: Ravi Sampleton [P1, p. 1]',
        ],
        chronology: [
          '2024-03-04 - FIR registered: The FIR was registered on 04-03-2024. [P2, p. 2]',
        ],
        evidence_identified: [
          'Witnesses: My neighbour saw the incident and is an eye-witness. [P1, p. 1]',
        ],
        procedural_considerations: [
          'Investigation: The investigation was entrusted to the SHO. [P2, p. 2]',
        ],
      },
    };
    render(<ProfessionalResultsView result={result} />);

    expect(screen.getByText('Parties & Roles')).toBeInTheDocument();
    expect(screen.getByText('Complainant: Meera Placeholder [P1, p. 1]')).toBeInTheDocument();
    expect(screen.getByText('Accused: Ravi Sampleton [P1, p. 1]')).toBeInTheDocument();
    expect(screen.getByText('Chronology')).toBeInTheDocument();
    expect(screen.queryByText('Chronology / Procedural History')).not.toBeInTheDocument();
    expect(screen.getByText(/2024-03-04 - FIR registered/)).toBeInTheDocument();
    expect(screen.getByText('Evidence Identified')).toBeInTheDocument();
    expect(screen.getByText(/eye-witness/)).toBeInTheDocument();
    expect(screen.getByText(/The investigation was entrusted to the SHO/)).toBeInTheDocument();
  });

  it('hides document sections that are empty instead of padding them', () => {
    const result = {
      ...mockProfessionalQueryResponse,
      case_brief: {
        ...mockProfessionalQueryResponse.case_brief,
        parties_and_roles: [],
        chronology: [],
        evidence_identified: [],
      },
    };
    render(<ProfessionalResultsView result={result} />);

    expect(screen.queryByText('Parties & Roles')).not.toBeInTheDocument();
    expect(screen.queryByText('Evidence Identified')).not.toBeInTheDocument();
  });

  it('copies a null relevance score as "not available"', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    const [first, ...rest] = mockProfessionalQueryResponse.precedents;
    const result = {
      ...mockProfessionalQueryResponse,
      precedents: [{ ...first, relevance_score: null, chunk_id: 'doc:chunk:0001' }, ...rest],
    };
    render(<ProfessionalResultsView result={result} />);

    fireEvent.click(screen.getByRole('button', { name: /Copy Brief/i }));

    const copied = writeTextMock.mock.calls[0]?.[0] as string;
    expect(copied).toContain('Relevance: not available');
    expect(copied).toContain('[doc:chunk:0001]');
    expect(copied).not.toContain('NaN');
  });

  it('copies brief text when Copy Brief is clicked', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<ProfessionalResultsView result={mockProfessionalQueryResponse} />);

    const copyBtn = screen.getByRole('button', { name: /Copy Brief/i });
    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledTimes(1);
    await screen.findByText(/Copied Brief!/i);
  });
});
