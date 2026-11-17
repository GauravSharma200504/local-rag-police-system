/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { 950: "#070e1f", 900: "#0b1530", 800: "#12204a", 700: "#1a2d63", 600: "#25407f", 100: "#e6ebf5", 50: "#f3f6fb" },
      },
      fontFamily: { sans: ["Inter", "Segoe UI", "system-ui", "-apple-system", "Roboto", "Noto Sans", "Noto Sans Devanagari", "sans-serif"] },
    },
  },
  plugins: [],
};
