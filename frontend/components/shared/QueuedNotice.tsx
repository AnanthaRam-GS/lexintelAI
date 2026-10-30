'use client';

import React, { useEffect, useState } from 'react';

/**
 * Step 23: answers wait in the backend's pacing queue when the answer model is at its rate limit, for up to about
 * 90 seconds. A query pending longer than QUEUED_NOTICE_DELAY_MS shows this plain-language notice instead of a
 * spinner alone. A queue timeout is still the MODEL_BUSY message (lib/api.ts), not this notice.
 */
export const QUEUED_NOTICE_DELAY_MS = 5_000;
export const QUEUED_NOTICE_COPY = 'High demand — your answer is queued and will appear shortly.';

export interface QueuedNoticeProps {
  /** True while the request is pending. */
  active: boolean;
  delayMs?: number;
  className?: string;
}

export function QueuedNotice({ active, delayMs = QUEUED_NOTICE_DELAY_MS, className = '' }: QueuedNoticeProps) {
  // Mounted only while a request is pending, so each request starts its own delay from zero.
  return active ? <DelayedQueuedNotice className={className} delayMs={delayMs} /> : null;
}

function DelayedQueuedNotice({ delayMs, className }: { delayMs: number; className: string }) {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setShown(true), delayMs);
    return () => clearTimeout(timer);
  }, [delayMs]);

  if (!shown) return null;
  return (
    <p
      aria-live="polite"
      className={`text-type-body-sm rounded-[var(--radius-standard)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-[var(--color-muted)] ${className}`}
      role="status"
    >
      {QUEUED_NOTICE_COPY}
    </p>
  );
}
