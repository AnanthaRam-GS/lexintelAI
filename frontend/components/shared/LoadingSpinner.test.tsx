import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { LoadingSpinner } from './LoadingSpinner';

describe('LoadingSpinner', () => {
  afterEach(cleanup);

  it('announces its label and applies the requested size', () => {
    render(<LoadingSpinner size="lg" label="Loading legal analysis" />);

    expect(screen.getByRole('status', { name: 'Loading legal analysis' })).toHaveAttribute(
      'data-size',
      'lg',
    );
  });

  it('marks a full-screen spinner and preserves focus on an existing control', () => {
    const { rerender } = render(
      <>
        <button type="button">Continue</button>
        <LoadingSpinner size="md" />
      </>,
    );

    const control = screen.getByRole('button', { name: 'Continue' });
    control.focus();

    rerender(
      <>
        <button type="button">Continue</button>
        <LoadingSpinner size="md" fullScreen />
      </>,
    );

    expect(screen.getByRole('status')).toHaveAttribute('data-full-screen', 'true');
    expect(control).toHaveFocus();
  });

  it('uses CSS reduced-motion suppression for its animated ring', () => {
    render(<LoadingSpinner />);

    const ring = screen.getByRole('status').querySelector('[aria-hidden="true"]');

    expect(ring).toHaveClass('animate-spin', 'motion-reduce:animate-none');
    expect(ring).not.toHaveAttribute('style');
  });
});
