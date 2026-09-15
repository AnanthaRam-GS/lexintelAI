import React from 'react';
import type { Metadata } from 'next';
import { ProtectedRoute } from '../../components/auth/ProtectedRoute';
import { AuthProvider } from '../../lib/auth/AuthContext';

export const metadata: Metadata = {
  title: 'Admin Portal — LegalAI',
  description: 'LegalAI Administrative and Corpus Ingestion Management',
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <ProtectedRoute requiredRole="admin">{children}</ProtectedRoute>
    </AuthProvider>
  );
}
