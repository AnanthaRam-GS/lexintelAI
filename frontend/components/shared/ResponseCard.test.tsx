import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ResponseCard } from './ResponseCard';

const content = {
  heading: 'Rights after an arrest',
  paragraphs: [
    'You have a right to be told why you are being arrested.',
    '<strong>This must be rendered as text, not HTML.</strong>',
  ],
  keyPoints: ['Ask to contact a lawyer.', 'Keep a copy of the arrest memo.'],
};

const citations = [
  {
    title: 'D.K. Basu v. State of West Bengal',
    court: 'Supreme Court of India',
    year: 1997,
    sourceUrl: 'https://example.com/dk-basu',
    excerpt: 'Arrested people have protections against arbitrary detention.',
  },
];

const sections = [
  {
    code: 'BNSS',
    section: '47',
    title: 'Person arrested not to be detained more than twenty-four hours',
    explanation:
      'The arrested person must be produced before a magistrate within twenty-four hours.',
    sourceUrl: 'https://example.com/bnss-47',
    confidence: 82,
  },
];

describe('ResponseCard', () => {
  afterEach(cleanup);

  it('shows research metadata and confidence only to professionals', () => {
    const { rerender } = render(
      <ResponseCard
        citations={citations}
        content={content}
        mode="professional"
        sections={sections}
      />,
    );

    expect(screen.getByText('Supreme Court of India')).toBeInTheDocument();
    expect(screen.getByText('82% confidence')).toBeInTheDocument();
    expect(
      screen.getByText('Arrested people have protections against arbitrary detention.'),
    ).toBeInTheDocument();

    rerender(
      <ResponseCard citations={citations} content={content} mode="public" sections={sections} />,
    );

    expect(screen.queryByText('Supreme Court of India')).not.toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText('Arrested people have protections against arbitrary detention.'),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Learn more' })).not.toHaveLength(0);
  });

  it('uses safe external links in both response modes', () => {
    const { rerender } = render(
      <ResponseCard
        citations={citations}
        content={content}
        mode="professional"
        sections={sections}
      />,
    );

    screen.getAllByRole('link').forEach((link) => {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noreferrer');
    });

    rerender(
      <ResponseCard citations={citations} content={content} mode="public" sections={sections} />,
    );

    screen.getAllByRole('link', { name: 'Learn more' }).forEach((link) => {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noreferrer');
    });
  });

  it('keeps absent and partial citation metadata free from separator artifacts', () => {
    render(
      <ResponseCard
        citations={[
          {
            title: 'Plain citation',
            sourceUrl: 'https://example.com/plain-citation',
          },
          {
            title: 'Court only citation',
            court: 'High Court of Delhi',
            sourceUrl: 'https://example.com/court-only-citation',
          },
          {
            title: 'Year only citation',
            year: 2024,
            sourceUrl: 'https://example.com/year-only-citation',
          },
        ]}
        content={content}
        mode="professional"
        sections={[]}
      />,
    );

    const plainCitation = screen.getByText('Plain citation').closest('li');
    const courtOnlyCitation = screen.getByText('Court only citation').closest('li');
    const yearOnlyCitation = screen.getByText('Year only citation').closest('li');

    expect(plainCitation).toHaveTextContent('Plain citation');
    expect(plainCitation).not.toHaveTextContent(/[·,|–—]/);
    expect(courtOnlyCitation).toHaveTextContent('High Court of Delhi');
    expect(courtOnlyCitation).not.toHaveTextContent(/[·,|–—]/);
    expect(yearOnlyCitation).toHaveTextContent('2024');
    expect(yearOnlyCitation).not.toHaveTextContent(/[·,|–—]/);
  });

  it('keeps every labelled region tied to a unique heading in its own card', () => {
    render(
      <>
        <ResponseCard
          citations={citations}
          content={content}
          mode="professional"
          sections={sections}
        />
        <ResponseCard
          citations={citations}
          content={content}
          mode="professional"
          sections={sections}
        />
        <ResponseCard citations={citations} content={content} mode="public" sections={sections} />
        <ResponseCard citations={citations} content={content} mode="public" sections={sections} />
      </>,
    );

    const cards = [
      ...screen.getAllByLabelText('Professional legal research response'),
      ...screen.getAllByLabelText('Plain-language legal information'),
    ];
    const labelledRegions = cards.flatMap((card) =>
      Array.from(card.querySelectorAll<HTMLElement>('[aria-labelledby]')),
    );
    const headingIds = labelledRegions.map((region) => region.getAttribute('aria-labelledby'));

    expect(new Set(headingIds).size).toBe(headingIds.length);
    labelledRegions.forEach((region) => {
      const heading = document.getElementById(region.getAttribute('aria-labelledby') ?? '');

      expect(heading).not.toBeNull();
      expect(region.closest('article')).toContainElement(heading);
    });
  });

  it('renders response paragraphs as text instead of raw HTML', () => {
    render(<ResponseCard citations={[]} content={content} mode="public" sections={[]} />);

    expect(
      screen.getByText('<strong>This must be rendered as text, not HTML.</strong>'),
    ).toBeInTheDocument();
    expect(document.querySelector('strong')).toBeNull();
  });

  it('clamps professional confidence to the inclusive 0–100 range', () => {
    render(
      <ResponseCard
        citations={[]}
        content={content}
        mode="professional"
        sections={[
          {
            ...sections[0],
            confidence: 142.6,
          },
          {
            ...sections[0],
            section: '48',
            confidence: -3,
          },
        ]}
      />,
    );

    expect(screen.getByText('100% confidence')).toBeInTheDocument();
    expect(screen.getByText('0% confidence')).toBeInTheDocument();
  });
});
