import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { SectionBadge } from './SectionBadge';

describe('SectionBadge Component', () => {
  afterEach(cleanup);

  it('renders statute prefix, section number, and confidence score', () => {
    render(
      <SectionBadge
        section={{
          statute: 'Indian Penal Code, 1860',
          section: 'Section 302',
          confidence: 0.95,
          context: 'Punishment for murder',
        }}
      />,
    );

    expect(screen.getByText('IPC')).toBeInTheDocument();
    expect(screen.getByText('Section 302')).toBeInTheDocument();
    expect(screen.getByText('95%')).toBeInTheDocument();
  });

  it('toggles contextual explanation on button click when context is provided', () => {
    render(
      <SectionBadge
        section={{
          statute: 'Bharatiya Nyaya Sanhita, 2023',
          section: 'Section 103(1)',
          confidence: 0.92,
          context: 'Offence of murder maintaining requirement of bodily injury intention.',
        }}
      />,
    );

    const toggleButton = screen.getByRole('button', {
      name: /Toggle description for Section 103\(1\)/i,
    });
    expect(screen.queryByText(/Offence of murder/i)).not.toBeInTheDocument();

    fireEvent.click(toggleButton);
    expect(screen.getByText(/Offence of murder/i)).toBeInTheDocument();

    fireEvent.click(toggleButton);
    expect(screen.queryByText(/Offence of murder/i)).not.toBeInTheDocument();
  });

  it('applies the appropriate styling prefix for different statutes', () => {
    const { rerender } = render(
      <SectionBadge
        section={{
          statute: 'Code of Criminal Procedure, 1973',
          section: 'Section 437',
        }}
      />,
    );
    expect(screen.getByText('CrPC')).toBeInTheDocument();

    rerender(
      <SectionBadge
        section={{
          statute: 'Bharatiya Nagarik Suraksha Sanhita, 2023',
          section: 'Section 480',
        }}
      />,
    );
    expect(screen.getByText('BNSS')).toBeInTheDocument();
  });

  describe('statute prefix matching (step 27: exact, never by substring)', () => {
    const prefixFor = (statute: string) => {
      render(<SectionBadge section={{ statute, section: '173' }} />);
      const prefix = screen.getByTestId('statute-prefix').textContent;
      cleanup();
      return prefix;
    };

    it.each([
      ['BNSS', 'BNSS'],
      ['Bharatiya Nagarik Suraksha Sanhita, 2023', 'BNSS'],
      ['BNS', 'BNS'],
      ['Bharatiya Nyaya Sanhita', 'BNS'],
      ['BSA', 'BSA'],
      ['Bharatiya Sakshya Adhiniyam, 2023', 'BSA'],
      ['IPC', 'IPC'],
      ['Indian Penal Code, 1860', 'IPC'],
      ['CrPC', 'CrPC'],
      ['Cr.P.C.', 'CrPC'],
      ['Code of Criminal Procedure, 1973', 'CrPC'],
      ['Evidence Act', 'IEA'],
      ['The Indian Evidence Act, 1872', 'IEA'],
      ['NDPS Act', 'NDPS'],
      ['POCSO Act', 'POCSO'],
      ['SC/ST Act', 'SC/ST'],
    ])('%s -> %s', (statute, expected) => {
      expect(prefixFor(statute)).toBe(expected);
    });

    it('matches regardless of case and spacing', () => {
      expect(prefixFor('bnss')).toBe('BNSS');
      expect(prefixFor('  bNsS ')).toBe('BNSS');
      expect(prefixFor('bharatiya NAGARIK suraksha sanhita')).toBe('BNSS');
      expect(prefixFor('Bharatiya Nagarik Suraksha Sanhita (BNSS)')).toBe('BNSS');
    });

    it('gives an unknown statute the neutral ACT badge instead of a guessed code', () => {
      expect(prefixFor('Arms Act')).toBe('ACT');
      expect(prefixFor('BNSSX')).toBe('ACT');
      expect(prefixFor('Unspecified')).toBe('ACT');
      // Substring matching would have read these as IPC or BSA.
      expect(prefixFor('Principles of Natural Justice')).toBe('ACT');
      expect(prefixFor('BSAX Rules')).toBe('ACT');
    });

    it('shows the corrected statute for a corrected-statute label (BNS 173 -> BNSS 173)', () => {
      render(
        <SectionBadge
          section={{
            statute: 'BNSS',
            section: '173',
            context: 'generated_from_grounded_answer',
            label: {
              state: 'corrected_statute',
              title: 'Information in cognizable cases',
              source: 'official_heading',
              statute_corrected_from: 'BNS',
              model_label: 'registration of FIR',
              correction_reason: 'label',
            },
          }}
        />,
      );
      expect(screen.getByTestId('statute-prefix')).toHaveTextContent(/^BNSS$/);
      const badge = screen.getByTestId('section-badge');
      expect(badge).toHaveTextContent('Information in cognizable cases');
      expect(badge).toHaveTextContent('Statute corrected: the answer cited BNS 173.');
    });
  });
});
