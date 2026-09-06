import type { Metadata } from 'next';

import { PreviewGallery } from './PreviewGallery';

export const metadata: Metadata = { title: 'Component Library | LegalAI' };

export default function ComponentPreviewPage() {
  return <PreviewGallery />;
}
