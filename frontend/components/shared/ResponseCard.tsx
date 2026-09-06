import { useId } from 'react';

import type { Citation, ResponseCardProps } from './response-types';

export type { AnswerContent, Citation, LegalSection, ResponseCardProps } from './response-types';

const linkClass =
  'font-semibold text-[var(--color-info-foreground)] underline decoration-[var(--color-info)] underline-offset-4 transition-colors duration-[var(--motion-fast)] hover:text-[var(--color-ink)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem]';

const clampConfidence = (confidence: number) => Math.min(100, Math.max(0, Math.round(confidence)));

function CitationMetadata({ citation }: { citation: Citation }) {
  const court = citation.court?.trim();
  const hasYear = typeof citation.year === 'number';

  return court || hasYear ? (
    <p className="mt-1 text-sm text-[var(--color-muted)]">
      {court ? <span>{court}</span> : null}
      {court && hasYear ? <span aria-hidden="true"> · </span> : null}
      {hasYear ? <span>{citation.year}</span> : null}
    </p>
  ) : null;
}

function ProfessionalResponse({
  content,
  citations,
  sections,
  headingId,
}: Omit<ResponseCardProps, 'mode'> & { headingId: string }) {
  return (
    <article
      aria-label="Professional legal research response"
      className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-component)] sm:p-6"
    >
      <header className="border-b border-[var(--color-border)] pb-4">
        <p className="text-sm font-semibold uppercase tracking-wide text-[var(--color-brass)]">
          Research response
        </p>
        <h2 className="mt-1 font-[family-name:var(--font-display)] text-2xl font-semibold text-[var(--color-ink)]">
          {content.heading}
        </h2>
      </header>

      <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(16rem,0.8fr)]">
        <section aria-label="Legal analysis" className="min-w-0 space-y-4">
          {content.paragraphs.map((paragraph, index) => (
            <p className="leading-7 text-[var(--color-body)]" key={`${paragraph}-${index}`}>
              {paragraph}
            </p>
          ))}

          {content.keyPoints?.length ? (
            <section aria-labelledby={`${headingId}-key-points`} className="pt-1">
              <h3
                className="font-[family-name:var(--font-display)] text-lg font-semibold text-[var(--color-ink)]"
                id={`${headingId}-key-points`}
              >
                Key points
              </h3>
              <ul className="mt-2 list-disc space-y-2 pl-5 text-[var(--color-body)]">
                {content.keyPoints.map((point, index) => (
                  <li key={`${point}-${index}`}>{point}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </section>

        <aside aria-label="Legal provisions and sources" className="space-y-5">
          {sections.length > 0 ? (
            <section aria-labelledby={`${headingId}-provisions`}>
              <h3
                className="font-[family-name:var(--font-display)] text-lg font-semibold text-[var(--color-ink)]"
                id={`${headingId}-provisions`}
              >
                Legal provisions
              </h3>
              <ul className="mt-2 space-y-3">
                {sections.map((legalSection) => (
                  <li
                    className="rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3"
                    key={`${legalSection.code}-${legalSection.section}-${legalSection.sourceUrl}`}
                  >
                    <p className="text-sm font-semibold text-[var(--color-brass)]">
                      {legalSection.code} § {legalSection.section}
                    </p>
                    <h4 className="mt-1 font-semibold text-[var(--color-ink)]">
                      {legalSection.title}
                    </h4>
                    {legalSection.explanation ? (
                      <p className="mt-1 text-sm leading-6 text-[var(--color-body)]">
                        {legalSection.explanation}
                      </p>
                    ) : null}
                    {typeof legalSection.confidence === 'number' ? (
                      <p className="mt-2 text-sm font-semibold text-[var(--color-success-foreground)]">
                        {clampConfidence(legalSection.confidence)}% confidence
                      </p>
                    ) : null}
                    <a
                      className={`${linkClass} mt-2 inline-block text-sm`}
                      href={legalSection.sourceUrl}
                      rel="noreferrer"
                      target="_blank"
                    >
                      View provision
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {citations.length > 0 ? (
            <section aria-labelledby={`${headingId}-citations`}>
              <h3
                className="font-[family-name:var(--font-display)] text-lg font-semibold text-[var(--color-ink)]"
                id={`${headingId}-citations`}
              >
                Authorities cited
              </h3>
              <ul className="mt-2 space-y-3">
                {citations.map((citation) => (
                  <li
                    className="rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3"
                    key={`${citation.title}-${citation.sourceUrl}`}
                  >
                    <p className="font-semibold text-[var(--color-ink)]">{citation.title}</p>
                    <CitationMetadata citation={citation} />
                    {citation.excerpt ? (
                      <blockquote className="mt-2 border-l-2 border-[var(--color-brass)] pl-3 text-sm leading-6 text-[var(--color-body)]">
                        {citation.excerpt}
                      </blockquote>
                    ) : null}
                    <a
                      className={`${linkClass} mt-2 inline-block text-sm`}
                      href={citation.sourceUrl}
                      rel="noreferrer"
                      target="_blank"
                    >
                      View source
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </aside>
      </div>

      <ResponseFooter />
    </article>
  );
}

function PublicResponse({
  content,
  citations,
  sections,
  headingId,
}: Omit<ResponseCardProps, 'mode'> & { headingId: string }) {
  return (
    <article
      aria-label="Plain-language legal information"
      className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[var(--shadow-component)] sm:p-8"
    >
      <header>
        <p className="text-sm font-semibold text-[var(--color-brass)]">In plain language</p>
        <h2 className="mt-2 font-[family-name:var(--font-display)] text-3xl font-semibold text-[var(--color-ink)]">
          {content.heading}
        </h2>
      </header>

      <section aria-label="Explanation" className="mt-6 space-y-5">
        {content.paragraphs.map((paragraph, index) => (
          <p className="text-lg leading-8 text-[var(--color-body)]" key={`${paragraph}-${index}`}>
            {paragraph}
          </p>
        ))}

        {content.keyPoints?.length ? (
          <section
            aria-labelledby={`${headingId}-key-points`}
            className="rounded-[var(--radius-compact)] bg-[var(--color-surface-subtle)] p-4 sm:p-5"
          >
            <h3
              className="font-[family-name:var(--font-display)] text-xl font-semibold text-[var(--color-ink)]"
              id={`${headingId}-key-points`}
            >
              What you can do
            </h3>
            <ul className="mt-3 space-y-3 text-[var(--color-body)]">
              {content.keyPoints.map((point, index) => (
                <li className="flex gap-3" key={`${point}-${index}`}>
                  <span
                    aria-hidden="true"
                    className="mt-2 size-2 shrink-0 rounded-full bg-[var(--color-brass)]"
                  />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </section>

      {sections.length > 0 ? (
        <section aria-labelledby={`${headingId}-provisions`} className="mt-8">
          <h3
            className="font-[family-name:var(--font-display)] text-xl font-semibold text-[var(--color-ink)]"
            id={`${headingId}-provisions`}
          >
            Related law
          </h3>
          <ul className="mt-3 space-y-4">
            {sections.map((legalSection) => (
              <li
                className="border-l-2 border-[var(--color-brass)] pl-4"
                key={`${legalSection.code}-${legalSection.section}-${legalSection.sourceUrl}`}
              >
                <h4 className="font-semibold text-[var(--color-ink)]">{legalSection.title}</h4>
                {legalSection.explanation ? (
                  <p className="mt-1 leading-7 text-[var(--color-body)]">
                    {legalSection.explanation}
                  </p>
                ) : null}
                <a
                  className={`${linkClass} mt-2 inline-block`}
                  href={legalSection.sourceUrl}
                  rel="noreferrer"
                  target="_blank"
                >
                  Learn more
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {citations.length > 0 ? (
        <section aria-labelledby={`${headingId}-sources`} className="mt-8">
          <h3
            className="font-[family-name:var(--font-display)] text-xl font-semibold text-[var(--color-ink)]"
            id={`${headingId}-sources`}
          >
            Sources
          </h3>
          <ul className="mt-3 space-y-3">
            {citations.map((citation) => (
              <li
                className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1"
                key={`${citation.title}-${citation.sourceUrl}`}
              >
                <span className="font-medium text-[var(--color-body)]">{citation.title}</span>
                <a className={linkClass} href={citation.sourceUrl} rel="noreferrer" target="_blank">
                  Learn more
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <ResponseFooter />
    </article>
  );
}

function ResponseFooter() {
  return (
    <footer className="mt-6 border-t border-[var(--color-border)] pt-4 text-sm leading-6 text-[var(--color-muted)]">
      This information is for general education and is not legal advice.
    </footer>
  );
}

export function ResponseCard(props: ResponseCardProps) {
  const headingId = useId();
  const { mode, ...responseProps } = props;

  return mode === 'professional' ? (
    <ProfessionalResponse {...responseProps} headingId={headingId} />
  ) : (
    <PublicResponse {...responseProps} headingId={headingId} />
  );
}
