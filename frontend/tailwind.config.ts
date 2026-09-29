import type { Config } from "tailwindcss";

/**
 * A deliberately small token set. One accent colour, a few surfaces, and
 * restrained motion -- the generated model is meant to be the visual hero,
 * not the chrome around it.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#0B0F17",
        surface: "#111827",
        "surface-raised": "#151D2C",
        hairline: "rgba(148, 163, 184, 0.12)",
        "hairline-strong": "rgba(148, 163, 184, 0.22)",
        accent: {
          DEFAULT: "#6366F1",
          hover: "#4F46E5",
          muted: "rgba(99, 102, 241, 0.12)",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        // Depth from a soft lift, not a glow.
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 12px 32px -12px rgba(0,0,0,0.7)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fade-up 320ms cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fade-in 220ms ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
