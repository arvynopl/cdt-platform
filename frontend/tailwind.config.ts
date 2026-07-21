import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "var(--font-sans)",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
      },
      colors: {
        // Semantic, theme-aware tokens (values in app/globals.css). Using the
        // rgb(var / <alpha-value>) form keeps opacity modifiers working.
        brand: {
          DEFAULT: "rgb(var(--brand) / <alpha-value>)",
          soft: "rgb(var(--brandsoft) / <alpha-value>)",
        },
        page: "rgb(var(--page) / <alpha-value>)",
        card: "rgb(var(--card) / <alpha-value>)",
        panel: "rgb(var(--panel) / <alpha-value>)",
        edge: "rgb(var(--edge) / <alpha-value>)",
        edge2: "rgb(var(--edge2) / <alpha-value>)",
        strong: "rgb(var(--strong) / <alpha-value>)",
        bodytext: "rgb(var(--body) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        // Money semantics — reserved for gain/loss, never UI chrome.
        gain: "rgb(var(--gain) / <alpha-value>)",
        loss: "rgb(var(--loss) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
      },
      borderRadius: {
        // Tighter than Tailwind's defaults for a denser, tool-like feel.
        lg: "0.5rem",
        xl: "0.625rem",
        "2xl": "0.875rem",
      },
    },
  },
  plugins: [],
} satisfies Config;
