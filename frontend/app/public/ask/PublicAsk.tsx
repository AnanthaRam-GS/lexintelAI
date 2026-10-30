'use client';

import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  type Ref,
} from 'react';

import { ErrorMessage } from '../../../components/shared/ErrorMessage';
import { ApiClientError, dailyCapacityMessage } from '../../../lib/api';
import { LoadingSpinner } from '../../../components/shared/LoadingSpinner';
import { QUEUED_NOTICE_DELAY_MS } from '../../../components/shared/QueuedNotice';
import { ResponseCard } from '../../../components/shared/ResponseCard';
import { UploadDropzone } from '../../../components/shared/UploadDropzone';

import { usePublicSession } from '../PublicSessionProvider';
import { classifyPublicAnswerFailure, errorCopy, type PublicAnswerFailure } from '../error-copy';
import { fetchPublicQuery, type PublicQueryInput } from '../query-client';
import { toPublicResponseCardProps } from '../response-adapter';

import { chatReducer, initialChatState, type ChatEntry, type ChatMessage } from './chat-model';

const emptyStateExamples = [
  'My landlord has not returned my deposit. What can I do?',
  'Can my employer withhold my final salary?',
  'What should I do after receiving a court notice?',
];

const controlFocusClass =
  'focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem]';
// Step 23: from 5 s the answer is shown as queued (the backend paces requests to the model's rate limit and may
// queue one for up to ~90 s); the keep-waiting / cancel card follows at 30 s.
const PUBLIC_SLOW_CUE_DELAY_MS = QUEUED_NOTICE_DELAY_MS;
const PUBLIC_TIMEOUT_CUE_DELAY_MS = 30_000;

type ActiveInputMode = 'text' | 'file' | 'none';
type RequestStatus = 'idle' | 'loading' | 'error';
type LoadingStage = 'fast' | 'slow' | 'timeout';

export interface PublicAskProps {
  /**
   * Optional observers and pending-state control retained from the reviewed
   * composer seam. PublicAsk owns the production request lifecycle.
   */
  isRequestPending?: boolean;
  onInputSubmitted?: (input: PublicQueryInput, entry: ChatEntry) => void;
  onNewConversation?: () => void;
  onRetry?: (entry: ChatEntry) => void;
}

function activeInputLabel(activeMode: ActiveInputMode, fileNeedsQuestion: boolean): string {
  switch (activeMode) {
    case 'text':
      return 'Ready to send: Written question';
    case 'file':
      return fileNeedsQuestion
        ? 'Add a question about this PDF to send'
        : 'Ready to send: PDF (not stored) + Written question';
    case 'none':
      return 'Type a question or add one PDF';
  }
}

function ChatThreadEntry({
  entry,
  entryRef,
  onRetry,
  retryAvailable,
}: {
  entry: ChatEntry;
  entryRef?: Ref<HTMLLIElement>;
  retryAvailable: boolean;
  onRetry: (entry: ChatEntry) => void;
}) {
  const { message } = entry;

  if (message.role === 'user' && message.kind === 'text') {
    return (
      <li className="flex min-w-0 w-full justify-end" ref={entryRef}>
        <article
          aria-label="Your submitted question"
          className="max-w-[78%] rounded-[var(--radius-standard)] rounded-br-[var(--radius-compact)] bg-[var(--color-ink)] px-4 py-3 text-type-body text-[var(--color-inverse)] [overflow-wrap:anywhere]"
        >
          {message.content}
        </article>
      </li>
    );
  }

  if (message.role === 'user' && message.kind === 'file') {
    return (
      <li className="flex min-w-0 w-full justify-end" ref={entryRef}>
        <article
          aria-label={`Temporary PDF: ${message.fileName}`}
          className="min-w-0 max-w-[78%] rounded-[var(--radius-standard)] border border-[var(--color-info-border)] bg-[var(--color-info-surface)] px-4 py-3 text-type-body text-[var(--color-info-foreground)]"
        >
          <p className="truncate font-semibold">{message.fileName}</p>
          <p className="text-type-body-sm mt-1">Checked temporarily for this question</p>
        </article>
      </li>
    );
  }

  if (message.role === 'assistant' && 'response' in message) {
    return (
      <li ref={entryRef}>
        <ResponseCard {...toPublicResponseCardProps(message.response)} />
      </li>
    );
  }

  const failure = errorCopy.public.answer[message.failure];
  const failureMessage =
    message.failure === 'daily-capacity' && message.retryAfterSeconds
      ? `${dailyCapacityMessage(message.retryAfterSeconds)} Your question is still here.`
      : failure.message;

  return (
    <li ref={entryRef}>
      <ErrorMessage
        message={failureMessage}
        onRetry={retryAvailable ? () => onRetry(entry) : undefined}
        title={failure.title}
        variant="inline"
      />
    </li>
  );
}

