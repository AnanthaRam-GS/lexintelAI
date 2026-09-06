import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ErrorMessage } from './ErrorMessage';

describe('ErrorMessage', () => {
  afterEach(cleanup);

  it('calls retry and keeps technical detail collapsed by default', async () => {
    const retry = vi.fn();
    const user = userEvent.setup();

    render(
      <ErrorMessage
        message="We could not finish this request."
        onRetry={retry}
        technicalDetail="Reference service unavailable."
        title="Try again"
        variant="banner"
      />,
    );

    expect(screen.getByText('Reference service unavailable.')).not.toBeVisible();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Retry' }));

    expect(retry).toHaveBeenCalledOnce();
  });

  it('announces every variant with its plain-language title and message', () => {
    (['inline', 'banner', 'fullpage'] as const).forEach((variant) => {
      const { unmount } = render(
        <ErrorMessage
          message={`Message for ${variant}`}
          title={`Title for ${variant}`}
          variant={variant}
        />,
      );

      expect(screen.getByRole('alert')).toHaveTextContent(`Title for ${variant}`);
      expect(screen.getByRole('alert')).toHaveTextContent(`Message for ${variant}`);

      unmount();
    });
  });
});
