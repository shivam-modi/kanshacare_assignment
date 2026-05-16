import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Severity palette — used consistently across map markers, badges, table rows.
        sev: {
          mute: '#475569',
          low: '#10b981',
          moderate: '#f59e0b',
          elevated: '#f97316',
          high: '#ef4444',
          tsunami: '#7c3aed',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};

export default config;
