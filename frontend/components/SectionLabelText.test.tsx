import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { SectionBadge } from './SectionBadge';
import { SectionLabelText } from './SectionLabelText';
import { ProfessionalResultsView } from './professional/ProfessionalResultsView';
import { mockProfessionalQueryResponse } from '../lib/mocks/professionalMocks';
import type { SectionReference } from '../lib/types/api';

const GENERATED = 'generated_from_grounded_answer';

// The three model errors from the step 25 brief, as the backend resolves them.
const verifiedRobbery: SectionReference = {
  statute: 'BNS',
  section: '309(4)',
  context: GENERATED,
  label: {
    state: 'verified',
    title: 'Robbery',
    source: 'section_catalog',
    source_key: 'BNS 309',
    note: "The answer's own label for this section did not match the trusted title and is not shown.",
  },
};
const correctedFir: SectionReference = {
  statute: 'BNSS',
  section: '173',
  context: GENERATED,
  label: {
    state: 'corrected_statute',
    title: null,
    model_label: 'registration of FIR',
    statute_corrected_from: 'BNS',
    source: 'section_catalog',
    source_key: 'BNSS 173(4)',
  },
};
const correctedMurder: SectionReference = {
  statute: 'BNS',
  section: '103',
  context: GENERATED,
  label: { state: 'corrected_statute', title: 'Murder', statute_corrected_from: 'BNSS' },
};
const unverified: SectionReference = {
  statute: 'Evidence Act',
  section: '113B',
  context: GENERATED,
  label: { state: 'unverified', model_label: 'presumption as to dowry death' },
};
const conflict: SectionReference = {
  statute: 'BNS',
  section: '900',
  context: GENERATED,
  label: { state: 'conflict', source: 'ipc_bns_mapping' },
};

function renderLabel(reference: SectionReference) {
  render(<SectionLabelText reference={reference} />);
  return screen.getByTestId('section-label');
}

describe('SectionLabelText', () => {
  afterEach(cleanup);

  it('verified: shows the trusted title with no marker', () => {
    const label = renderLabel(verifiedRobbery);
    expect(label).toHaveAttribute('data-label-state', 'verified');
    expect(label).toHaveTextContent('Section 309(4) BNS — Robbery');
    expect(screen.queryByTestId('section-label-marker')).toBeNull();
    expect(label).not.toHaveTextContent(/suicide/i);
  });

  it('corrected statute without a trusted title: the answer wording is marked unverified, with a note', () => {
    const label = renderLabel(correctedFir);
    expect(label).toHaveAttribute('data-label-state', 'corrected_statute');
    expect(label).toHaveTextContent('Section 173 BNSS — registration of FIR');
    expect(screen.getByTestId('section-label-marker')).toHaveTextContent('Unverified label');
    expect(screen.getByTestId('section-label-note')).toHaveTextContent(
      'Statute corrected: the answer cited BNS 173.',
    );
  });

  it('corrected statute with a trusted title: no marker, a note', () => {
    const label = renderLabel(correctedMurder);
    expect(label).toHaveTextContent('Section 103 BNS — Murder');
    expect(screen.queryByTestId('section-label-marker')).toBeNull();
    expect(screen.getByTestId('section-label-note')).toHaveTextContent('the answer cited BNSS 103');
  });

  it('unverified: keeps the answer wording with the unverified marker', () => {
    const label = renderLabel(unverified);
    expect(label).toHaveAttribute('data-label-state', 'unverified');
    expect(label).toHaveTextContent('Section 113B Evidence Act — presumption as to dowry death');
    expect(screen.getByTestId('section-label-marker')).toHaveTextContent('Unverified label');
  });

  it('conflict: shows no title and says the sources disagree', () => {
    const label = renderLabel(conflict);
    expect(label).toHaveAttribute('data-label-state', 'conflict');
    expect(label).toHaveTextContent('Section 900 BNS');
    expect(screen.getByTestId('section-label-marker')).toHaveTextContent('Sources disagree');
    expect(screen.getByTestId('section-label-note')).toHaveTextContent(
      'Title not shown: the trusted sources disagree.',
    );
  });

  it('a provision with no readable section is shown as written and marked unverified', () => {
    renderLabel({
      statute: 'Unspecified',
      section: 'Theft provisions',
      context: GENERATED,
      label: { state: 'unverified', model_label: 'Theft provisions' },
    });
    expect(screen.getByTestId('section-label')).toHaveTextContent('Theft provisions');
    expect(screen.getByTestId('section-label-marker')).toHaveTextContent('Unverified label');
  });
});

describe('SectionBadge with a resolved label', () => {
  afterEach(cleanup);

  it('shows the section, the trusted title and never the answer label', () => {
    render(<SectionBadge section={verifiedRobbery} />);
    const badge = screen.getByTestId('section-badge');
    expect(badge).toHaveTextContent('Section 309(4)');
    expect(badge).toHaveTextContent('Robbery');
    expect(badge).not.toHaveTextContent(/suicide/i);
  });

  it('marks an unverified label', () => {
    render(<SectionBadge section={unverified} />);
    expect(screen.getByTestId('section-label-marker')).toHaveTextContent('Unverified label');
  });
});

describe('ProfessionalResultsView explicit provisions', () => {
  afterEach(cleanup);

  it('lists provisions from the resolved references, one state each', () => {
    const result = {
      ...mockProfessionalQueryResponse,
      identified_sections: [verifiedRobbery, correctedFir, unverified, conflict],
      case_brief: {
        ...mockProfessionalQueryResponse.case_brief,
        statutory_provisions: [
          'Section 309(4) BNS — Robbery',
          'Section 173 BNSS — registration of FIR (statute corrected from BNS; unverified label)',
        ],
        statutory_provision_references: [verifiedRobbery, correctedFir, unverified, conflict],
      },
    };
    render(<ProfessionalResultsView result={result} />);
    const provisions = screen.getByTestId('statutory-provisions');
    const states = Array.from(provisions.querySelectorAll('[data-testid="section-label"]')).map(
      (node) => node.getAttribute('data-label-state'),
    );
    expect(states).toEqual(['verified', 'corrected_statute', 'unverified', 'conflict']);
    expect(provisions).toHaveTextContent('Section 309(4) BNS — Robbery');
    expect(document.body).not.toHaveTextContent(/suicide/i);
  });

  it('marks provisions from older history entries as unverified', () => {
    const result = {
      ...mockProfessionalQueryResponse,
      case_brief: {
        ...mockProfessionalQueryResponse.case_brief,
        statutory_provisions: ['Section 309(4) BNS – offences relating to suicide attempts.'],
        statutory_provision_references: undefined,
      },
    };
    render(<ProfessionalResultsView result={result} />);
    const provisions = screen.getByTestId('statutory-provisions');
    expect(provisions.querySelector('[data-testid="section-label-marker"]')).toHaveTextContent(
      'Unverified label',
    );
  });
});
