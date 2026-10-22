import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { PreviewGallery } from './PreviewGallery';
import { isPreviewDisabled } from './preview-access';

// In production the route is a 404, so it must not advertise the preview either.
export const metadata: Metadata = isPreviewDisabled()
  ? {}
  : { title: 'Component Library | LegalAI' };

export default function ComponentPreviewPage() {
  if (isPreviewDisabled()) {
    notFound();
  }
  return <PreviewGallery />;
}
