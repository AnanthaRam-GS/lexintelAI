import type { Metadata } from 'next';
import localFont from 'next/font/local';

import './globals.css';

// Self-hosted (OFL 1.1, see app/fonts/README.md): same families, weights, subset and variables as the former
// next/font/google setup, so `next build` needs no network. The fallbacks match what next/font/google chose by
// category (serif: Times New Roman, sans-serif: Arial), so text keeps its size while the fonts load.
const displayFont = localFont({
  src: [
    { path: './fonts/libre-baskerville-latin-400-normal.woff2', weight: '400', style: 'normal' },
    { path: './fonts/libre-baskerville-latin-700-normal.woff2', weight: '700', style: 'normal' },
  ],
  variable: '--font-display',
  display: 'swap',
  adjustFontFallback: 'Times New Roman',
});

const uiFont = localFont({
  src: [
    { path: './fonts/ibm-plex-sans-latin-400-normal.woff2', weight: '400', style: 'normal' },
    { path: './fonts/ibm-plex-sans-latin-500-normal.woff2', weight: '500', style: 'normal' },
    { path: './fonts/ibm-plex-sans-latin-600-normal.woff2', weight: '600', style: 'normal' },
    { path: './fonts/ibm-plex-sans-latin-700-normal.woff2', weight: '700', style: 'normal' },
  ],
  variable: '--font-ui',
  display: 'swap',
  adjustFontFallback: 'Arial',
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
