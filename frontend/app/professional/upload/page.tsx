'use client';

import React, { useState } from 'react';
import { ApiClientError, limitMessage, queryApi } from '../../../lib/api';
import {
  ErrorMessage,
  LoadingSpinner,
  QueuedNotice,
  UploadDropzone,
} from '../../../components/shared';
import { ProfessionalResultsView } from '../../../components/professional/ProfessionalResultsView';
import type { ProfessionalQueryResponse } from '../../../lib/types/api';

export default function ProfessionalUploadPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [errorState, setErrorState] = useState<{
    title: string;
    message: string;
    detail?: string;
  } | null>(null);
  const [result, setResult] = useState<ProfessionalQueryResponse | null>(null);

  const handleFilesSelected = (files: File[]) => {
    if (files.length > 0) {
      setSelectedFile(files[0]);
      setErrorState(null);
    }
  };

  const handleStartAnalysis = async () => {
    if (!selectedFile) {
      setErrorState({
        title: 'No Document Selected',
        message: 'Please upload a PDF document (FIR, judgment, or case memorandum) to proceed.',
      });
      return;
    }

    setIsAnalyzing(true);
    setErrorState(null);

    try {
      // CRITICAL CONTRACT: Sends directly to /query/professional/pdf via multipart/form-data.
      // Must NOT call corpus ingestion. No specific question is collected on this
      // page, so this is always whole-document brief mode (bounded hierarchical
      // analysis), never the question-focused targeted-retrieval mode.
      const response = await queryApi.submitPdf(selectedFile, undefined, undefined, 'brief');
      setResult(response);
    } catch (err) {
      const limited = limitMessage(err);
      if (limited) {
        setErrorState({ title: 'Please slow down', message: limited });
        return;
      }
      if (err instanceof ApiClientError && err.status === 429) {
        setErrorState({
          title: 'Usage Limit Reached',
          message:
            'AI analysis capacity is temporarily exhausted. Your document was not stored. Please try again after the provider limit resets.',
        });
        return;
      }
      setErrorState({
        title: 'Document Analysis Failed',
        message:
          err instanceof Error ? err.message : 'Unable to analyze the uploaded legal document.',
        detail: (err as { detail?: string })?.detail,
      });
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleReset = () => {
    setResult(null);
    setSelectedFile(null);
    setErrorState(null);
  };

  return (
    <div className="space-y-6" data-testid="professional-upload-page">
      {/* Page Heading */}
      <div>
        <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-brass)]">
          Confidential Document Analysis
        </span>
        <h1 className="font-display text-2xl font-bold tracking-tight text-[var(--color-ink)] sm:text-3xl">
          Private Case File &amp; Brief Analysis
        </h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Upload an FIR, appeal petition, chargesheet, or court judgment in PDF format for
          in-session statutory identification, precedent retrieval, and case brief drafting.
        </p>
      </div>

      {/* Results View or Upload Workspace */}
      {result ? (
        <ProfessionalResultsView
          result={result}
          queryTitle={selectedFile ? selectedFile.name : 'Analyzed Legal Brief'}
          onReset={handleReset}
        />
      ) : (
        <div className="space-y-6">
          {/* Privacy & Non-Ingestion Assurance Banner */}
          <div className="rounded-[var(--radius-standard)] border border-[var(--color-brass)]/40 bg-[var(--color-surface)] p-4 shadow-xs">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--color-brass)]/15 text-[var(--color-brass)]">
                <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                  <path
                    fillRule="evenodd"
                    d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>
              <div className="text-xs leading-relaxed text-[var(--color-body)]">
                <p className="font-bold text-[var(--color-ink)] text-sm">
                  Privileged Legal Document Safeguard
                </p>
                <p className="mt-0.5">
                  Uploaded files are submitted directly to the ephemeral query pipeline (
                  <code>/query/professional/pdf</code>). They are processed exclusively in-memory
                  for your session and are{' '}
                  <strong>never indexed, stored, or added to the global corpus</strong>.
                </p>
              </div>
            </div>
          </div>

          {/* Error Feedback */}
          {errorState && (
            <ErrorMessage
              variant="inline"
              title={errorState.title}
              message={errorState.message}
              technicalDetail={errorState.detail}
              onRetry={handleStartAnalysis}
            />
          )}

          {/* Dropzone Container Card */}
          <section
            aria-label="Upload private document"
            className="rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-xs sm:p-8"
          >
            <UploadDropzone
              accept="application/pdf,.pdf"
              maxSizeMB={25}
              multiple={false}
              disabled={isAnalyzing}
              onFilesSelected={handleFilesSelected}
            />

            {selectedFile && (
              <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-t border-[var(--color-border)] pt-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-surface-subtle)] text-[var(--color-brass)]">
                    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"
                      />
                    </svg>
                  </div>
                  <div>
                    <p className="text-sm font-bold text-[var(--color-ink)]">{selectedFile.name}</p>
                    <p className="text-xs text-[var(--color-muted)]">
                      {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB · Ready for analysis
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={handleStartAnalysis}
                  disabled={isAnalyzing}
                  className="cursor-pointer inline-flex items-center justify-center gap-2 rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-6 py-2.5 text-sm font-semibold text-white shadow-xs transition-colors hover:bg-[var(--color-brass-hover)] active:bg-[var(--color-brass-active)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isAnalyzing ? (
                    <>
                      <LoadingSpinner size="sm" label="Analyzing document securely" />
                      <span>Analyzing document and retrieving relevant legal authorities...</span>
                    </>
                  ) : (
                    <>
                      <span>Begin Private Analysis</span>
                      <svg
                        className="h-4 w-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M14 5l7 7m0 0l-7 7m7-7H3"
                        />
                      </svg>
                    </>
                  )}
                </button>
              </div>
            )}
            <QueuedNotice active={isAnalyzing} className="mt-4" />
          </section>
        </div>
      )}
    </div>
  );
}
