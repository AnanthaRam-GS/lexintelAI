/** True in `next build` / `next start` output, where the development-only preview must not exist (SEC-009). */
export function isPreviewDisabled(nodeEnv: string | undefined = process.env.NODE_ENV): boolean {
  return nodeEnv === 'production';
}
