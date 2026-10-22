import type { Metadata } from 'next';
import { Suspense } from 'react';

import { AuthProvider } from '../../lib/auth/AuthContext';
import { LoginForm } from './LoginForm';

export const metadata: Metadata = {
  title: 'Sign in | LegalAI',
  description: 'Sign in to a protected LegalAI workspace.',
};

export default function LoginPage() {
  return (
    <AuthProvider>
      {/* useSearchParams() needs a Suspense boundary for the page to prerender in `next build`. */}
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthProvider>
  );
}
