'use client';

import React from 'react';
import Link from 'next/link';

interface ActionCard {
  title: string;
  badge: string;
  description: string;
  href: string;
  ctaText: string;
  icon: React.ReactNode;
}

const ACTION_CARDS: ActionCard[] = [
  {
    title: 'Text Query Workbench',
    badge: 'Core Research',
    description:
      'Input natural language fact patterns or legal questions to retrieve relevant precedents, identify applicable IPC/BNS statutory provisions, and generate structured case briefs.',
    href: '/professional/query',
    ctaText: 'Start Text Query',
    icon: (
      <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
        />
      </svg>
    ),
  },
  {
    title: 'Confidential PDF Analysis',
    badge: 'Private Analysis',
    description:
      'Upload an FIR, appeal brief, or judgment PDF for ephemeral AI analysis. Extracts key points, matches Supreme Court and High Court precedents, and never ingests files into the shared corpus.',
    href: '/professional/upload',
    ctaText: 'Analyze Document',
    icon: (
      <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
        />
      </svg>
    ),
  },
  {
    title: 'Judicial & Statutory Analytics',
    badge: '5-Tab Dashboard',
    description:
      'Interactive visualizations of offense trends, court outcome distributions across trial and appellate courts, statutory co-occurrences, IPC-BNS mapping, and NCRB crime statistics.',
    href: '/professional/analytics',
    ctaText: 'Open Analytics',
    icon: (
      <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
        />
      </svg>
    ),
  },
  {
    title: 'Research History & Briefs',
    badge: 'Audit Trail',
    description:
      'Review past authenticated research queries and document analyses. Expand stored case briefs, citations, and identified statutory provisions with instant client-side pagination.',
    href: '/professional/history',
    ctaText: 'View History',
    icon: (
      <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
    ),
  },
];

export default function ProfessionalHomePage() {
  return (
    <div className="space-y-8" data-testid="professional-home">
      {/* Welcome & Overview Header */}
      <div className="border-b border-[var(--color-border)] pb-6">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-brass)]">
              Professional Legal Intelligence
            </span>
            <h1 className="font-display text-2xl font-bold tracking-tight text-[var(--color-ink)] sm:text-3xl">
              Counsel Research Workbench
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center rounded-full bg-[var(--color-success-surface)] px-2.5 py-1 text-xs font-semibold text-[var(--color-success-foreground)] border border-[var(--color-success-border)]">
              <span className="mr-1.5 h-2 w-2 rounded-full bg-[var(--color-success)] animate-pulse" />
              Live AI RAG Connected
            </span>
          </div>
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[var(--color-body)]">
          Welcome to the LegalAI Professional Portal. Analyze complex fact patterns, query Supreme
          Court and High Court precedents, examine transition mappings between the Indian Penal Code
          (IPC) and Bharatiya Nyaya Sanhita (BNS), and conduct private brief analysis.
        </p>
      </div>

      {/* Quick Access Action Grid */}
      <section aria-label="Professional tools" className="grid gap-6 sm:grid-cols-2">
        {ACTION_CARDS.map((card) => (
          <article
            key={card.title}
            className="group flex flex-col justify-between rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-xs transition-all duration-[var(--motion-standard)] hover:border-[var(--color-brass)] hover:shadow-[var(--shadow-component)]"
          >
            <div>
              <div className="flex items-center justify-between">
                <div className="flex h-11 w-11 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-ink)] text-[var(--color-brass)] shadow-xs transition-colors group-hover:bg-[var(--color-brass)] group-hover:text-white">
                  {card.icon}
                </div>
                <span className="rounded bg-[var(--color-surface-subtle)] px-2.5 py-1 text-[0.6875rem] font-bold uppercase tracking-wider text-[var(--color-brass)]">
                  {card.badge}
                </span>
              </div>

              <h2 className="font-display mt-4 text-lg font-bold text-[var(--color-ink)] group-hover:text-[var(--color-brass-hover)]">
                {card.title}
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-[var(--color-muted)]">
                {card.description}
              </p>
            </div>

            <div className="mt-6 pt-4 border-t border-[var(--color-border)]">
              <Link
                href={card.href}
                className="inline-flex w-full items-center justify-center gap-2 rounded-[var(--radius-compact)] bg-[var(--color-canvas)] px-4 py-2.5 text-xs font-bold uppercase tracking-wider text-[var(--color-ink)] border border-[var(--color-border)] transition-all group-hover:bg-[var(--color-ink)] group-hover:text-white group-hover:border-transparent focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
              >
                <span>{card.ctaText}</span>
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M14 5l7 7m0 0l-7 7m7-7H3"
                  />
                </svg>
              </Link>
            </div>
          </article>
        ))}
      </section>

      {/* Confidentiality & Security Notice Banner */}
      <div className="rounded-[var(--radius-standard)] border border-[var(--color-info-border)] bg-[var(--color-info-surface)] p-4 text-xs leading-relaxed text-[var(--color-info-foreground)] sm:p-5">
        <div className="flex items-start gap-3">
          <svg
            className="h-5 w-5 shrink-0 text-[var(--color-info)] mt-0.5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
            />
          </svg>
          <div>
            <h3 className="font-bold text-[var(--color-ink)] text-sm mb-1">
              Client Confidentiality &amp; Ephemeral Processing Guarantee
            </h3>
            <p>
              Documents and queries submitted through Professional Mode are processed solely in
              memory for statutory identification and precedent extraction. Temporary PDFs are
              dispatched directly to the analytical query service and are <strong>never</strong>{' '}
              added to the shared public corpus or retained in persistent storage.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
