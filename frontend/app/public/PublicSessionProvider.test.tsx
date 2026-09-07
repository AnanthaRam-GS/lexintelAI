import { StrictMode, useState } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { PublicSessionProvider, usePublicSession } from './PublicSessionProvider';

function ProviderHarness() {
  const { pendingInput, setPendingInput, takePendingInput } = usePublicSession();
  const [takenInput, setTakenInput] = useState('not consumed');

  return (
    <>
      <output aria-label="Pending input">
        {pendingInput?.kind === 'text' ? `text:${pendingInput.content}` : 'none'}
      </output>
      <button
        onClick={() => setPendingInput({ kind: 'text', content: 'My landlord kept my deposit' })}
        type="button"
      >
        Set text
      </button>
      <output aria-label="Taken input">{takenInput}</output>
      <button
        onClick={() => {
          const input = takePendingInput();
          setTakenInput(input?.kind === 'text' ? `text:${input.content}` : 'none');
        }}
        type="button"
      >
        Consume
      </button>
    </>
  );
}

describe('PublicSessionProvider', () => {
  afterEach(cleanup);

  it('carries one text input through memory and consumes it once', async () => {
    const user = userEvent.setup();

    render(
      <StrictMode>
        <PublicSessionProvider>
          <ProviderHarness />
        </PublicSessionProvider>
      </StrictMode>,
    );

    await user.click(screen.getByRole('button', { name: 'Set text' }));
    expect(screen.getByText('text:My landlord kept my deposit')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Consume' }));
    expect(screen.getByRole('status', { name: 'Pending input' })).toHaveTextContent('none');
    expect(screen.getByRole('status', { name: 'Taken input' })).toHaveTextContent(
      'text:My landlord kept my deposit',
    );

    await user.click(screen.getByRole('button', { name: 'Consume' }));
    expect(screen.getByRole('status', { name: 'Pending input' })).toHaveTextContent('none');
    expect(screen.getByRole('status', { name: 'Taken input' })).toHaveTextContent('none');
  });
});
