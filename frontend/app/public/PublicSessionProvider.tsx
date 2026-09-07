'use client';

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';

import type { PublicQueryInput } from './query-client';

export interface PublicSessionValue {
  pendingInput: PublicQueryInput | null;
  setPendingInput: (input: PublicQueryInput) => void;
  takePendingInput: () => PublicQueryInput | null;
}

const PublicSessionContext = createContext<PublicSessionValue | null>(null);

export function PublicSessionProvider({ children }: PropsWithChildren) {
  const [pendingInput, setPendingInput] = useState<PublicQueryInput | null>(null);
  const pendingInputRef = useRef<PublicQueryInput | null>(null);

  const storePendingInput = useCallback((input: PublicQueryInput) => {
    pendingInputRef.current = input;
    setPendingInput(input);
  }, []);

  const takePendingInput = useCallback(() => {
    const input = pendingInputRef.current;

    pendingInputRef.current = null;
    setPendingInput(null);

    return input;
  }, []);

  return (
    <PublicSessionContext.Provider
      value={{ pendingInput, setPendingInput: storePendingInput, takePendingInput }}
    >
      {children}
    </PublicSessionContext.Provider>
  );
}

export function usePublicSession() {
  const session = useContext(PublicSessionContext);

  if (session === null) {
    throw new Error('usePublicSession must be used within PublicSessionProvider.');
  }

  return session;
}
