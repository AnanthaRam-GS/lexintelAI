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
      />
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
      />
    );

    const toggleButton = screen.getByRole('button', { name: /Toggle description for Section 103\(1\)/i });
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
      />
    );
    expect(screen.getByText('CrPC')).toBeInTheDocument();

    rerender(
      <SectionBadge
        section={{
          statute: 'Bharatiya Nagarik Suraksha Sanhita, 2023',
          section: 'Section 480',
        }}
      />
    );
    expect(screen.getByText('BNSS')).toBeInTheDocument();
  });
});
