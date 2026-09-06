import type { Metadata } from 'next';
import { IBM_Plex_Sans, Libre_Baskerville } from 'next/font/google';

import './globals.css';

const displayFont = Libre_Baskerville({
  subsets: ['latin'],
  variable: '--font-display',
  weight: ['400', '700'],
});

const uiFont = IBM_Plex_Sans({
  subsets: ['latin'],
  variable: '--font-ui',
  weight: ['400', '500', '600', '700'],
});

export const metadata: Metadata = {
  title: 'LegalAI',
  description: 'Legal intelligence, clearly presented.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${displayFont.variable} ${uiFont.variable}`}>
      <body>{children}</body>
    </html>
  );
}
