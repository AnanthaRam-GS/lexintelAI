import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

const router = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => router,
}));

import { PublicLanding } from './PublicLanding';
import { PublicSessionProvider, usePublicSession } from './PublicSessionProvider';

function PendingInputStatus() {
  const { pendingInput } = usePublicSession();

  return (
    <output>
      {pendingInput?.kind === 'text'
        ? `text:${pendingInput.content}`
        : pendingInput?.kind === 'file'
          ? `file:${pendingInput.file.name}`
          : 'none'}
    </output>
  );
}

function renderLanding() {
  return render(
    <PublicSessionProvider>
      <PublicLanding />
      <PendingInputStatus />
    </PublicSessionProvider>,
  );
}

describe('PublicLanding', () => {
  afterEach(() => {
    cleanup();
    router.push.mockReset();
  });

  it('presents the approved plain-language landing content without professional navigation', () => {
    renderLanding();

    expect(
      screen.getByRole('heading', {
        name: 'Understand your legal question without the legal jargon.',
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'Ask in your own words or share one PDF. We explain the information clearly and suggest practical next steps.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText('My landlord has not returned my deposit. What can I do?'),
    ).toBeVisible();
    expect(screen.getByText('Can my employer withhold my final salary?')).toBeVisible();
    expect(screen.getByText('What should I do after receiving a court notice?')).toBeVisible();
    expect(
      screen.getByText(
        'This service gives general information, not personal legal advice. A PDF is checked once for your question and is not stored or added to a shared collection.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /log in|professional/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /log in|professional/i })).not.toBeInTheDocument();
  });

  it('hands a non-empty text question to the ask route without placing it in the URL', async () => {
    const user = userEvent.setup();
    renderLanding();

    await user.type(screen.getByLabelText('Your question'), 'Can my employer keep my pay?');
    await user.click(screen.getByRole('button', { name: 'Ask your question' }));

    expect(screen.getByText('text:Can my employer keep my pay?')).toBeInTheDocument();
    expect(router.push).toHaveBeenCalledWith('/public/ask');
  });

  it('submits a trimmed question once on plain Enter without inserting a newline', async () => {
    const user = userEvent.setup();
    renderLanding();

    const question = screen.getByLabelText('Your question');
    await user.type(question, '  Can my employer keep my pay?  {Enter}');

    expect(question).toHaveValue('  Can my employer keep my pay?  ');
    expect(screen.getByText('text:Can my employer keep my pay?')).toBeInTheDocument();
    expect(router.push).toHaveBeenCalledTimes(1);
    expect(router.push).toHaveBeenCalledWith('/public/ask');

    const destination = new URL(router.push.mock.calls[0][0], 'https://legalai.test');
    expect(destination.pathname).toBe('/public/ask');
    expect(destination.search).toBe('');
    expect(destination.hash).toBe('');
  });

  it('keeps Shift+Enter as a multiline gesture without handing off', async () => {
    const user = userEvent.setup();
    renderLanding();

    const question = screen.getByLabelText('Your question');
    await user.type(question, 'First line{Shift>}{Enter}{/Shift}Second line');

    expect(question).toHaveValue('First line\nSecond line');
    expect(screen.getByText('none')).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it('does not hand off a whitespace-only question on plain Enter', async () => {
    const user = userEvent.setup();
    renderLanding();

    const question = screen.getByLabelText('Your question');
    await user.type(question, '   {Enter}');

    expect(question).toHaveValue('   ');
    expect(screen.getByText('none')).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it('does not hand off Enter while an IME composition is active', async () => {
    const user = userEvent.setup();
    renderLanding();

    const question = screen.getByLabelText('Your question');
    await user.type(question, 'Composed question');
    fireEvent.compositionStart(question);
    fireEvent.keyDown(question, { key: 'Enter', isComposing: true });
    fireEvent.compositionEnd(question);

    expect(question).toHaveValue('Composed question');
    expect(screen.getByText('none')).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it('keeps the question composer keyboard-focusable with the Phase 1 visible-focus treatment', async () => {
    const user = userEvent.setup();
    renderLanding();

    await user.tab();
    await user.tab();
    await user.tab();

    const question = screen.getByLabelText('Your question');
    expect(question).toHaveFocus();
    expect(question).toHaveClass(
      'focus-visible:outline-[0.1875rem]',
      'focus-visible:outline-[var(--color-focus)]',
      'focus-visible:outline-offset-[0.1875rem]',
    );
  });

  it('connects the PDF disclosure control to its revealed upload region', async () => {
    const user = userEvent.setup();
    renderLanding();

    const uploadButton = screen.getByRole('button', { name: 'Upload one PDF' });
    expect(uploadButton).toHaveAttribute('aria-expanded', 'false');
    expect(uploadButton).toHaveAttribute('aria-controls', 'public-pdf-upload');
    expect(document.getElementById('public-pdf-upload')).not.toBeInTheDocument();

    await user.click(uploadButton);

    expect(uploadButton).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById('public-pdf-upload')).toContainElement(
      screen.getByRole('region', { name: 'PDF file upload' }),
    );
  });

  it('reveals a single-PDF upload and hands a valid selected file to the ask route', async () => {
    const user = userEvent.setup();
    const file = new File(['pdf'], 'notice.pdf', { type: 'application/pdf' });
    renderLanding();

    expect(screen.queryByLabelText('Choose PDF files')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Upload one PDF' }));
    const fileInput = screen.getByLabelText('Choose PDF files') as HTMLInputElement;

    expect(fileInput).toHaveAttribute('accept', 'application/pdf');
    expect(fileInput.multiple).toBe(false);

    await user.upload(fileInput, file);

    expect(screen.getByText('file:notice.pdf')).toBeInTheDocument();
    expect(router.push).toHaveBeenCalledWith('/public/ask');
  });
});
