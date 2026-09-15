import React from 'react';
import type { Metadata } from 'next';
import { AuthenticatedNavbar } from '../../components/auth/AuthenticatedNavbar';
import { ProtectedRoute } from '../../components/auth/ProtectedRoute';
import { AuthProvider } from '../../lib/auth/AuthContext';

export const metadata: Metadata = {
  title: 'Professional Legal Workbench — LegalAI',
  description:
    'AI-assisted statutory interpretation, precedent discovery, and judicial analytics for legal practitioners.',
};

export default function ProfessionalLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <ProtectedRoute allowedRoles={['lawyer', 'admin']}>
        <div className="flex min-h-screen flex-col bg-[var(--color-canvas)] text-[var(--color-body)]">
          <AuthenticatedNavbar />
          <main className="flex-1">
            <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">{children}</div>
          </main>
          <footer className="border-t border-[var(--color-border)] bg-[var(--color-surface)] py-4 text-center text-xs text-[var(--color-muted)]">
            <p>
              LexIntel AI · Confidential &amp; Privileged · For Legal Practitioner Assistance Only
            </p>
          </footer>
        </div>
      </ProtectedRoute>
    </AuthProvider>
  );
}
