import type { Metadata } from 'next';

import { PublicAsk } from './PublicAsk';

export const metadata: Metadata = {
  title: 'Your conversation | LegalAI',
  description: 'Ask a legal question in your own words or share one temporary PDF.',
};

export default function PublicAskPage() {
  return <PublicAsk />;
}