export function PublicAsk({
  isRequestPending = false,
  onInputSubmitted,
  onNewConversation,
  onRetry,
}: PublicAskProps) {
  const { pendingInput, takePendingInput } = usePublicSession();
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [draft, setDraft] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploadVisible, setIsUploadVisible] = useState(false);
  const [uploadKey, setUploadKey] = useState(0);
  const [isConfirmingNewConversation, setIsConfirmingNewConversation] = useState(false);
  const [requestStatus, setRequestStatus] = useState<RequestStatus>('idle');
  const [loadingStage, setLoadingStage] = useState<LoadingStage>('fast');
  const [continuedWaiting, setContinuedWaiting] = useState(false);
  const entrySequence = useRef(0);
  const confirmationRef = useRef<HTMLElement>(null);
  const failedInputsRef = useRef(new Map<string, PublicQueryInput>());
  const isMountedRef = useRef(true);
  const isRequestInFlightRef = useRef(false);
  const latestEntryRef = useRef<HTMLLIElement>(null);
  const textInputRef = useRef<HTMLTextAreaElement>(null);
  const newConversationButtonRef = useRef<HTMLButtonElement>(null);
  const requestGenerationRef = useRef(0);
  const requestAbortControllerRef = useRef<AbortController | null>(null);
  const requestRef = useRef<PublicQueryInput | null>(null);
  const slowCueTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const timeoutCueTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activeMode: ActiveInputMode = selectedFile ? 'file' : draft.trim() ? 'text' : 'none';
  const fileNeedsQuestion = Boolean(selectedFile) && !draft.trim();
  const isAnyRequestPending = isRequestPending || requestStatus === 'loading';

  const clearRequestTimers = useCallback(() => {
    if (slowCueTimerRef.current) clearTimeout(slowCueTimerRef.current);
    if (timeoutCueTimerRef.current) clearTimeout(timeoutCueTimerRef.current);
    slowCueTimerRef.current = null;
    timeoutCueTimerRef.current = null;
  }, []);

  useEffect(() => {
    isMountedRef.current = true;

    return () => {
      isMountedRef.current = false;
      requestAbortControllerRef.current?.abort();
      requestAbortControllerRef.current = null;
      clearRequestTimers();
    };
  }, [clearRequestTimers]);

  useEffect(() => {
    const latestEntry = latestEntryRef.current;

    if (!latestEntry) {
      return;
    }

    const prefersReducedMotion =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    latestEntry.scrollIntoView({
      block: 'nearest',
      behavior: prefersReducedMotion ? 'auto' : 'smooth',
    });
  }, [state.entries.length, requestStatus]);

  useEffect(() => {
    const confirmation = confirmationRef.current;

    if (!isConfirmingNewConversation || !confirmation) {
      return;
    }

    const prefersReducedMotion =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    confirmation.scrollIntoView({
      block: 'nearest',
      behavior: prefersReducedMotion ? 'auto' : 'smooth',
    });
  }, [isConfirmingNewConversation]);

  const appendInput = useCallback(
    (input: PublicQueryInput) => {
      entrySequence.current += 1;
      const message: Extract<ChatMessage, { role: 'user' }> =
        input.kind === 'text'
          ? { role: 'user', kind: 'text', content: input.content }
          : { role: 'user', kind: 'file', fileName: input.file.name };
      const entry: ChatEntry & { message: Extract<ChatMessage, { role: 'user' }> } = {
        id: `public-turn-${entrySequence.current}-user`,
        message,
      };

      dispatch({ type: 'append-user', entry });
      onInputSubmitted?.(input, entry);

      return entry;
    },
    [onInputSubmitted],
  );

  const submitInput = useCallback(
    (input: PublicQueryInput, appendUser = true): boolean => {
      if (isRequestPending || isRequestInFlightRef.current) {
        return false;
      }

      const requestGeneration = requestGenerationRef.current;
      const requestAbortController = new AbortController();
      requestAbortControllerRef.current = requestAbortController;
      requestRef.current = input;
      isRequestInFlightRef.current = true;
      setRequestStatus('loading');
      setLoadingStage('fast');
      setContinuedWaiting(false);
      clearRequestTimers();

      const requestIsCurrent = () =>
        isMountedRef.current &&
        requestGeneration === requestGenerationRef.current &&
        requestRef.current === input &&
        isRequestInFlightRef.current;

      slowCueTimerRef.current = setTimeout(() => {
        if (requestIsCurrent()) setLoadingStage('slow');
      }, PUBLIC_SLOW_CUE_DELAY_MS);
      timeoutCueTimerRef.current = setTimeout(() => {
        if (requestIsCurrent()) setLoadingStage('timeout');
      }, PUBLIC_TIMEOUT_CUE_DELAY_MS);

      if (appendUser) {
        appendInput(input);
      }

      void (async () => {
        try {
          const response = await fetchPublicQuery(input, {
            signal: requestAbortController.signal,
          });

          if (
            !isMountedRef.current ||
            requestGeneration !== requestGenerationRef.current ||
            requestRef.current !== input ||
            !isRequestInFlightRef.current
          ) {
            return;
          }

          entrySequence.current += 1;
          const entry: ChatEntry & {
            message: Extract<ChatMessage, { role: 'assistant' }>;
          } = {
            id: `public-turn-${entrySequence.current}-assistant`,
            message: { role: 'assistant', response },
          };

          dispatch({ type: 'append-assistant', entry });
          clearRequestTimers();
          requestAbortControllerRef.current = null;
          requestRef.current = null;
          isRequestInFlightRef.current = false;
          setRequestStatus('idle');
        } catch (error) {
          if (
            !isMountedRef.current ||
            requestGeneration !== requestGenerationRef.current ||
            requestRef.current !== input ||
            !isRequestInFlightRef.current
          ) {
            return;
          }

          entrySequence.current += 1;
          const entry: ChatEntry & {
            message: Extract<ChatMessage, { role: 'assistant' }>;
          } = {
            id: `public-turn-${entrySequence.current}-assistant`,
            message: {
              role: 'assistant',
              kind: 'error',
              failure: classifyPublicAnswerFailure(error),
              retryAfterSeconds:
                error instanceof ApiClientError ? error.retryAfterSeconds : undefined,
            },
          };

          dispatch({ type: 'append-assistant', entry });
          failedInputsRef.current.set(entry.id, input);
          clearRequestTimers();
          requestAbortControllerRef.current = null;
          requestRef.current = null;
          isRequestInFlightRef.current = false;
          setRequestStatus('error');
        }
      })();

      return true;
    },
    [appendInput, clearRequestTimers, isRequestPending],
  );

  useEffect(() => {
    if (!pendingInput || isAnyRequestPending) {
      return;
    }

    const input = takePendingInput();
    if (input) {
      submitInput(input);
    }
  }, [isAnyRequestPending, pendingInput, submitInput, takePendingInput]);

  const resetComposer = useCallback(() => {
    setDraft('');
    setSelectedFile(null);
    setIsUploadVisible(false);
    setUploadKey((key) => key + 1);
  }, []);

  const submitCurrentInput = useCallback(() => {
    if (isAnyRequestPending) {
      return;
    }

    const content = draft.trim();
    if (!content) {
      return;
    }

    if (selectedFile) {
      if (submitInput({ kind: 'file', file: selectedFile, question: content })) {
        resetComposer();
      }
      return;
    }

    if (submitInput({ kind: 'text', content })) {
      resetComposer();
    }
  }, [draft, isAnyRequestPending, resetComposer, selectedFile, submitInput]);

  const handleComposerSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submitCurrentInput();
  };

  const armTextInput = (value: string) => {
    setDraft(value);

    if (selectedFile) {
      setSelectedFile(null);
      setUploadKey((key) => key + 1);
    }
  };

  const handleQuestionChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    if (isAnyRequestPending) {
      return;
    }

    setDraft(event.target.value);
  };

  const handleQuestionKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) {
      return;
    }

    event.preventDefault();

    if (!isAnyRequestPending && draft.trim()) {
      submitCurrentInput();
    }
  };

  const handleFilesSelected = (files: File[]) => {
    if (isAnyRequestPending) {
      return;
    }

    const [file] = files;
    setSelectedFile(file ?? null);
  };

  const clearConversation = useCallback(() => {
    requestGenerationRef.current += 1;
    requestAbortControllerRef.current?.abort();
    requestAbortControllerRef.current = null;
    clearRequestTimers();
    requestRef.current = null;
    failedInputsRef.current.clear();
    isRequestInFlightRef.current = false;
    setRequestStatus('idle');
    dispatch({ type: 'clear' });
    resetComposer();
    setIsConfirmingNewConversation(false);
    onNewConversation?.();
    queueMicrotask(() => textInputRef.current?.focus());
  }, [clearRequestTimers, onNewConversation, resetComposer]);

  const requestNewConversation = () => {
    if (state.entries.length >= 2) {
      setIsConfirmingNewConversation(true);
      return;
    }

    clearConversation();
  };

  const cancelNewConversation = () => {
    setIsConfirmingNewConversation(false);
    newConversationButtonRef.current?.focus();
  };

  const retryEntry = useCallback(
    (entry: ChatEntry) => {
      const retainedInput = failedInputsRef.current.get(entry.id);

      if (isAnyRequestPending || !retainedInput) {
        return;
      }

      if (!submitInput(retainedInput, false)) {
        return;
      }

      dispatch({ type: 'remove-error', id: entry.id });
      failedInputsRef.current.delete(entry.id);
      onRetry?.(entry);
    },
    [isAnyRequestPending, onRetry, submitInput],
  );

  const cancelSlowRequest = useCallback(() => {
    const retainedInput = requestRef.current;
    if (!retainedInput || !isRequestInFlightRef.current) return;

    requestGenerationRef.current += 1;
    requestAbortControllerRef.current?.abort();
    requestAbortControllerRef.current = null;
    clearRequestTimers();
    requestRef.current = null;
    isRequestInFlightRef.current = false;
    entrySequence.current += 1;
    const entry: ChatEntry & {
      message: { role: 'assistant'; kind: 'error'; failure: PublicAnswerFailure };
    } = {
      id: `public-turn-${entrySequence.current}-assistant`,
      message: { role: 'assistant', kind: 'error', failure: 'cancelled' },
    };
    failedInputsRef.current.set(entry.id, retainedInput);
    dispatch({ type: 'append-assistant', entry });
    setRequestStatus('error');
    setLoadingStage('fast');
    setContinuedWaiting(false);
  }, [clearRequestTimers]);

  return (
    <main className="mx-auto min-h-screen max-w-5xl px-5 py-6 sm:px-8 sm:py-10 lg:grid lg:h-dvh lg:min-h-0 lg:grid-rows-[auto_minmax(0,1fr)_auto] lg:overflow-hidden">
      <header className="mx-auto flex w-full max-w-4xl flex-col gap-4 border-b border-[var(--color-border)] pb-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-display text-type-heading-md font-bold text-[var(--color-ink)]">
            Your conversation
          </h1>
          <p className="text-type-body-sm mt-1 text-[var(--color-muted)]">
            Available only during this visit
          </p>
        </div>
        <button
          aria-controls="public-ask-new-conversation-confirmation"
          aria-expanded={isConfirmingNewConversation}
          className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-brass)] bg-[var(--color-surface-raised)] px-4 font-semibold text-[var(--color-brass-active)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)] ${controlFocusClass}`}
          onClick={requestNewConversation}
          ref={newConversationButtonRef}
          type="button"
        >
          Start New Conversation
        </button>
      </header>

      <section
        aria-label="Conversation workspace"
        className={`lg:min-h-0 lg:overflow-y-auto lg:overscroll-contain lg:scroll-py-6 ${controlFocusClass}`}
        tabIndex={0}
      >
        {isConfirmingNewConversation ? (
          <section
            aria-label="Confirm new conversation"
            className="mx-auto mt-5 max-w-4xl rounded-[var(--radius-standard)] border border-[var(--color-warning-border)] bg-[var(--color-warning-surface)] p-4"
            id="public-ask-new-conversation-confirmation"
            ref={confirmationRef}
          >
            <h2 className="font-display text-type-heading-sm font-semibold text-[var(--color-ink)]">
              Start a new conversation?
            </h2>
            <p className="text-type-body-sm-relaxed mt-2 text-[var(--color-warning-foreground)]">
              This clears the questions in this visit so you can begin again.
            </p>
            <div className="mt-4 flex flex-col gap-3 sm:flex-row">
              <button
                className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 font-semibold text-[var(--color-inverse)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-brass-hover)] ${controlFocusClass}`}
                onClick={clearConversation}
                type="button"
              >
                Start fresh
              </button>
              <button
                className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-4 font-semibold text-[var(--color-body)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)] ${controlFocusClass}`}
                onClick={cancelNewConversation}
                type="button"
              >
                Keep conversation
              </button>
            </div>
          </section>
        ) : null}

        {state.entries.length === 0 ? (
          <section
            aria-labelledby="public-ask-empty-title"
            className="mx-auto mt-10 max-w-3xl rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[var(--shadow-component)] sm:p-8"
          >
            <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass)]">
              Start here
            </p>
            <h2
              className="font-display text-type-heading-xl mt-2 font-semibold text-[var(--color-ink)]"
              id="public-ask-empty-title"
            >
              Ask a legal question in your own words.
            </h2>
            <p className="text-type-body-relaxed mt-3 text-[var(--color-muted)]">
              You can also share one PDF for a temporary, plain-language explanation.
            </p>
            <ul className="mt-6 grid gap-3">
              {emptyStateExamples.map((example) => (
                <li key={example}>
                  <button
                    className={`text-type-body min-h-11 w-full rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-4 py-3 text-left font-medium text-[var(--color-ink)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)] ${controlFocusClass}`}
                    disabled={isAnyRequestPending}
                    onClick={() => armTextInput(example)}
                    type="button"
                  >
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {state.entries.length > 0 || requestStatus === 'loading' ? (
          <ol aria-label="Conversation" className="mx-auto mt-8 grid max-w-4xl gap-5">
            {state.entries.map((entry, index) => (
              <ChatThreadEntry
                entry={entry}
                entryRef={
                  requestStatus !== 'loading' && index === state.entries.length - 1
                    ? latestEntryRef
                    : undefined
                }
                key={entry.id}
                onRetry={retryEntry}
                retryAvailable={!isAnyRequestPending}
              />
            ))}
            {requestStatus === 'loading' ? (
              <li ref={latestEntryRef}>
                {loadingStage === 'timeout' ? (
                  <section className="max-w-xl rounded-[var(--radius-standard)] border border-[var(--color-warning-border)] bg-[var(--color-warning-surface)] p-4 text-[var(--color-warning-foreground)]">
                    <div className="flex items-start gap-3">
                      <LoadingSpinner label="Still working on your answer" size="sm" />
                      <div>
                        <h2 className="font-display text-type-heading-sm font-semibold text-[var(--color-ink)]">
                          {errorCopy.public.loading.timeoutTitle}
                        </h2>
                        <p className="text-type-body-sm-relaxed mt-1">
                          {continuedWaiting
                            ? errorCopy.public.loading.continued
                            : errorCopy.public.loading.timeoutMessage}
                        </p>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                      {!continuedWaiting ? (
                        <button
                          className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-warning-foreground)] px-4 font-semibold ${controlFocusClass}`}
                          onClick={() => setContinuedWaiting(true)}
                          type="button"
                        >
                          Keep waiting
                        </button>
                      ) : null}
                      <button
                        className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 font-semibold text-[var(--color-body)] ${controlFocusClass}`}
                        onClick={cancelSlowRequest}
                        type="button"
                      >
                        Cancel request
                      </button>
                    </div>
                  </section>
                ) : (
                  <div className="inline-flex items-center gap-3 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-[var(--color-muted)]">
                    <LoadingSpinner
                      label={
                        loadingStage === 'slow'
                          ? 'Still working on your answer'
                          : 'Finding a clear answer'
                      }
                      size="sm"
                    />
                    <span className="text-type-body-sm">
                      {loadingStage === 'slow'
                        ? errorCopy.public.loading.slow
                        : errorCopy.public.loading.fast}
                    </span>
                  </div>
                )}
              </li>
            ) : null}
          </ol>
        ) : null}
      </section>

      <section
        aria-label="Ask another question"
        className="mx-auto mt-8 max-w-4xl lg:mt-4 lg:w-full"
      >
        <form
          className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 shadow-[var(--shadow-component)] sm:p-5"
          onSubmit={handleComposerSubmit}
        >
          <div className="flex items-center justify-between gap-4">
            <label
              className="font-display text-type-heading-sm font-semibold text-[var(--color-ink)]"
              htmlFor="public-ask-question"
            >
              Your question
            </label>
            <p
              aria-live="polite"
              className="text-type-label text-right text-[var(--color-muted)]"
              id="public-ask-input-mode"
              role="status"
            >
              {activeInputLabel(activeMode, fileNeedsQuestion)}
            </p>
          </div>
          <textarea
            aria-describedby={
              fileNeedsQuestion
                ? 'public-ask-input-mode public-ask-pdf-question-required'
                : 'public-ask-input-mode'
            }
            className={`text-type-body mt-3 min-h-28 w-full resize-y rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-[var(--color-body)] placeholder:text-[var(--color-muted)] disabled:cursor-not-allowed disabled:bg-[var(--color-surface-subtle)] ${controlFocusClass}`}
            disabled={isAnyRequestPending}
            id="public-ask-question"
            onChange={handleQuestionChange}
            onKeyDown={handleQuestionKeyDown}
            placeholder={selectedFile ? 'Ask a question about this PDF…' : 'Ask another question…'}
            ref={textInputRef}
            value={draft}
          />
          {fileNeedsQuestion ? (
            <p
              className="text-type-label mt-2 text-[var(--color-warning-foreground)]"
              id="public-ask-pdf-question-required"
              role="status"
            >
              Enter a question about this PDF.
            </p>
          ) : null}
          <div className="mt-3 flex flex-col-reverse gap-3 border-t border-[var(--color-surface-subtle)] pt-3 sm:flex-row sm:items-center sm:justify-between">
            <button
              aria-controls="public-ask-pdf-upload"
              aria-expanded={isUploadVisible}
              className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-brass)] bg-[var(--color-surface-raised)] px-4 font-semibold text-[var(--color-brass-active)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)] disabled:cursor-not-allowed disabled:opacity-60 ${controlFocusClass}`}
              disabled={isAnyRequestPending}
              onClick={() => setIsUploadVisible(true)}
              type="button"
            >
              Add one PDF
            </button>
            <button
              className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-5 font-semibold text-[var(--color-inverse)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-brass-hover)] active:bg-[var(--color-brass-active)] disabled:cursor-not-allowed disabled:opacity-60 ${controlFocusClass}`}
              disabled={isAnyRequestPending || !draft.trim()}
              type="submit"
            >
              Send
            </button>
          </div>
        </form>

        {isUploadVisible ? (
          <div className="mt-4" id="public-ask-pdf-upload">
            <UploadDropzone
              accept="application/pdf"
              disabled={isAnyRequestPending}
              key={uploadKey}
              multiple={false}
              onFilesSelected={handleFilesSelected}
            />
          </div>
        ) : null}
      </section>
    </main>
  );
}
