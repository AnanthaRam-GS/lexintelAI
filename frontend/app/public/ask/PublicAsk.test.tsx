import { useEffect } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PublicSessionProvider, usePublicSession } from '../PublicSessionProvider';
import type { PublicQueryInput, PublicQueryResponse } from '../query-client';

import { PublicAsk, type PublicAskProps } from './PublicAsk';
import type { ChatEntry } from './chat-model';

const { fetchPublicQuery } = vi.hoisted(() => ({
  fetchPublicQuery: vi.fn<(input: PublicQueryInput) => Promise<PublicQueryResponse>>(),
}));

vi.mock('../query-client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../query-client')>();

  return { ...original, fetchPublicQuery };
});

const examples = [
  'My landlord has not returned my deposit. What can I do?',
  'Can my employer withhold my final salary?',
  'What should I do after receiving a court notice?',
];

const responseFixture: PublicQueryResponse = {
  explanation: 'A written notice can help create a clear record of what happened.',
  sections: [
    {
      title: 'Indian Contract Act, 1872',
      explanation: 'The agreement may explain the steps each side must follow.',
      link: 'https://www.indiacode.nic.in/',
    },
  ],
  sources: [{ title: 'India Code', link: 'https://www.indiacode.nic.in/' }],
  nextStepGuidance: 'Keep copies of the notice and agreement before you respond.',
};

interface Deferred<T> {
  promise: Promise<T>;
  reject: (reason?: unknown) => void;
  resolve: (value: T) => void;
}

function createDeferred<T>(): Deferred<T> {
  let reject!: Deferred<T>['reject'];
  let resolve!: Deferred<T>['resolve'];
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });

  return { promise, reject, resolve };
}

function neverSettles(): Promise<PublicQueryResponse> {
  return new Promise(() => undefined);
}

function SessionSeed({ input }: { input: PublicQueryInput }) {
  const { setPendingInput } = usePublicSession();

  useEffect(() => {
    setPendingInput(input);
  }, [input, setPendingInput]);

  return null;
}

function PublicAskWithSession(props: PublicAskProps) {
  return (
    <PublicSessionProvider>
      <PublicAsk {...props} />
    </PublicSessionProvider>
  );
}

