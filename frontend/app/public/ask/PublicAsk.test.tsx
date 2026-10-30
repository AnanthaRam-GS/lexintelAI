import { useEffect } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClientError } from '../../../lib/api';
import { PublicSessionProvider, usePublicSession } from '../PublicSessionProvider';
import type { PublicQueryInput, PublicQueryResponse } from '../query-client';

import { PublicAsk, type PublicAskProps } from './PublicAsk';
import type { ChatEntry } from './chat-model';

const { fetchPublicQuery } = vi.hoisted(() => ({
  fetchPublicQuery:
    vi.fn<
      (input: PublicQueryInput, options?: { signal?: AbortSignal }) => Promise<PublicQueryResponse>
    >(),
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

function PublicAskWithReplayableSession({
  input,
  version,
}: {
  input: PublicQueryInput | null;
  version: number;
}) {
  return (
    <PublicSessionProvider>
      <PublicAsk />
      {input ? <SessionSeed input={input} key={version} /> : null}
    </PublicSessionProvider>
  );
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

const originalMatchMediaDescriptor = Object.getOwnPropertyDescriptor(window, 'matchMedia');
const originalScrollIntoViewDescriptor = Object.getOwnPropertyDescriptor(
  Element.prototype,
  'scrollIntoView',
);
const scrollIntoView = vi.fn<(options?: ScrollIntoViewOptions) => void>();
const scrolledElements: Element[] = [];

function installMatchMedia(prefersReducedMotion: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(
      (query: string) =>
        ({
          matches: prefersReducedMotion && query === '(prefers-reduced-motion: reduce)',
          media: query,
          onchange: null,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          addListener: vi.fn(),
          removeListener: vi.fn(),
          dispatchEvent: vi.fn(),
        }) satisfies MediaQueryList,
    ),
  });
}

describe('PublicAsk', () => {
  beforeEach(() => {
    fetchPublicQuery.mockReset();
    fetchPublicQuery.mockImplementation(neverSettles);
    scrollIntoView.mockReset();
    scrolledElements.length = 0;
    Object.defineProperty(Element.prototype, 'scrollIntoView', {
      configurable: true,
      value(this: Element, options?: ScrollIntoViewOptions) {
        scrolledElements.push(this);
        scrollIntoView(options);
      },
    });
    installMatchMedia(false);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();

    if (originalMatchMediaDescriptor) {
      Object.defineProperty(window, 'matchMedia', originalMatchMediaDescriptor);
    } else {
      Reflect.deleteProperty(window, 'matchMedia');
    }

    if (originalScrollIntoViewDescriptor) {
      Object.defineProperty(Element.prototype, 'scrollIntoView', originalScrollIntoViewDescriptor);
    } else {
      Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
    }
  });

  it('keeps the conversation name as the page heading', () => {
    renderAsk();

    expect(screen.getByRole('heading', { level: 1, name: 'Your conversation' })).toBeVisible();
  });

  it('separates the persistent header, scrollable conversation workspace, and composer', () => {
    renderAsk();

    const main = screen.getByRole('main');
    const header = main.querySelector(':scope > header');
    const workspace = screen.getByRole('region', { name: 'Conversation workspace' });
    const composer = screen.getByRole('region', { name: 'Ask another question' });

    expect(header).not.toBeNull();
    expect(Array.from(main.children)).toEqual([header, workspace, composer]);
    expect(workspace).toHaveAttribute('tabindex', '0');
    expect(workspace).toContainElement(
      screen.getByRole('region', { name: 'Ask a legal question in your own words.' }),
    );
  });

  it('keeps a completed exchange visible while the next answer loads and removes the spinner after settlement', async () => {
    const user = userEvent.setup();
    const nextResponse = createDeferred<PublicQueryResponse>();
    fetchPublicQuery
      .mockResolvedValueOnce(responseFixture)
      .mockReturnValueOnce(nextResponse.promise);
    renderAsk();

    await submitText(user, 'What does my first notice mean?');
    const completedResponse = await screen.findByRole('article', {
      name: 'Plain-language legal information',
    });
    await submitText(user, 'Can my employer keep my final pay?');

    expect(screen.getByText('What does my first notice mean?')).toBeVisible();
    expect(completedResponse).toBeVisible();
    expect(screen.getByText('Can my employer keep my final pay?')).toBeVisible();
    expect(screen.getByRole('status', { name: 'Finding a clear answer' })).toBeVisible();

    await act(async () => nextResponse.resolve(responseFixture));

    await waitFor(() => {
      expect(
        screen.queryByRole('status', { name: 'Finding a clear answer' }),
      ).not.toBeInTheDocument();
    });
  });

  it('scrolls the loading row and newly appended answer into view smoothly without stealing focus', async () => {
    const user = userEvent.setup();
    const request = createDeferred<PublicQueryResponse>();
    fetchPublicQuery.mockReturnValueOnce(request.promise);
    renderAsk();

    await submitText(user, 'Please explain this notice');

    const loading = screen.getByRole('status', { name: 'Finding a clear answer' });
    await waitFor(() => {
      expect(scrolledElements.at(-1)).toBe(loading.closest('li'));
      expect(scrollIntoView).toHaveBeenLastCalledWith({
        behavior: 'smooth',
        block: 'nearest',
      });
    });

    const newConversation = screen.getByRole('button', { name: 'Start New Conversation' });
    newConversation.focus();
    await act(async () => request.resolve(responseFixture));

    const answer = await screen.findByRole('article', {
      name: 'Plain-language legal information',
    });
    await waitFor(() => {
      expect(scrolledElements.at(-1)).toBe(answer.closest('li'));
    });
    expect(newConversation).toHaveFocus();
  });

  it('scrolls a newly appended error into view without stealing focus', async () => {
    const user = userEvent.setup();
    const request = createDeferred<PublicQueryResponse>();
    fetchPublicQuery.mockReturnValueOnce(request.promise);
    renderAsk();

    await submitText(user, 'Please explain this notice');
    const newConversation = screen.getByRole('button', { name: 'Start New Conversation' });
    newConversation.focus();
    await act(async () => request.reject(new Error('provider failed')));

    const error = await screen.findByRole('alert');
    await waitFor(() => {
      expect(scrolledElements.at(-1)).toBe(error.closest('li'));
      expect(scrollIntoView).toHaveBeenLastCalledWith({
        behavior: 'smooth',
        block: 'nearest',
      });
    });
    expect(newConversation).toHaveFocus();
  });

  it('uses instant latest-row scrolling when reduced motion is preferred', async () => {
    const user = userEvent.setup();
    installMatchMedia(true);
    renderAsk();

    await submitText(user, 'Please explain this notice');

    const loading = screen.getByRole('status', { name: 'Finding a clear answer' });
    await waitFor(() => {
      expect(scrolledElements.at(-1)).toBe(loading.closest('li'));
      expect(scrollIntoView).toHaveBeenLastCalledWith({
        behavior: 'auto',
        block: 'nearest',
      });
    });
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
    await user.type(screen.getByLabelText('Your question'), 'What does this notice ask me to do?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(fetchPublicQuery).toHaveBeenCalledTimes(1);
    const submittedInput = fetchPublicQuery.mock.calls[0]?.[0];
    expect(submittedInput?.kind).toBe('file');
    if (submittedInput?.kind === 'file') {
      expect(submittedInput.file).toBe(file);
      expect(submittedInput.question).toBe('What does this notice ask me to do?');
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
    expect(error).toHaveTextContent("Couldn't get an answer right now");
    expect(error).toHaveTextContent('Your question is still here. Please try again in a moment.');
    expect(document.body).not.toHaveTextContent(privateFailure);
    expect(
      Array.from(document.querySelectorAll('*')).some((element) =>
        Array.from(element.attributes).some((attribute) =>
          attribute.value.includes(privateFailure),
        ),
      ),
    ).toBe(false);
  });

  it('distinguishes a network failure with fixed connection guidance', async () => {
    const user = userEvent.setup();
    fetchPublicQuery.mockRejectedValueOnce(
      new TypeError('Failed to fetch https://private-host/query'),
    );
    renderAsk();

    await submitText(user, 'What can I do?');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Check your connection');
    expect(alert).toHaveTextContent('Reconnect, then try your question again.');
    expect(alert).not.toHaveTextContent('private-host');
  });

  it('says when daily capacity returns for DAILY_CAPACITY_REACHED (step 24b)', async () => {
    const user = userEvent.setup();
    fetchPublicQuery.mockRejectedValueOnce(
      new ApiClientError(
        "Today's answer capacity has been reached.",
        503,
        'DAILY_CAPACITY_REACHED',
        3600,
      ),
    );
    renderAsk();

    await submitText(user, 'What can I do?');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent("Today's AI capacity has been reached");
    expect(alert).toHaveTextContent(/please try again after .+\. Your question is still here\./);
    expect(alert).not.toHaveTextContent('Many people are asking');
  });

  it('maps a 429 provider quota failure to a usage-limit-safe message', async () => {
    const user = userEvent.setup();
    fetchPublicQuery.mockRejectedValueOnce(
      new ApiClientError(
        'Gemini request failed with HTTP 429: quota exceeded for project abc123',
        429,
        'MODEL_PROVIDER_QUOTA_EXCEEDED',
      ),
    );
    renderAsk();

    await submitText(user, 'What can I do?');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Usage limit reached');
    expect(alert).toHaveTextContent(
      'AI answer service has reached its temporary usage limit. Please try again later.',
    );
    expect(alert).not.toHaveTextContent('abc123');
    expect(alert).not.toHaveTextContent('Gemini');
  });

  it('maps a 503 provider-unavailable failure to the answer-service-unavailable message', async () => {
    const user = userEvent.setup();
    fetchPublicQuery.mockRejectedValueOnce(
      new ApiClientError(
        'The legal answer provider is temporarily unavailable.',
        503,
        'MODEL_PROVIDER_ERROR',
      ),
    );
    renderAsk();

    await submitText(user, 'What can I do?');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Answer service unavailable');
    expect(alert).toHaveTextContent(
      'The legal answer model is temporarily unavailable. Try again later.',
    );
  });

  it('changes from fast to slow and then offers keep-waiting or cancel controls', async () => {
    vi.useFakeTimers();
    const request = createDeferred<PublicQueryResponse>();
    fetchPublicQuery.mockReturnValueOnce(request.promise);
    renderAsk();

    fireEvent.change(screen.getByLabelText('Your question'), {
      target: { value: 'Please explain this notice' },
    });
    fireEvent.submit(screen.getByRole('button', { name: 'Send' }).closest('form')!);

    const requestSignal = fetchPublicQuery.mock.calls[0]?.[1]?.signal;
    expect(requestSignal).toBeInstanceOf(AbortSignal);
    expect(requestSignal?.aborted).toBe(false);

    expect(screen.getByRole('status', { name: 'Finding a clear answer' })).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(4_999));
    expect(screen.getByRole('status', { name: 'Finding a clear answer' })).toBeInTheDocument();
    expect(screen.queryByText(/High demand/)).not.toBeInTheDocument();
    // Step 23: past 5 s the answer is shown as queued.
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(
      screen.getByRole('status', { name: 'Still working on your answer' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText('High demand — your answer is queued and will appear shortly.'),
    ).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(24_999));
    expect(
      screen.queryByRole('heading', { name: 'Taking longer than expected' }),
    ).not.toBeInTheDocument();

    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(
      screen.getByRole('heading', { name: 'Taking longer than expected' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep waiting' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel request' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Keep waiting' }));
    expect(screen.getByText(/Still working\. You can cancel at any time/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Keep waiting' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel request' }));
    expect(requestSignal?.aborted).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('We stopped waiting');
    expect(screen.getByText('Please explain this notice')).toBeInTheDocument();

    await act(async () => request.resolve(responseFixture));
    expect(screen.queryByText(responseFixture.explanation)).not.toBeInTheDocument();
  });

  it('keeps an older failed turn visible when a later turn recovers', async () => {
    const user = userEvent.setup();
    fetchPublicQuery
      .mockRejectedValueOnce(new Error('provider failed'))
      .mockResolvedValueOnce(responseFixture);
    renderAsk();

    await submitText(user, 'First question');
    const oldFailure = await screen.findByRole('alert');
    await submitText(user, 'Second question');
    await screen.findByRole('article', { name: 'Plain-language legal information' });

    expect(oldFailure).toBeInTheDocument();
    expect(screen.getByText('First question')).toBeInTheDocument();
    expect(screen.getByText('Second question')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
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

    expect(fetchPublicQuery).toHaveBeenNthCalledWith(
      2,
      {
        kind: 'text',
        content: 'What can I do?',
      },
      { signal: expect.any(AbortSignal) },
    );
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
    await user.type(screen.getByLabelText('Your question'), 'What does this notice ask me to do?');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    const retriedInput = fetchPublicQuery.mock.calls[1]?.[0];
    expect(retriedInput?.kind).toBe('file');
    if (retriedInput?.kind === 'file') {
      expect(retriedInput.file).toBe(file);
      expect(retriedInput.question).toBe('What does this notice ask me to do?');
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

  it('contains an unbroken submitted question inside the conversation grid below desktop', () => {
    renderAsk();
    const question = 'A'.repeat(320);

    fireEvent.change(screen.getByLabelText('Your question'), { target: { value: question } });
    fireEvent.submit(screen.getByRole('button', { name: 'Send' }).closest('form')!);

    const message = screen.getByRole('article', { name: 'Your submitted question' });
    expect(message.parentElement).toHaveClass('min-w-0', 'w-full');
    expect(message).toHaveClass('[overflow-wrap:anywhere]');
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
    expect(screen.getByText('Ready to send: Written question')).toBeVisible();
    expect(onInputSubmitted).not.toHaveBeenCalled();
  });

  it('keeps a typed question attached to a PDF added afterward', async () => {
    const user = userEvent.setup();
    renderAsk();

    await user.type(screen.getByLabelText('Your question'), 'Help me understand this');
    expect(screen.getByText('Ready to send: Written question')).toBeVisible();

    await selectPdf(user);

    expect(screen.getByLabelText('Your question')).toHaveValue('Help me understand this');
    expect(screen.getByText('notice.pdf')).toBeVisible();
    expect(screen.getByText('Ready to send: PDF (not stored) + Written question')).toBeVisible();
  });

  it('keeps the selected PDF attached while a person types the required question', async () => {
    const user = userEvent.setup();
    renderAsk();

    const { input: firstUploadInput } = await selectPdf(user);
    expect(screen.getByText('Add a question about this PDF to send')).toBeVisible();

    await user.type(screen.getByLabelText('Your question'), 'Explain this notice');

    expect(screen.getByLabelText('Choose PDF files')).toBe(firstUploadInput);
    expect(screen.getByText('notice.pdf')).toBeVisible();
    expect(screen.getByText('Ready to send: PDF (not stored) + Written question')).toBeVisible();
    expect(screen.queryByText('Enter a question about this PDF.')).not.toBeInTheDocument();
  });

  it('lets a person remove an attached PDF without submitting or losing the typed question', async () => {
    const user = userEvent.setup();
    const submitted = vi.fn<(input: PublicQueryInput, entry: ChatEntry) => void>();
    renderAsk({ onInputSubmitted: submitted });

    await selectPdf(user);
    await user.type(screen.getByLabelText('Your question'), 'Explain this notice');

    await user.click(screen.getByRole('button', { name: 'Remove notice.pdf' }));

    expect(screen.queryByText('notice.pdf')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Your question')).toHaveValue('Explain this notice');
    expect(screen.getByText('Ready to send: Written question')).toBeVisible();
    expect(fetchPublicQuery).not.toHaveBeenCalled();
    expect(submitted).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(submitted).toHaveBeenCalledTimes(1);
    const submittedInput = submitted.mock.calls[0]?.[0];
    expect(submittedInput).toEqual({ kind: 'text', content: 'Explain this notice' });
  });

  it('switches a selected PDF to text when an empty-state example is chosen', async () => {
    const user = userEvent.setup();
    renderAsk();

    await selectPdf(user);
    await user.click(screen.getByRole('button', { name: examples[1] }));

    expect(screen.getByLabelText('Your question')).toHaveValue(examples[1]);
    expect(screen.getByText('Ready to send: Written question')).toBeVisible();
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
    expect(screen.getByText('Add a question about this PDF to send')).toBeVisible();
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
    expect(screen.getByText('Type a question or add one PDF')).toBeVisible();
    expect(onInputSubmitted).not.toHaveBeenCalled();
  });

  it('does not submit whitespace-only text', async () => {
    const user = userEvent.setup();
    const { onInputSubmitted } = renderAsk();

    await user.type(screen.getByLabelText('Your question'), '   {Enter}');

    expect(screen.getByText('Type a question or add one PDF')).toBeVisible();
    expect(onInputSubmitted).not.toHaveBeenCalled();
  });

  it('submits a selected PDF with its original File object', async () => {
    const user = userEvent.setup();
    const submitted = vi.fn<(input: PublicQueryInput, entry: ChatEntry) => void>();
    renderAsk({ onInputSubmitted: submitted });

    const { file } = await selectPdf(user);
    await user.type(screen.getByLabelText('Your question'), 'What does this notice ask me to do?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(screen.getByRole('article', { name: 'Temporary PDF: notice.pdf' })).toBeVisible();
    expect(submitted).toHaveBeenCalledTimes(1);

    const submittedInput = submitted.mock.calls[0]?.[0];
    expect(submittedInput?.kind).toBe('file');
    if (submittedInput?.kind === 'file') {
      expect(submittedInput.file).toBe(file);
      expect(submittedInput.question).toBe('What does this notice ask me to do?');
    }
  });

  it('does not submit a selected PDF without a question', async () => {
    const user = userEvent.setup();
    const submitted = vi.fn<(input: PublicQueryInput, entry: ChatEntry) => void>();
    renderAsk({ onInputSubmitted: submitted });

    await selectPdf(user);

    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(screen.getByText('Enter a question about this PDF.')).toBeVisible();
    expect(fetchPublicQuery).not.toHaveBeenCalled();
    expect(submitted).not.toHaveBeenCalled();
  });

  it('contains a submitted PDF with a long filename inside the conversation grid', async () => {
    const user = userEvent.setup();
    const fileName = `${'a'.repeat(200)}.pdf`;
    renderAsk();

    await selectPdf(user, fileName);
    await user.type(screen.getByLabelText('Your question'), 'Explain this document');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    const message = screen.getByRole('article', { name: `Temporary PDF: ${fileName}` });
    expect(message.parentElement).toHaveClass('flex', 'min-w-0', 'w-full', 'justify-end');
    expect(message).toHaveClass('min-w-0');
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
    expect(fetchPublicQuery).toHaveBeenCalledWith(
      {
        kind: 'text',
        content: 'I received a court notice',
      },
      { signal: expect.any(AbortSignal) },
    );
  });

  it('consumes a file landing handoff once with the original File object', async () => {
    const file = new File(['pdf'], 'notice.pdf', { type: 'application/pdf' });
    const submitted = vi.fn<(input: PublicQueryInput, entry: ChatEntry) => void>();

    render(
      <PublicSessionProvider>
        <SessionSeed
          input={{ kind: 'file', file, question: 'What does this notice ask me to do?' }}
        />
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
      expect(submittedInput.question).toBe('What does this notice ask me to do?');
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

  it('opens a labelled confirmation at exactly two thread entries', async () => {
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
    expect(screen.getByRole('button', { name: 'Keep conversation' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start fresh' })).toBeVisible();
  });

  it('scrolls the new-conversation confirmation into the conversation workspace', async () => {
    const user = userEvent.setup();
    fetchPublicQuery.mockResolvedValueOnce(responseFixture);
    renderAsk();

    await submitText(user, 'First question');
    await screen.findByRole('article', { name: 'Plain-language legal information' });
    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));

    const confirmation = screen.getByRole('region', { name: 'Confirm new conversation' });
    expect(scrolledElements.at(-1)).toBe(confirmation);
    expect(scrollIntoView).toHaveBeenLastCalledWith({
      block: 'nearest',
      behavior: 'smooth',
    });
  });

  it('keeps the full thread after cancellation and restores focus to the trigger', async () => {
    const user = userEvent.setup();
    fetchPublicQuery.mockResolvedValueOnce(responseFixture);
    renderAsk();

    await submitText(user, 'First question');
    const response = await screen.findByRole('article', {
      name: 'Plain-language legal information',
    });
    const conversation = screen.getByRole('list', { name: 'Conversation' });
    expect(conversation.children).toHaveLength(2);

    const newConversation = screen.getByRole('button', { name: 'Start New Conversation' });
    await user.click(newConversation);
    await user.click(screen.getByRole('button', { name: 'Keep conversation' }));

    expect(screen.getByText('First question')).toBeVisible();
    expect(response).toBeVisible();
    expect(conversation.children).toHaveLength(2);
    expect(
      screen.queryByRole('region', { name: 'Confirm new conversation' }),
    ).not.toBeInTheDocument();
    expect(newConversation).toHaveFocus();
  });

  it('clears the full thread, error, armed PDF, and request UI after confirmation', async () => {
    const user = userEvent.setup();
    const onNewConversation = vi.fn();
    fetchPublicQuery.mockRejectedValueOnce(new Error('provider failed'));
    renderAsk({ onNewConversation });

    await submitText(user, 'First question');
    expect(await screen.findByRole('alert')).toBeVisible();
    await selectPdf(user);
    expect(screen.getByText('Add a question about this PDF to send')).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));
    await user.click(screen.getByRole('button', { name: 'Start fresh' }));

    expect(screen.queryByRole('list', { name: 'Conversation' })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.queryByText('notice.pdf')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Choose PDF files')).not.toBeInTheDocument();
    expect(screen.getByText('Type a question or add one PDF')).toBeVisible();
    expect(screen.getByLabelText('Your question')).toHaveValue('');
    expect(screen.getByLabelText('Your question')).toHaveFocus();
    expect(onNewConversation).toHaveBeenCalledTimes(1);
  });

  it('keeps a replayed-input request active when an obsolete success settles after confirmed clear', async () => {
    const user = userEvent.setup();
    const obsoleteRequest = createDeferred<PublicQueryResponse>();
    const currentRequest = createDeferred<PublicQueryResponse>();
    fetchPublicQuery
      .mockResolvedValueOnce(responseFixture)
      .mockReturnValueOnce(obsoleteRequest.promise)
      .mockReturnValueOnce(currentRequest.promise);
    const view = render(<PublicAskWithReplayableSession input={null} version={0} />);

    await submitText(user, 'Completed question');
    await screen.findByRole('article', { name: 'Plain-language legal information' });
    await submitText(user, 'Question that will be replayed');
    const replayedInput = fetchPublicQuery.mock.calls[1]?.[0];
    expect(replayedInput).toBeDefined();

    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));
    await user.click(screen.getByRole('button', { name: 'Start fresh' }));
    view.rerender(<PublicAskWithReplayableSession input={replayedInput ?? null} version={1} />);
    await waitFor(() => expect(fetchPublicQuery).toHaveBeenCalledTimes(3));

    await act(async () =>
      obsoleteRequest.resolve({ ...responseFixture, explanation: 'Obsolete answer' }),
    );

    expect(screen.queryByText('Obsolete answer')).not.toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Finding a clear answer' })).toBeVisible();

    await act(async () =>
      currentRequest.resolve({ ...responseFixture, explanation: 'Current answer' }),
    );
    expect(await screen.findByText('Current answer')).toBeVisible();
  });

  it('does not let a late success repopulate a confirmed-cleared conversation', async () => {
    const user = userEvent.setup();
    const request = createDeferred<PublicQueryResponse>();
    fetchPublicQuery.mockResolvedValueOnce(responseFixture).mockReturnValueOnce(request.promise);
    renderAsk();

    await submitText(user, 'Completed question');
    await screen.findByRole('article', { name: 'Plain-language legal information' });
    await submitText(user, 'Question from the old conversation');
    expect(fetchPublicQuery).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));
    await user.click(screen.getByRole('button', { name: 'Start fresh' }));
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

  it('does not let a late failure repopulate a confirmed-cleared conversation', async () => {
    const user = userEvent.setup();
    const request = createDeferred<PublicQueryResponse>();
    fetchPublicQuery.mockResolvedValueOnce(responseFixture).mockReturnValueOnce(request.promise);
    renderAsk();

    await submitText(user, 'Completed question');
    await screen.findByRole('article', { name: 'Plain-language legal information' });
    await submitText(user, 'Another question from the old conversation');
    expect(fetchPublicQuery).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: 'Start New Conversation' }));
    await user.click(screen.getByRole('button', { name: 'Start fresh' }));

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
