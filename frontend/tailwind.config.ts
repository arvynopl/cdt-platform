import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Carried over from the thesis build's Streamlit theme for brand
        // continuity (primary #2563EB on near-white).
        brand: {
          DEFAULT: "#2563EB",
          soft: "rgb(var(--brandsoft) / <alpha-value>)",
          ink: "#1C1E21",
        },
        // Semantic, theme-aware tokens (values in app/globals.css). Using the
        // rgb(var / <alpha-value>) form keeps opacity modifiers working.
        page: "rgb(var(--page) / <alpha-value>)",
        card: "rgb(var(--card) / <alpha-value>)",
        panel: "rgb(var(--panel) / <alpha-value>)",
        edge: "rgb(var(--edge) / <alpha-value>)",
        edge2: "rgb(var(--edge2) / <alpha-value>)",
        strong: "rgb(var(--strong) / <alpha-value>)",
        bodytext: "rgb(var(--body) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
      },
    },
  },
  plugins: [],
} satisfies Config;
