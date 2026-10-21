import { afterEach, describe, expect, it, vi } from 'vitest';

const { notFound } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error('NEXT_HTTP_ERROR_FALLBACK;404');
  }),
}));

vi.mock('next/navigation', () => ({ notFound }));
vi.mock('./PreviewGallery', () => ({ PreviewGallery: () => null }));

import ComponentPreviewPage from './page';
import { isPreviewDisabled } from './preview-access';

describe('dev component preview (SEC-009)', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    notFound.mockClear();
  });

  it('is disabled only in production builds', () => {
    expect(isPreviewDisabled('production')).toBe(true);
    expect(isPreviewDisabled('development')).toBe(false);
    expect(isPreviewDisabled('test')).toBe(false);
  });

  it('renders a 404 in production', () => {
    vi.stubEnv('NODE_ENV', 'production');
    expect(() => ComponentPreviewPage()).toThrow('NEXT_HTTP_ERROR_FALLBACK;404');
    expect(notFound).toHaveBeenCalledOnce();
  });

  it('renders the gallery in development', () => {
    vi.stubEnv('NODE_ENV', 'development');
    expect(() => ComponentPreviewPage()).not.toThrow();
    expect(notFound).not.toHaveBeenCalled();
  });
});
