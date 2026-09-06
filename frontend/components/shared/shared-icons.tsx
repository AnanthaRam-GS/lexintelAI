import { AlertTriangle, RotateCcw, type LucideProps } from 'lucide-react';

type SharedIconProps = Omit<LucideProps, 'aria-hidden' | 'focusable'>;

export function ErrorIcon(props: SharedIconProps) {
  return <AlertTriangle aria-hidden="true" focusable="false" {...props} />;
}

export function RetryIcon(props: SharedIconProps) {
  return <RotateCcw aria-hidden="true" focusable="false" {...props} />;
}
