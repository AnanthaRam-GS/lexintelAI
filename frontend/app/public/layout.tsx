import { PublicSessionProvider } from './PublicSessionProvider';

export default function PublicLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <PublicSessionProvider>{children}</PublicSessionProvider>;
}
