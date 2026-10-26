import type { Metadata } from 'next';

import './fonts';
import './globals.css';

export const metadata: Metadata = {
  title: 'LegalAI',
  description: 'Legal intelligence, clearly presented.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
