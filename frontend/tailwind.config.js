/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        glass: {
          surface: "rgba(255, 255, 255, 0.75)",
          border: "rgba(255, 255, 255, 0.85)",
          highlight: "rgba(255, 255, 255, 0.95)",
          glow: "rgba(2, 132, 199, 0.12)",
        },
      },
    },
  },
  plugins: [],
};
