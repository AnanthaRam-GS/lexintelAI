import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { CitationCard } from './CitationCard';

describe('CitationCard Component', () => {
  afterEach(cleanup);

  const mockPrecedent = {
    document_id: 'SC_1984_CRIM_162',
    case_name: 'Sharad Birdhichand Sarda v. State of Maharashtra',
    court: 'Supreme Court of India',
    year: 1984,
    relevance_score: 0.95,
    excerpt:
      'In circumstantial evidence cases, the circumstances from which the conclusion of guilt is drawn must be fully established.',
    source_url: 'https://main.sci.gov.in/judgments/1984/SC_1984_CRIM_162.pdf',
    page_start: 14,
    page_end: 18,
    paragraph_start: 152,
    paragraph_end: 158,
  };

  it('renders precedent case name, court, year, and relevance percentage', () => {
    render(<CitationCard precedent={mockPrecedent} />);

    expect(
      screen.getByRole('heading', { name: 'Sharad Birdhichand Sarda v. State of Maharashtra' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Supreme Court of India')).toBeInTheDocument();
    expect(screen.getByText('1984')).toBeInTheDocument();
    expect(screen.getByText('95%')).toBeInTheDocument();
    expect(screen.getByText('SC_1984_CRIM_162')).toBeInTheDocument();
  });

  it('displays pinpoint citations and judgment source link', () => {
    render(<CitationCard precedent={mockPrecedent} />);

    expect(screen.getByText('pp. 14–18')).toBeInTheDocument();
    expect(screen.getByText('¶ 152–158')).toBeInTheDocument();

    const link = screen.getByRole('link', { name: /View Judgment/i });
    expect(link).toHaveAttribute('href', mockPrecedent.source_url);
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('handles excerpt toggle when excerpt is long', () => {
    const longExcerptPrecedent = {
      ...mockPrecedent,
      excerpt:
        'A very long legal excerpt exceeding one hundred and eighty characters in length to verify the accordion toggle works cleanly and reveals the complete text on demand without causing layout breaks in the professional mode.',
    };

    render(<CitationCard precedent={longExcerptPrecedent} />);

    const toggleButton = screen.getByRole('button', { name: /Read full excerpt/i });
    expect(toggleButton).toBeInTheDocument();

    fireEvent.click(toggleButton);
    expect(screen.getByRole('button', { name: /Show less/i })).toBeInTheDocument();
  });
});
