import { act, cleanup, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QUEUED_NOTICE_COPY, QUEUED_NOTICE_DELAY_MS, QueuedNotice } from './QueuedNotice';

describe('QueuedNotice', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('stays hidden for the first 5 seconds of a pending request, then explains the queue', () => {
    render(<QueuedNotice active />);
    expect(QUEUED_NOTICE_DELAY_MS).toBe(5_000);
    act(() => vi.advanceTimersByTime(4_999));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    const notice = screen.getByRole('status');
    expect(notice).toHaveTextContent(QUEUED_NOTICE_COPY);
    expect(notice).toHaveAttribute('aria-live', 'polite');
  });

  it('disappears when the request finishes and starts over for the next one', () => {
    const { rerender } = render(<QueuedNotice active />);
    act(() => vi.advanceTimersByTime(6_000));
    expect(screen.getByRole('status')).toBeInTheDocument();
    rerender(<QueuedNotice active={false} />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    rerender(<QueuedNotice active />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('never shows for a request that finishes quickly', () => {
    const { rerender } = render(<QueuedNotice active />);
    act(() => vi.advanceTimersByTime(2_000));
    rerender(<QueuedNotice active={false} />);
    act(() => vi.advanceTimersByTime(10_000));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
