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

  it('marks a full-screen spinner without trapping focus', () => {
    render(<LoadingSpinner size="md" fullScreen />);

    expect(screen.getByRole('status')).toHaveAttribute('data-full-screen', 'true');
  });
});
