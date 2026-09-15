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
      screen.getByRole('heading', { name: 'Sharad Birdhichand Sarda v. State of Maharashtra' })
    ).toBeInTheDocument();
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
