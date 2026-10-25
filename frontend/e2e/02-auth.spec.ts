import { randomBytes } from 'node:crypto';

import { expect, test } from '@playwright/test';

import { account, uniqueSuffix } from './support';

test.describe('authentication', () => {
  test('register, verify the emailed code and sign in', async ({ page }) => {
    const email = `e2e-public-${uniqueSuffix()}@legalai.test`;
    const password = `E2e-${randomBytes(12).toString('base64url')}`; // generated per run, never stored

    await page.goto('/register');
    await page.getByLabel('Full name').fill('E2E Public User');
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByLabel('Confirm password').fill(password);
    const registered = page.waitForResponse((r) => r.url().endsWith('/auth/register'));
    await page.getByRole('button', { name: 'Create public account' }).click();

    // APP_ENV=test with EXPOSE_DEV_VERIFICATION_TOKENS: the API returns the code it "emailed".
    const body = (await (await registered).json()) as { dev_verification_otp?: string };
    expect(body.dev_verification_otp).toMatch(/^\d{6}$/);
    await expect(page).toHaveURL(/\/verify-email\?/);
    await page.getByLabel('Verification code').fill(body.dev_verification_otp!);
    await page.getByRole('button', { name: 'Verify email' }).click();
    await expect(page).toHaveURL(/\/login/);

    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    // A verified public account goes to the lawyer-verification application.
    await expect(page).toHaveURL('/lawyer/apply');
  });

  test('a wrong password shows the generic sign-in error', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill(account('lawyer').email);
    await page.getByLabel('Password').fill('definitely-not-the-password');
    await page.getByRole('button', { name: 'Sign in' }).click();

    // Next.js also renders an empty role="alert" route announcer, so match the form's alert by its text.
    const alert = page.getByRole('alert').filter({ hasText: 'We could not sign you in' });
    await expect(alert).toContainText('Sign-in failed');
    await expect(alert).toContainText(
      'We could not sign you in. Check your details and try again.',
    );
    // The same message for every failure: nothing says whether the email exists.
    await expect(alert).not.toContainText(/password is wrong|no account|not found/i);
    await expect(page).toHaveURL(/\/login/);
  });
});
