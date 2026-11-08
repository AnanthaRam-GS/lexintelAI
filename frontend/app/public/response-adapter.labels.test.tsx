import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ResponseCard } from '../../components/shared';
import { toPublicResponseCardProps } from './response-adapter';
import type { PublicQueryResponse } from './query-client';

const GENERATED = 'generated_from_grounded_answer';
const link = 'https://www.indiacode.nic.in/';
const explanation = 'Applicability depends on the specific facts and documents.';

// Public "Related law" sections as the backend resolves the three step 25 model errors and an unverified one.
const response: PublicQueryResponse = {
  explanation: 'What this may mean.',
  nextStepGuidance: 'Speak to a lawyer.',
  sources: [],
  sections: [
    {
      title: 'Section 309(4) BNS — Robbery',
      explanation,
      link,
      references: [
        {
          statute: 'BNS',
          section: '309(4)',
          context: GENERATED,
          label: { state: 'verified', title: 'Robbery' },
        },
      ],
    },
    {
      title:
        'Section 173 BNSS — registration of FIR (statute corrected from BNS; unverified label)',
      explanation,
      link,
      references: [
        {
          statute: 'BNSS',
          section: '173',
          context: GENERATED,
          label: {
            state: 'corrected_statute',
            model_label: 'registration of FIR',
            statute_corrected_from: 'BNS',
          },
        },
      ],
    },
    {
      title: 'Section 113B Evidence Act — presumption (unverified label)',
      explanation,
      link,
      references: [
        {
          statute: 'Evidence Act',
          section: '113B',
          context: GENERATED,
          label: { state: 'unverified', model_label: 'presumption' },
        },
      ],
    },
    {
      title: 'Section 900 BNS (title not shown: trusted sources disagree)',
      explanation,
      link,
      references: [
        { statute: 'BNS', section: '900', context: GENERATED, label: { state: 'conflict' } },
      ],
    },
  ],
};

describe('public sections with resolved labels (step 25)', () => {
  afterEach(cleanup);

  it('builds each title from the resolved label, with a marker and note where needed', () => {
    const sections = toPublicResponseCardProps(response).sections;
    expect(sections.map((s) => [s.title, s.labelMarker, s.labelNote])).toEqual([
      ['Section 309(4) BNS — Robbery', null, null],
      [
        'Section 173 BNSS — registration of FIR',
        'unverified',
        'Statute corrected: the answer cited BNS 173.',
      ],
      ['Section 113B Evidence Act — presumption', 'unverified', null],
      ['Section 900 BNS', 'conflict', 'Title not shown: the trusted sources disagree.'],
    ]);
  });

  it('renders the markers and notes in the Related law list', () => {
    render(<ResponseCard {...toPublicResponseCardProps(response)} />);
    expect(
      screen.getByRole('heading', { name: 'Section 309(4) BNS — Robbery' }),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId('section-label-marker').map((node) => node.textContent)).toEqual([
      'Unverified label',
      'Unverified label',
      'Sources disagree',
    ]);
    expect(screen.getByText('Statute corrected: the answer cited BNS 173.')).toBeInTheDocument();
  });
});
