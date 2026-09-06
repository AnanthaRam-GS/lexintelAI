import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{js,ts,jsx,tsx,mdx}', './components/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      borderColor: {
        default: 'var(--color-border)',
      },
      borderRadius: {
        compact: 'var(--radius-compact)',
        standard: 'var(--radius-standard)',
      },
      borderWidth: {
        hairline: 'var(--border-hairline)',
      },
      boxShadow: {
        component: 'var(--shadow-component)',
        overlay: 'var(--shadow-overlay)',
      },
      colors: {
        canvas: 'var(--color-canvas)',
        surface: {
          DEFAULT: 'var(--color-surface)',
          raised: 'var(--color-surface-raised)',
          subtle: 'var(--color-surface-subtle)',
        },
        ink: 'var(--color-ink)',
        body: 'var(--color-body)',
        muted: 'var(--color-muted)',
        inverse: 'var(--color-inverse)',
        brass: {
          DEFAULT: 'var(--color-brass)',
          hover: 'var(--color-brass-hover)',
          active: 'var(--color-brass-active)',
        },
        focus: 'var(--color-focus)',
        success: {
          DEFAULT: 'var(--color-success)',
          foreground: 'var(--color-success-foreground)',
          surface: 'var(--color-success-surface)',
          border: 'var(--color-success-border)',
        },
        warning: {
          DEFAULT: 'var(--color-warning)',
          foreground: 'var(--color-warning-foreground)',
          surface: 'var(--color-warning-surface)',
          border: 'var(--color-warning-border)',
        },
        error: {
          DEFAULT: 'var(--color-error)',
          foreground: 'var(--color-error-foreground)',
          surface: 'var(--color-error-surface)',
          border: 'var(--color-error-border)',
        },
        info: {
          DEFAULT: 'var(--color-info)',
          foreground: 'var(--color-info-foreground)',
          surface: 'var(--color-info-surface)',
          border: 'var(--color-info-border)',
        },
      },
      fontFamily: {
        display: ['var(--font-display)'],
        ui: ['var(--font-ui)'],
      },
      transitionDuration: {
        fast: 'var(--motion-fast)',
        standard: 'var(--motion-standard)',
      },
      transitionTimingFunction: {
        standard: 'var(--motion-ease)',
      },
    },
  },
};

export default config;
