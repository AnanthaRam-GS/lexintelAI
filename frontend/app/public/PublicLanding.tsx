'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';

import { UploadDropzone } from '../../components/shared';

import { usePublicSession } from './PublicSessionProvider';

const examples = [
  'My landlord has not returned my deposit. What can I do?',
  'Can my employer withhold my final salary?',
  'What should I do after receiving a court notice?',
];

export function PublicLanding() {
  const router = useRouter();
  const { setPendingInput } = usePublicSession();
  const [question, setQuestion] = useState('');
  const [isUploadVisible, setIsUploadVisible] = useState(false);

  const submitQuestion = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const content = question.trim();
    if (!content) {
      return;
    }

    setPendingInput({ kind: 'text', content });
    router.push('/public/ask');
  };

  const selectFile = (files: File[]) => {
    const [file] = files;

    if (!file) {
      return;
    }

    setPendingInput({ kind: 'file', file });
    router.push('/public/ask');
  };

  return (
    <main className="mx-auto min-h-screen max-w-5xl px-5 py-6 sm:px-8 sm:py-10">
      <header className="flex items-center justify-between gap-4">
        <p className="font-display text-type-heading-md font-bold text-[var(--color-ink)]">
          LegalAI
        </p>
        <p className="text-type-caption text-[var(--color-muted)]">No login needed</p>
      </header>

      <section className="mx-auto mt-16 max-w-3xl" aria-labelledby="public-landing-title">
        <p className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-active)]">
          PLAIN-LANGUAGE LEGAL INFORMATION
        </p>
        <h1
          className="font-display text-type-heading-xl mt-3 font-semibold tracking-tight text-[var(--color-ink)] sm:text-type-heading-2xl"
          id="public-landing-title"
        >
          Understand your legal question without the legal jargon.
        </h1>
        <p className="text-type-body-lg mt-5 max-w-2xl text-[var(--color-muted)]">
          Ask in your own words or share one PDF. We explain the information clearly and suggest
          practical next steps.
        </p>

        <form
          className="mt-8 rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 shadow-[var(--shadow-component)] sm:p-5"
          onSubmit={submitQuestion}
        >
          <label className="sr-only" htmlFor="public-question">
            Your question
          </label>
          <textarea
            className="text-type-body min-h-28 w-full resize-y border-0 bg-transparent text-[var(--color-body)] outline-none placeholder:text-[var(--color-muted)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem]"
            id="public-question"
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="What would you like help understanding?"
            value={question}
          />
          <div className="mt-3 flex flex-col-reverse gap-3 border-t border-[var(--color-surface-subtle)] pt-3 sm:flex-row sm:items-center sm:justify-between">
            <button
              aria-expanded={isUploadVisible}
              aria-controls="public-pdf-upload"
              className="text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] border border-[var(--color-brass)] bg-[var(--color-surface-raised)] px-4 font-semibold text-[var(--color-brass-active)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)]"
              onClick={() => setIsUploadVisible((visible) => !visible)}
              type="button"
            >
              Upload one PDF
            </button>
            <button
              className="text-type-control inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-5 font-semibold text-[var(--color-inverse)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-brass-hover)] active:bg-[var(--color-brass-active)] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={!question.trim()}
              type="submit"
            >
              Ask your question
            </button>
          </div>
        </form>

        {isUploadVisible ? (
          <div className="mt-4" id="public-pdf-upload">
            <UploadDropzone
              accept="application/pdf"
              multiple={false}
              onFilesSelected={selectFile}
            />
          </div>
        ) : null}
      </section>

      <section className="mx-auto mt-12 max-w-3xl" aria-labelledby="example-questions-title">
        <p
          className="text-type-label font-semibold uppercase tracking-wide text-[var(--color-brass-active)]"
          id="example-questions-title"
        >
          QUESTIONS PEOPLE OFTEN ASK
        </p>
        <ul className="mt-3 grid gap-3">
          {examples.map((example) => (
            <li key={example}>
              <button
                className="text-type-body min-h-11 w-full rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-left font-medium text-[var(--color-ink)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)]"
                onClick={() => setQuestion(example)}
                type="button"
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <aside className="mx-auto mt-12 max-w-3xl border-t border-[var(--color-border)] pt-5 text-type-body-sm-relaxed text-[var(--color-muted)]">
        <h2 className="font-display text-type-heading-sm font-bold text-[var(--color-ink)]">
          A quick note before you begin
        </h2>
        <p className="mt-2">
          This service gives general information, not personal legal advice. A PDF is checked once
          for your question and is not stored or added to a shared collection.
        </p>
      </aside>
    </main>
  );
}
