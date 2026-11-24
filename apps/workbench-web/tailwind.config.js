/** Design tokens are CSS variables (src/styles/tokens.css) so light and dark themes share one scale. */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"], mono: ["JetBrains Mono", "ui-monospace", "monospace"] },
      colors: {
        bg: "rgb(var(--bg) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        border: "rgb(var(--border) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        subtle: "rgb(var(--subtle) / <alpha-value>)",
        brand: { DEFAULT: "rgb(var(--brand) / <alpha-value>)", fg: "rgb(var(--brand-fg) / <alpha-value>)", soft: "rgb(var(--brand-soft) / <alpha-value>)" },
        ok: "rgb(var(--ok) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        info: "rgb(var(--info) / <alpha-value>)",
      },
      borderRadius: { xl: "var(--radius-lg)", lg: "var(--radius)", md: "var(--radius-sm)" },
      spacing: { 18: "4.5rem" },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        pulseRing: { "0%": { boxShadow: "0 0 0 0 rgb(var(--brand) / .45)" }, "100%": { boxShadow: "0 0 0 10px rgb(var(--brand) / 0)" } },
      },
      animation: { shimmer: "shimmer 1.4s infinite", pulseRing: "pulseRing 1.2s ease-out 2" },
    },
  },
  plugins: [],
};
