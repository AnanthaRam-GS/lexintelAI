import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, type Page } from '@playwright/test';

/** The run's state directory, prepared by backend/scripts/e2e/setup_e2e.py. */
function stateDir(): string {
  const dir = process.env.LEGALAI_E2E_STATE_DIR;
  if (!dir)
    throw new Error('LEGALAI_E2E_STATE_DIR is not set; run the journeys through run_e2e.sh');
  return dir;
}

interface Account {
  email: string;
  password: string;
}

/** Test accounts created for this run, with passwords generated at setup (never committed or logged). */
export function account(role: 'admin' | 'lawyer'): Account {
  const accounts = JSON.parse(
    readFileSync(path.join(stateDir(), 'accounts.json'), 'utf-8'),
  ) as Record<string, Account>;
  return accounts[role];
}

/** A synthetic upload fixture rendered for this run (fir_synthetic.pdf, ingest_judgment_synthetic.pdf). */
export function fixtureFile(name: string): string {
  return path.join(stateDir(), 'files', name);
}

export async function signIn(page: Page, role: 'admin' | 'lawyer', next?: string): Promise<void> {
  const { email, password } = account(role);
  await page.goto(next ? `/login?next=${encodeURIComponent(next)}` : '/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(next ?? (role === 'admin' ? '/admin' : '/professional'));
}

export function uniqueSuffix(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}
