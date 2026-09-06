import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { PreviewGallery } from './PreviewGallery';

describe('PreviewGallery', () => {
  afterEach(cleanup);

  it('uses only the approved copy before the first component section', () => {
    render(<PreviewGallery />);

    const banner = screen.getAllByRole('banner')[0];
    const main = screen.getByRole('main');
    const introduction = main.firstElementChild;
    const aboveFoldCopy = [
      ...Array.from(banner.querySelectorAll('p'), (element) => element.textContent),
      ...Array.from(introduction?.children ?? [], (element) => element.textContent),
    ];

    expect(aboveFoldCopy).toEqual([
      'LegalAI',
      'Indian Criminal Law RAG Assistant',
      'LegalAI Component Library',
      'Shared UX for Public, Professional & Admin modes',
    ]);
  });

  it('provides the approved responsive brand marks as decorative graphics', () => {
    render(<PreviewGallery />);

    const banner = screen.getAllByRole('banner')[0];
    const brandMark = banner.querySelector('[aria-hidden="true"]');

    expect(brandMark).not.toBeNull();
    expect(brandMark?.querySelector('svg.lucide-scale')).not.toBeNull();
    expect(brandMark?.querySelector('svg.lucide-landmark')).not.toBeNull();
  });

  it('demonstrates every shared component in order and switches response mode', async () => {
    const user = userEvent.setup();

    render(<PreviewGallery />);

    expect(
      screen.getByRole('heading', { name: 'LegalAI Component Library', level: 1 }),
    ).toBeInTheDocument();

    const sectionHeadings = Array.from(
      screen
        .getByRole('main')
        .querySelectorAll<HTMLElement>('section[aria-labelledby$="-heading"]'),
      (section) => {
        const headingId = section.getAttribute('aria-labelledby');

        return section.querySelector(`#${headingId}`)?.textContent;
      },
    );

    expect(sectionHeadings).toEqual([
      '1. LoadingSpinner',
      '2. ErrorMessage',
      '3. UploadDropzone',
      '4. IngestionProgress',
      '5. ResponseCard',
    ]);
    expect(screen.getByRole('status', { name: 'Small loading spinner' })).toHaveAttribute(
      'data-size',
      'sm',
    );
    expect(screen.getAllByRole('alert')).toHaveLength(4);
    expect(screen.getByLabelText('Choose PDF files')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Ingestion jobs' })).toBeInTheDocument();
    expect(screen.getByLabelText('Professional legal research response')).toBeInTheDocument();

    const professionalButton = screen.getByRole('button', { name: 'Professional' });
    const publicButton = screen.getByRole('button', { name: 'Public' });

    expect(professionalButton).toHaveAttribute('aria-pressed', 'true');
    expect(publicButton).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getAllByText(/confidence/i)).not.toHaveLength(0);

    await user.click(publicButton);

    expect(professionalButton).toHaveAttribute('aria-pressed', 'false');
    expect(publicButton).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('heading', { name: 'Plain-language answer' })).toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });

  it('accepts a selected PDF in the upload demonstration', async () => {
    const user = userEvent.setup();
    const pdf = new File(['court order'], 'delhi-high-court-order.pdf', {
      type: 'application/pdf',
    });

    render(<PreviewGallery />);

    await user.upload(screen.getByLabelText('Choose PDF files'), pdf);

    expect(screen.getByText('delhi-high-court-order.pdf')).toBeVisible();
    expect(screen.getByText('1 PDF selected for this local preview.')).toBeVisible();
  });

  it('acknowledges Retry in a polite live region', async () => {
    const user = userEvent.setup();

    render(<PreviewGallery />);

    await user.click(screen.getAllByRole('button', { name: 'Retry' })[0]);

    const acknowledgement = screen.getByText('Retry requested for the inline example.');

    expect(acknowledgement).toBeVisible();
    expect(acknowledgement).toHaveAttribute('aria-live', 'polite');
  });

  it('uses native disclosure for safe technical detail', async () => {
    const user = userEvent.setup();

    render(<PreviewGallery />);

    const disclosure = screen.getByText('Technical details');
    const details = disclosure.closest('details');
    const technicalDetail = screen.getByText('Reference service temporarily unavailable.');

    expect(disclosure.tagName).toBe('SUMMARY');
    expect(details).not.toHaveAttribute('open');
    expect(technicalDetail).not.toBeVisible();

    await user.click(disclosure);

    expect(details).toHaveAttribute('open');
    expect(technicalDetail).toBeVisible();
  });

  it('advances progress by replacing data while preserving the job identity', async () => {
    const user = userEvent.setup();

    render(<PreviewGallery />);

    const filename = screen.getByText('Constitution Bench reference.pdf');
    const initialRow = filename.closest('li');

    expect(initialRow).not.toBeNull();
    expect(within(initialRow as HTMLElement).getByText('EXTRACTING')).toBeInTheDocument();
    expect(
      within(initialRow as HTMLElement).getByRole('progressbar', {
        name: 'Constitution Bench reference.pdf progress',
      }),
    ).toHaveAttribute('aria-valuenow', '32');

    await user.click(screen.getByRole('button', { name: 'Advance progress' }));

    const updatedRow = screen.getByText('Constitution Bench reference.pdf').closest('li');

    expect(updatedRow).toBe(initialRow);
    expect(within(updatedRow as HTMLElement).getByText('CHUNKING')).toBeInTheDocument();
    expect(
      within(updatedRow as HTMLElement).getByRole('progressbar', {
        name: 'Constitution Bench reference.pdf progress',
      }),
    ).toHaveAttribute('aria-valuenow', '58');
  });
});
