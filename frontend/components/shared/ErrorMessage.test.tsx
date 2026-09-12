import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ErrorMessage } from './ErrorMessage';

describe('ErrorMessage', () => {
  afterEach(cleanup);

  it('reveals native technical detail on click and calls Retry from the keyboard', async () => {
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

    const technicalDetail = screen.getByText('Reference service unavailable.');
    const details = technicalDetail.closest('details');
    const disclosure = screen.getByText('Technical details');
    const retryButton = screen.getByRole('button', { name: 'Retry' });

    expect(technicalDetail).not.toBeVisible();
    expect(details).toBeInstanceOf(HTMLDetailsElement);
    expect(disclosure.tagName).toBe('SUMMARY');
    expect(details).toContainElement(disclosure);
    expect(details).not.toHaveAttribute('open');

    await user.click(disclosure);

    expect(details).toHaveAttribute('open');
    expect(technicalDetail).toBeVisible();

    await user.tab();
    expect(retryButton).toHaveFocus();
    await user.keyboard('{Enter}');

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
      expect(screen.getByRole('alert')).toHaveAttribute('data-variant', variant);

      unmount();
    });
  });

  it('contains long unbroken error details within the available width', () => {
    const longFilename = `${'a'.repeat(200)}.txt`;

    render(
      <ErrorMessage
        message={`${longFilename} cannot be added. Choose a PDF file.`}
        title="Unable to add files"
        variant="inline"
      />,
    );

    expect(screen.getByText(/cannot be added/).parentElement).toHaveClass(
      'min-w-0',
      '[overflow-wrap:anywhere]',
    );
  });
});
