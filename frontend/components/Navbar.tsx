'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Scale } from 'lucide-react';
import type { AuthenticatedUser } from '../lib/types/api';

export interface NavbarProps {
  user?: AuthenticatedUser | null;
  onLogout?: () => Promise<void> | void;
}

const NAV_ITEMS = [
  { label: 'Overview', href: '/professional' },
  { label: 'Text Query', href: '/professional/query' },
  { label: 'Upload Brief', href: '/professional/upload' },
  { label: 'Analytics', href: '/professional/analytics' },
  { label: 'History', href: '/professional/history' },
];

export function Navbar({ user, onLogout }: NavbarProps) {
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  const handleLogoutClick = async () => {
    if (isLoggingOut) return;
    setIsLoggingOut(true);
    try {
      if (onLogout) {
        await onLogout();
      }
    } finally {
      setIsLoggingOut(false);
    }
  };

  return (
    <header className="sticky top-0 z-40 border-b border-[var(--color-border)] bg-[var(--color-surface)] shadow-xs">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
        {/* Brand & Mode Identity */}
        <div className="flex items-center gap-3">
          <Link
            href="/professional"
            className="group flex items-center gap-2.5 focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
          >
            {/* Legal Scales Icon */}
            <div className="flex h-9 w-9 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-ink)] text-[var(--color-brass)] shadow-xs transition-colors group-hover:bg-[var(--color-body)]">
              <Scale className="h-5 w-5" strokeWidth={1.8} aria-hidden="true" />
            </div>
            <div>
              <span className="font-display text-lg font-bold tracking-tight text-[var(--color-ink)]">
                LexIntel AI
              </span>
              <span className="ml-2 hidden rounded-sm bg-[var(--color-surface-subtle)] px-2 py-0.5 text-[0.6875rem] font-semibold uppercase tracking-wider text-[var(--color-brass)] sm:inline-block">
                Professional Mode
              </span>
            </div>
          </Link>
        </div>

        {/* Desktop Navigation Links */}
        <nav
          className="hidden md:flex md:items-center md:gap-1"
          role="navigation"
          aria-label="Professional Mode Navigation"
        >
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.href === '/professional'
                ? pathname === '/professional'
                : pathname.startsWith(item.href);

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-[var(--radius-compact)] px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-[var(--color-focus)] ${
                  isActive
                    ? 'bg-[var(--color-ink)] text-white shadow-xs'
                    : 'text-[var(--color-body)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]'
                }`}
                aria-current={isActive ? 'page' : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Right Area: User Profile & Logout */}
        <div className="hidden items-center gap-3 md:flex">
          {user ? (
            <div className="flex items-center gap-2.5 border-l border-[var(--color-border)] pl-3 text-xs">
              <div className="text-right">
                <p className="max-w-[140px] truncate font-medium text-[var(--color-ink)]" title={user.email}>
                  {user.email}
                </p>
                <span className="inline-block rounded-xs bg-[var(--color-brass)]/15 px-1.5 py-0.2 font-semibold uppercase text-[var(--color-brass-hover)]">
                  {user.role}
                </span>
              </div>
              <button
                type="button"
                onClick={handleLogoutClick}
                disabled={isLoggingOut}
                className="cursor-pointer rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1 text-xs font-semibold text-[var(--color-body)] transition-colors hover:border-[var(--color-error-border)] hover:bg-[var(--color-error-surface)] hover:text-[var(--color-error-foreground)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)] disabled:opacity-50"
              >
                {isLoggingOut ? 'Signing out...' : 'Sign out'}
              </button>
            </div>
          ) : null}
        </div>

        {/* Mobile Hamburger Button */}
        <div className="flex items-center md:hidden">
          <button
            type="button"
            onClick={() => setMobileMenuOpen((prev) => !prev)}
            aria-expanded={mobileMenuOpen}
            aria-label="Toggle navigation menu"
            className="rounded-[var(--radius-compact)] p-2 text-[var(--color-ink)] hover:bg-[var(--color-surface-subtle)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
          >
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {mobileMenuOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              )}
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="border-t border-[var(--color-border)] bg-[var(--color-surface)] px-4 pt-2 pb-4 md:hidden">
          <div className="flex flex-col gap-1">
            {NAV_ITEMS.map((item) => {
              const isActive =
                item.href === '/professional'
                  ? pathname === '/professional'
                  : pathname.startsWith(item.href);

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMobileMenuOpen(false)}
                  className={`rounded-[var(--radius-compact)] px-3 py-2 text-sm font-medium ${
                    isActive
                      ? 'bg-[var(--color-ink)] text-white'
                      : 'text-[var(--color-body)] hover:bg-[var(--color-surface-subtle)]'
                  }`}
                  aria-current={isActive ? 'page' : undefined}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>

          {user && (
            <div className="mt-4 border-t border-[var(--color-border)] pt-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-[var(--color-ink)]">{user.email}</p>
                  <span className="text-[0.6875rem] font-bold uppercase text-[var(--color-brass)]">
                    Role: {user.role}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={handleLogoutClick}
                  disabled={isLoggingOut}
                  className="rounded-[var(--radius-compact)] border border-[var(--color-border)] px-3 py-1.5 text-xs font-semibold text-[var(--color-error-foreground)] hover:bg-[var(--color-error-surface)]"
                >
                  {isLoggingOut ? 'Signing out...' : 'Sign out'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </header>
  );
}
