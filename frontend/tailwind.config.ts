import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Carried over from the thesis build's Streamlit theme for brand
        // continuity (primary #2563EB on near-white).
        brand: {
          DEFAULT: "#2563EB",
          soft: "#EBF1FE",
          ink: "#1C1E21",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
