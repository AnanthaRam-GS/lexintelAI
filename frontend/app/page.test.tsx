import { describe, expect, it, vi } from 'vitest';

const { redirect } = vi.hoisted(() => ({
  redirect: vi.fn(),
}));

vi.mock('next/navigation', () => ({ redirect }));

describe('Home', () => {
  it('opens the login onboarding entry instead of the component preview', async () => {
    const { default: Home } = await import('./page');

    Home();

    expect(redirect).toHaveBeenCalledWith('/login');
    expect(redirect).not.toHaveBeenCalledWith('/dev/component-preview');
  });
});
