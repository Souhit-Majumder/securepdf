/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        glass: {
          surface: "rgba(15, 23, 42, 0.65)",
          border: "rgba(255, 255, 255, 0.12)",
          highlight: "rgba(255, 255, 255, 0.05)",
          glow: "rgba(56, 189, 248, 0.15)",
        },
      },
    },
  },
  plugins: [],
};