function renderAsk({
  isRequestPending = false,
  onInputSubmitted = vi.fn<(input: PublicQueryInput, entry: ChatEntry) => void>(),
  onNewConversation,
  onRetry,
}: PublicAskProps = {}) {
  return {
    onInputSubmitted,
    ...render(
      <PublicAskWithSession
        isRequestPending={isRequestPending}
        onInputSubmitted={onInputSubmitted}
        onNewConversation={onNewConversation}
        onRetry={onRetry}
      />,
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

async function submitText(user: ReturnType<typeof userEvent.setup>, content: string) {
  await user.type(screen.getByLabelText('Your question'), `${content}{Enter}`);
}

describe('PublicAsk', () => {
  beforeEach(() => {
    fetchPublicQuery.mockReset();
    fetchPublicQuery.mockImplementation(neverSettles);
  });

  afterEach(cleanup);

  it('keeps the conversation name as the page heading', () => {
    renderAsk();

    expect(screen.getByRole('heading', { level: 1, name: 'Your conversation' })).toBeVisible();
  });

  it('keeps the submitted turn visible while an inline assistant loading row is pending', async () => {
    const user = userEvent.setup();
    renderAsk();

    await submitText(user, 'Can my employer keep my final pay?');

    expect(screen.getByText('Can my employer keep my final pay?')).toBeVisible();
    expect(screen.getByRole('status', { name: 'Finding a clear answer' })).toBeVisible();
  });

  it('renders successful text answers only through the public response adapter', async () => {
    const user = userEvent.setup();
    const responseWithPrivateFields = {
      ...responseFixture,
      confidence: 97,
      metadata: 'private-retrieval-id',
    } as PublicQueryResponse;
    fetchPublicQuery.mockResolvedValueOnce(responseWithPrivateFields);
    renderAsk();

    await submitText(user, 'What does this notice mean?');

    const response = await screen.findByRole('article', {
      name: 'Plain-language legal information',
    });
    expect(response).toHaveTextContent('What this may mean for you');
    expect(response).toHaveTextContent(responseFixture.explanation);
    expect(response).toHaveTextContent('What you can do');
    expect(response).toHaveTextContent('Indian Contract Act, 1872');
    expect(response).toHaveTextContent('India Code');
    expect(response).not.toHaveTextContent('97% confidence');
    expect(response).not.toHaveTextContent('private-retrieval-id');
  });

  it('sends the original PDF object and renders its successful public answer', async () => {
    const user = userEvent.setup();
    fetchPublicQuery.mockResolvedValueOnce({
      ...responseFixture,
      explanation: 'The PDF appears to be a notice asking for a written response.',
    });
    renderAsk();

    const { file } = await selectPdf(user);
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(fetchPublicQuery).toHaveBeenCalledTimes(1);
    const submittedInput = fetchPublicQuery.mock.calls[0]?.[0];
    expect(submittedInput?.kind).toBe('file');
    if (submittedInput?.kind === 'file') {
      expect(submittedInput.file).toBe(file);
    }
    expect(
      await screen.findByRole('article', { name: 'Plain-language legal information' }),
    ).toHaveTextContent('The PDF appears to be a notice asking for a written response.');
  });

  it('never renders a caught value, including in accessibility attributes', async () => {
    const user = userEvent.setup();
    const privateFailure = '/private/path database timeout';
    fetchPublicQuery.mockRejectedValueOnce(new Error(privateFailure));
    renderAsk();

    await submitText(user, 'What can I do?');

    const error = await screen.findByRole('alert');
    expect(error).toHaveTextContent("We couldn't answer that just now.");
    expect(error).toHaveTextContent('Your question is still here—please try again.');
    expect(document.body).not.toHaveTextContent(privateFailure);
    expect(
      Array.from(document.querySelectorAll('*')).some((element) =>
        Array.from(element.attributes).some((attribute) =>
          attribute.value.includes(privateFailure),
        ),
      ),
    ).toBe(false);
  });

  it('retries the exact failed text turn without duplicating its user message', async () => {
    const user = userEvent.setup();
    const retryDeferred = createDeferred<PublicQueryResponse>();
    fetchPublicQuery
      .mockRejectedValueOnce(new Error('/private/path database timeout'))
      .mockReturnValueOnce(retryDeferred.promise);
    renderAsk();

    await submitText(user, 'What can I do?');
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    expect(fetchPublicQuery).toHaveBeenNthCalledWith(2, {
      kind: 'text',
      content: 'What can I do?',
    });
    expect(screen.getAllByText('What can I do?')).toHaveLength(1);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Finding a clear answer' })).toBeVisible();

    await act(async () => retryDeferred.resolve(responseFixture));
    expect(
      await screen.findByRole('article', { name: 'Plain-language legal information' }),
    ).toBeVisible();
  });

  it('retains the same in-memory File object for an exact PDF retry', async () => {
    const user = userEvent.setup();
    const retryDeferred = createDeferred<PublicQueryResponse>();
    fetchPublicQuery
      .mockRejectedValueOnce(new Error('provider failed'))
      .mockReturnValueOnce(retryDeferred.promise);
    renderAsk();

    const { file } = await selectPdf(user);
    await user.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    const retriedInput = fetchPublicQuery.mock.calls[1]?.[0];
    expect(retriedInput?.kind).toBe('file');
    if (retriedInput?.kind === 'file') {
      expect(retriedInput.file).toBe(file);
    }
    expect(screen.getAllByRole('article', { name: 'Temporary PDF: notice.pdf' })).toHaveLength(1);

    await act(async () => retryDeferred.resolve(responseFixture));
  });

  it('allows only one request and one user turn during rapid repeated submission', async () => {
    const user = userEvent.setup();
    renderAsk();
    await user.type(screen.getByLabelText('Your question'), 'Please explain this notice');
    const send = screen.getByRole('button', { name: 'Send' });

    fireEvent.click(send);
    fireEvent.click(send);

    expect(fetchPublicQuery).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText('Please explain this notice')).toHaveLength(1);
    expect(screen.getByLabelText('Your question')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Add one PDF' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  it('serializes a re-entrant submission before notifying the composer observer', async () => {
    const user = userEvent.setup();
    const submitted = vi.fn(() => {
      if (submitted.mock.calls.length === 1) {
        const form = screen.getByRole('button', { name: 'Send' }).closest('form');

        if (!form) {
          throw new Error('Expected the Send button to belong to the composer form.');
        }
        fireEvent.submit(form);
      }
    });
    renderAsk({ onInputSubmitted: submitted });

    await user.type(screen.getByLabelText('Your question'), 'Explain this once');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(fetchPublicQuery).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText('Explain this once')).toHaveLength(1);
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

  it('prevents bare Enter from changing an armed PDF mode', async () => {
    const user = userEvent.setup();
    const { onInputSubmitted } = renderAsk();
    await selectPdf(user);

    const question = screen.getByLabelText('Your question');
    await user.click(question);
    await user.keyboard('{Enter}');

    expect(question).toHaveValue('');
    expect(screen.getByText('Active input: Temporary PDF')).toBeVisible();
    expect(screen.getByText('notice.pdf')).toBeVisible();
    expect(onInputSubmitted).not.toHaveBeenCalled();
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

  it('prevents bare Enter when no input mode is armed', async () => {
    const user = userEvent.setup();
    const { onInputSubmitted } = renderAsk();
    const question = screen.getByLabelText('Your question');

    await user.click(question);
    await user.keyboard('{Enter}');

    expect(question).toHaveValue('');
    expect(screen.getByText('Choose text or one PDF')).toBeVisible();
    expect(onInputSubmitted).not.toHaveBeenCalled();
  });

  it('does not submit whitespace-only text', async () => {
    const user = userEvent.setup();
    const { onInputSubmitted } = renderAsk();

    await user.type(screen.getByLabelText('Your question'), '   {Enter}');

    expect(screen.getByText('Choose text or one PDF')).toBeVisible();
    expect(onInputSubmitted).not.toHaveBeenCalled();
  });

  it('submits a selected PDF with its original File object', async () => {
    const user = userEvent.setup();
    const submitted = vi.fn<(input: PublicQueryInput, entry: ChatEntry) => void>();
    renderAsk({ onInputSubmitted: submitted });

    const { file } = await selectPdf(user);
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(screen.getByRole('article', { name: 'Temporary PDF: notice.pdf' })).toBeVisible();
    expect(submitted).toHaveBeenCalledTimes(1);

    const submittedInput = submitted.mock.calls[0]?.[0];
    expect(submittedInput?.kind).toBe('file');
    if (submittedInput?.kind === 'file') {
      expect(submittedInput.file).toBe(file);
    }
  });

  it('disables both composer modes while a request is pending', () => {
    renderAsk({ isRequestPending: true });

    expect(screen.getByLabelText('Your question')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Add one PDF' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  it('disables an already-open PDF mode when a request becomes pending', async () => {
    const user = userEvent.setup();
    const submitted = vi.fn<(input: PublicQueryInput, entry: ChatEntry) => void>();
    const { rerender } = renderAsk({ onInputSubmitted: submitted });

    await selectPdf(user);
    rerender(<PublicAskWithSession isRequestPending onInputSubmitted={submitted} />);

    expect(screen.getByLabelText('Your question')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Add one PDF' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Browse files' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Remove notice.pdf' })).toBeDisabled();
  });

  it('consumes a landing handoff once and automatically submits it', async () => {
    const submitted = vi.fn();

    render(
      <PublicSessionProvider>
        <SessionSeed input={{ kind: 'text', content: 'I received a court notice' }} />
        <PublicAsk onInputSubmitted={submitted} />
      </PublicSessionProvider>,
    );

    expect(await screen.findByText('I received a court notice')).toBeVisible();
    expect(submitted).toHaveBeenCalledTimes(1);
    expect(fetchPublicQuery).toHaveBeenCalledTimes(1);
    expect(fetchPublicQuery).toHaveBeenCalledWith({
      kind: 'text',
      content: 'I received a court notice',
    });
  });

  it('consumes a file landing handoff once with the original File object', async () => {
    const file = new File(['pdf'], 'notice.pdf', { type: 'application/pdf' });
    const submitted = vi.fn<(input: PublicQueryInput, entry: ChatEntry) => void>();

    render(
      <PublicSessionProvider>
        <SessionSeed input={{ kind: 'file', file }} />
        <PublicAsk onInputSubmitted={submitted} />
      </PublicSessionProvider>,
    );

    expect(await screen.findByRole('article', { name: 'Temporary PDF: notice.pdf' })).toBeVisible();
    expect(submitted).toHaveBeenCalledTimes(1);
    expect(fetchPublicQuery).toHaveBeenCalledTimes(1);

    const submittedInput = submitted.mock.calls[0]?.[0];
    expect(submittedInput?.kind).toBe('file');
    if (submittedInput?.kind === 'file') {
      expect(submittedInput.file).toBe(file);
    }
  });

  it('clears immediately from zero messages without opening confirmation', async () => {
    const user = userEvent.setup();
    renderAsk();

    await user.click(screen.getByRole('button', { name: examples[0] }));
    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));

    expect(
      screen.queryByRole('region', { name: 'Confirm new conversation' }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('Your question')).toHaveValue('');
    expect(screen.getByLabelText('Your question')).toHaveFocus();
  });

  it('clears immediately from one message without opening confirmation', async () => {
    const user = userEvent.setup();
    renderAsk();

    await user.type(screen.getByLabelText('Your question'), 'First question{Enter}');
    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));

    expect(
      screen.queryByRole('region', { name: 'Confirm new conversation' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('First question')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Your question')).toHaveFocus();
  });

  it('asks for confirmation before clearing a conversation with multiple messages', async () => {
    const user = userEvent.setup();
    fetchPublicQuery.mockResolvedValueOnce(responseFixture);
    renderAsk();

    await user.type(screen.getByLabelText('Your question'), 'First question{Enter}');
    await screen.findByRole('article', { name: 'Plain-language legal information' });
    const newConversation = screen.getByRole('button', { name: 'Start New Conversation' });
    expect(newConversation).toHaveAttribute('aria-expanded', 'false');
    expect(newConversation).toHaveAttribute(
      'aria-controls',
      'public-ask-new-conversation-confirmation',
    );

    await user.click(newConversation);

    const confirmation = screen.getByRole('region', { name: 'Confirm new conversation' });
    expect(newConversation).toHaveAttribute('aria-expanded', 'true');
    expect(confirmation).toHaveAttribute('id', 'public-ask-new-conversation-confirmation');
    expect(newConversation).toHaveFocus();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByText('First question')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start New Conversation' })).toHaveFocus();

    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));
    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(screen.queryByText('First question')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Your question')).toHaveFocus();
  });

  it('does not let a late success repopulate a newly cleared conversation', async () => {
    const user = userEvent.setup();
    const request = createDeferred<PublicQueryResponse>();
    fetchPublicQuery.mockReturnValueOnce(request.promise);
    renderAsk();

    await submitText(user, 'Question from the old conversation');
    expect(fetchPublicQuery).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));
    expect(screen.queryByText('Question from the old conversation')).not.toBeInTheDocument();

    await act(async () => request.resolve(responseFixture));

    expect(
      screen.queryByRole('article', { name: 'Plain-language legal information' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('status', { name: 'Finding a clear answer' }),
    ).not.toBeInTheDocument();
  });

  it('does not let a late failure repopulate a newly cleared conversation', async () => {
    const user = userEvent.setup();
    const request = createDeferred<PublicQueryResponse>();
    fetchPublicQuery.mockReturnValueOnce(request.promise);
    renderAsk();

    await submitText(user, 'Another question from the old conversation');
    expect(fetchPublicQuery).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));

    await act(async () => request.reject(new Error('/private/late failure')));
    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
    expect(
      screen.queryByText('Another question from the old conversation'),
    ).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('/private/late failure');
  });
});
