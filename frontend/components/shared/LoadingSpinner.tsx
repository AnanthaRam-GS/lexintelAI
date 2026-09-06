export interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  label?: string;
  fullScreen?: boolean;
}

const spinnerSizes = {
  sm: 'h-4 w-4 border-2',
  md: 'h-6 w-6 border-2',
  lg: 'h-8 w-8 border-[3px]',
} as const;

export function LoadingSpinner({
  size = 'md',
  label = 'Loading',
  fullScreen = false,
}: LoadingSpinnerProps) {
  return (
    <div
      aria-label={label}
      aria-live="polite"
      className={
        fullScreen
          ? 'fixed inset-0 z-50 flex items-center justify-center bg-[var(--color-canvas)]/90'
          : 'inline-flex items-center justify-center'
      }
      data-full-screen={fullScreen}
      data-size={size}
      role="status"
    >
      <span
        aria-hidden="true"
        className={`block rounded-full border-[var(--color-surface-subtle)] border-r-[var(--color-brass)] animate-spin motion-reduce:animate-none ${spinnerSizes[size]}`}
      />
    </div>
  );
}
