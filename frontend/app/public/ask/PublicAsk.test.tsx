import { useEffect } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PublicSessionProvider, usePublicSession } from '../PublicSessionProvider';
import type { PublicQueryInput } from '../query-client';

import { PublicAsk } from './PublicAsk';
import type { ChatEntry } from './chat-model';

const examples = [
  'My landlord has not returned my deposit. What can I do?',
  'Can my employer withhold my final salary?',
  'What should I do after receiving a court notice?',
];

function SessionSeed({ input }: { input: { kind: 'text'; content: string } }) {
  const { setPendingInput } = usePublicSession();

  useEffect(() => {
    setPendingInput(input);
  }, [input, setPendingInput]);

  return null;
}

function renderAsk({
  isRequestPending = false,
  onInputSubmitted = vi.fn<(input: PublicQueryInput, entry: ChatEntry) => void>(),
}: {
  isRequestPending?: boolean;
  onInputSubmitted?: (input: PublicQueryInput, entry: ChatEntry) => void;
} = {}) {
  return {
    onInputSubmitted,
    ...render(
      <PublicSessionProvider>
        <PublicAsk isRequestPending={isRequestPending} onInputSubmitted={onInputSubmitted} />
      </PublicSessionProvider>,
    ),
  };
}

async function selectPdf(user: ReturnType<typeof userEvent.setup>, fileName = 'notice.pdf') {
  await user.click(screen.getByRole('button', { name: 'Add one PDF' }));
  const file = new File(['pdf'], fileName, { type: 'application/pdf' });
  const input = screen.getByLabelText('Choose PDF files') as HTMLInputElement;

  await user.upload(input, file);

  return { file, input };
}

describe('PublicAsk', () => {
  afterEach(cleanup);

  it('keeps the conversation name as the page heading', () => {
    renderAsk();

    expect(screen.getByRole('heading', { level: 1, name: 'Your conversation' })).toBeVisible();
  });

  it('offers three realistic empty-state examples that arm text without submitting it', async () => {
    const user = userEvent.setup();
    const { onInputSubmitted } = renderAsk();

    for (const example of examples) {
      expect(screen.getByRole('button', { name: example })).toBeVisible();
    }

    await user.click(screen.getByRole('button', { name: examples[0] }));

    expect(screen.getByLabelText('Your question')).toHaveValue(examples[0]);
    expect(screen.getByText('Active input: Text question')).toBeVisible();
    expect(onInputSubmitted).not.toHaveBeenCalled();
  });

  it('makes text and PDF visibly alternative modes', async () => {
    const user = userEvent.setup();
    renderAsk();

    await user.type(screen.getByLabelText('Your question'), 'Help me understand this');
    expect(screen.getByText('Active input: Text question')).toBeVisible();

    await selectPdf(user);

    expect(screen.getByLabelText('Your question')).toHaveValue('');
    expect(screen.getByText('Active input: Temporary PDF')).toBeVisible();
  });

  it('clears and remounts the selected PDF when a person starts typing', async () => {
    const user = userEvent.setup();
    renderAsk();

    const { input: firstUploadInput } = await selectPdf(user);
    await user.type(screen.getByLabelText('Your question'), 'Explain this notice');

    const replacementUploadInput = screen.getByLabelText('Choose PDF files');
    expect(screen.getByText('Active input: Text question')).toBeVisible();
    expect(screen.queryByText('notice.pdf')).not.toBeInTheDocument();
    expect(replacementUploadInput).not.toBe(firstUploadInput);
  });

  it('switches a selected PDF to text when an empty-state example is chosen', async () => {
    const user = userEvent.setup();
    renderAsk();

    await selectPdf(user);
    await user.click(screen.getByRole('button', { name: examples[1] }));

    expect(screen.getByLabelText('Your question')).toHaveValue(examples[1]);
    expect(screen.getByText('Active input: Text question')).toBeVisible();
    expect(screen.queryByText('notice.pdf')).not.toBeInTheDocument();
  });

  it('submits an armed text question when Enter is pressed', async () => {
    const user = userEvent.setup();
    const { onInputSubmitted } = renderAsk();

    await user.type(screen.getByLabelText('Your question'), 'Can my employer keep my pay?{Enter}');

    expect(screen.getByText('Can my employer keep my pay?')).toBeVisible();
    expect(onInputSubmitted).toHaveBeenCalledWith(
      { kind: 'text', content: 'Can my employer keep my pay?' },
      expect.objectContaining({
        id: expect.any(String),
        message: { role: 'user', kind: 'text', content: 'Can my employer keep my pay?' },
      }),
    );
    expect(screen.getByLabelText('Your question')).toHaveValue('');
  });

  it('keeps a newline in an armed text question when Shift+Enter is pressed', async () => {
    const user = userEvent.setup();
    const { onInputSubmitted } = renderAsk();

    await user.type(
      screen.getByLabelText('Your question'),
      'First line{Shift>}{Enter}{/Shift}Second line',
    );

    expect(screen.getByLabelText('Your question')).toHaveValue('First line\nSecond line');
    expect(onInputSubmitted).not.toHaveBeenCalled();
  });

  it('does not submit whitespace-only text', async () => {
    const user = userEvent.setup();
    const { onInputSubmitted } = renderAsk();

    await user.type(screen.getByLabelText('Your question'), '   {Enter}');

    expect(screen.getByText('Choose text or one PDF')).toBeVisible();
    expect(onInputSubmitted).not.toHaveBeenCalled();
  });

  it('disables both composer modes while a request is pending', () => {
    renderAsk({ isRequestPending: true });

    expect(screen.getByLabelText('Your question')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Add one PDF' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  it('consumes a landing handoff once and adds its user turn to the thread', async () => {
    const submitted = vi.fn();

    render(
      <PublicSessionProvider>
        <SessionSeed input={{ kind: 'text', content: 'I received a court notice' }} />
        <PublicAsk onInputSubmitted={submitted} />
      </PublicSessionProvider>,
    );

    expect(await screen.findByText('I received a court notice')).toBeVisible();
    expect(submitted).toHaveBeenCalledTimes(1);
  });

  it('asks for confirmation before clearing a conversation with multiple messages', async () => {
    const user = userEvent.setup();
    renderAsk();

    await user.type(screen.getByLabelText('Your question'), 'First question{Enter}');
    await user.type(screen.getByLabelText('Your question'), 'Second question{Enter}');
    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));

    expect(screen.getByRole('region', { name: 'Confirm new conversation' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByText('First question')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start New Conversation' })).toHaveFocus();

    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));
    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(screen.queryByText('First question')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Your question')).toHaveFocus();
  });
});
