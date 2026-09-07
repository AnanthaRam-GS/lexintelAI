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
} from 'react';

import { ErrorMessage } from '../../../components/shared/ErrorMessage';
import { ResponseCard } from '../../../components/shared/ResponseCard';
import { UploadDropzone } from '../../../components/shared/UploadDropzone';

import { usePublicSession } from '../PublicSessionProvider';
import type { PublicQueryInput } from '../query-client';
import { toPublicResponseCardProps } from '../response-adapter';

import { chatReducer, initialChatState, type ChatEntry, type ChatMessage } from './chat-model';

const emptyStateExamples = [
  'My landlord has not returned my deposit. What can I do?',
  'Can my employer withhold my final salary?',
  'What should I do after receiving a court notice?',
];

const controlFocusClass =
  'focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem]';

type ActiveInputMode = 'text' | 'file' | 'none';

export interface PublicAskProps {
  /**
   * Task 4 supplies the request lifecycle through this seam. The composer owns
   * only input selection and user-turn creation in this task.
   */
  isRequestPending?: boolean;
  onInputSubmitted?: (input: PublicQueryInput, entry: ChatEntry) => void;
  onNewConversation?: () => void;
  onRetry?: (entry: ChatEntry) => void;
}

function activeInputLabel(activeMode: ActiveInputMode): string {
  switch (activeMode) {
    case 'text':
      return 'Active input: Text question';
    case 'file':
      return 'Active input: Temporary PDF';
    case 'none':
      return 'Choose text or one PDF';
  }
}

