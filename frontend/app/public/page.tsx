import type { Metadata } from 'next';

import { PublicLanding } from './PublicLanding';

export const metadata: Metadata = {
  title: 'LegalAI',
  description:
    'Ask in your own words or share one PDF. We explain the information clearly and suggest practical next steps.',
};

export default function PublicPage() {
  return <PublicLanding />;
}