function ChatThreadEntry({
  entry,
  onRetry,
}: {
  entry: ChatEntry;
  onRetry: (entry: ChatEntry) => void;
}) {
  const { message } = entry;

  if (message.role === 'user' && message.kind === 'text') {
    return (
      <li className="justify-self-end">
        <article
          aria-label="Your submitted question"
          className="max-w-[78%] rounded-[var(--radius-standard)] rounded-br-[var(--radius-compact)] bg-[var(--color-ink)] px-4 py-3 text-type-body text-[var(--color-inverse)]"
        >
          {message.content}
        </article>
      </li>
    );
  }

  if (message.role === 'user' && message.kind === 'file') {
    return (
      <li className="justify-self-end">
        <article
          aria-label={`Temporary PDF: ${message.fileName}`}
          className="max-w-[78%] rounded-[var(--radius-standard)] border border-[var(--color-info-border)] bg-[var(--color-info-surface)] px-4 py-3 text-type-body text-[var(--color-info-foreground)]"
        >
          <p className="truncate font-semibold">{message.fileName}</p>
          <p className="text-type-body-sm mt-1">Checked temporarily for this question</p>
        </article>
      </li>
    );
  }

  if (message.role === 'assistant' && 'response' in message) {
    return (
      <li>
        <ResponseCard {...toPublicResponseCardProps(message.response)} />
      </li>
    );
  }

  return (
    <li>
      <ErrorMessage
        message="Your question is still here—please try again."
        onRetry={() => onRetry(entry)}
        title="We couldn't answer that just now."
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
  const entrySequence = useRef(0);
  const textInputRef = useRef<HTMLTextAreaElement>(null);
  const newConversationButtonRef = useRef<HTMLButtonElement>(null);

  const activeMode: ActiveInputMode = selectedFile ? 'file' : draft.trim() ? 'text' : 'none';

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
    },
    [onInputSubmitted],
  );

  useEffect(() => {
    if (!pendingInput || isRequestPending) {
      return;
    }

    const input = takePendingInput();
    if (input) {
      appendInput(input);
    }
  }, [appendInput, isRequestPending, pendingInput, takePendingInput]);

  const resetComposer = useCallback(() => {
    setDraft('');
    setSelectedFile(null);
    setIsUploadVisible(false);
    setUploadKey((key) => key + 1);
  }, []);

  const submitCurrentInput = useCallback(() => {
    if (isRequestPending) {
      return;
    }

    if (selectedFile) {
      appendInput({ kind: 'file', file: selectedFile });
      resetComposer();
      return;
    }

    const content = draft.trim();
    if (!content) {
      return;
    }

    appendInput({ kind: 'text', content });
    resetComposer();
  }, [appendInput, draft, isRequestPending, resetComposer, selectedFile]);

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
    if (isRequestPending) {
      return;
    }

    armTextInput(event.target.value);
  };

  const handleQuestionKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !isRequestPending && activeMode === 'text') {
      event.preventDefault();
      submitCurrentInput();
    }
  };

  const handleFilesSelected = (files: File[]) => {
    if (isRequestPending) {
      return;
    }

    const [file] = files;
    setSelectedFile(file ?? null);

    if (file) {
      setDraft('');
    }
  };

  const clearConversation = () => {
    dispatch({ type: 'clear' });
    resetComposer();
    setIsConfirmingNewConversation(false);
    onNewConversation?.();
    textInputRef.current?.focus();
  };

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

  const retryEntry = (entry: ChatEntry) => {
    if (isRequestPending) {
      return;
    }

    dispatch({ type: 'remove-error', id: entry.id });
    onRetry?.(entry);
  };

  return (
    <main className="mx-auto min-h-screen max-w-5xl px-5 py-6 sm:px-8 sm:py-10">
      <header className="mx-auto flex max-w-4xl flex-col gap-4 border-b border-[var(--color-border)] pb-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-display text-type-heading-md font-bold text-[var(--color-ink)]">
            Your conversation
          </h1>
          <p className="text-type-body-sm mt-1 text-[var(--color-muted)]">
            Available only during this visit
          </p>
        </div>
        <button
          className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-brass)] bg-[var(--color-surface-raised)] px-4 font-semibold text-[var(--color-brass-active)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)] ${controlFocusClass}`}
          onClick={requestNewConversation}
          ref={newConversationButtonRef}
          type="button"
        >
          Start New Conversation
        </button>
      </header>

      {isConfirmingNewConversation ? (
        <section
          aria-label="Confirm new conversation"
          className="mx-auto mt-5 max-w-4xl rounded-[var(--radius-standard)] border border-[var(--color-warning-border)] bg-[var(--color-warning-surface)] p-4"
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
              Confirm
            </button>
            <button
              className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-4 font-semibold text-[var(--color-body)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)] ${controlFocusClass}`}
              onClick={cancelNewConversation}
              type="button"
            >
              Cancel
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
                  disabled={isRequestPending}
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

      {state.entries.length > 0 ? (
        <ol aria-label="Conversation" className="mx-auto mt-8 grid max-w-4xl gap-5">
          {state.entries.map((entry) => (
            <ChatThreadEntry entry={entry} key={entry.id} onRetry={retryEntry} />
          ))}
        </ol>
      ) : null}

      <section
        aria-label="Ask another question"
        className="mx-auto mt-8 max-w-4xl lg:sticky lg:bottom-4"
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
              {activeInputLabel(activeMode)}
            </p>
          </div>
          <textarea
            aria-describedby="public-ask-input-mode"
            className={`text-type-body mt-3 min-h-28 w-full resize-y rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-[var(--color-body)] placeholder:text-[var(--color-muted)] disabled:cursor-not-allowed disabled:bg-[var(--color-surface-subtle)] ${controlFocusClass}`}
            disabled={isRequestPending}
            id="public-ask-question"
            onChange={handleQuestionChange}
            onKeyDown={handleQuestionKeyDown}
            placeholder="Ask another question…"
            ref={textInputRef}
            value={draft}
          />
          <div className="mt-3 flex flex-col-reverse gap-3 border-t border-[var(--color-surface-subtle)] pt-3 sm:flex-row sm:items-center sm:justify-between">
            <button
              aria-controls="public-ask-pdf-upload"
              aria-expanded={isUploadVisible}
              className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-brass)] bg-[var(--color-surface-raised)] px-4 font-semibold text-[var(--color-brass-active)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)] disabled:cursor-not-allowed disabled:opacity-60 ${controlFocusClass}`}
              disabled={isRequestPending}
              onClick={() => setIsUploadVisible(true)}
              type="button"
            >
              Add one PDF
            </button>
            <button
              className={`text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-5 font-semibold text-[var(--color-inverse)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-brass-hover)] active:bg-[var(--color-brass-active)] disabled:cursor-not-allowed disabled:opacity-60 ${controlFocusClass}`}
              disabled={isRequestPending || activeMode === 'none'}
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
              disabled={isRequestPending}
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
