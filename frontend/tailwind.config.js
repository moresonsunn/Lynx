/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./public/index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "rgba(var(--color-brand-rgb), 0.05)",
          100: "rgba(var(--color-brand-rgb), 0.1)",
          200: "rgba(var(--color-brand-rgb), 0.2)",
          300: "rgba(var(--color-brand-rgb), 0.35)",
          400: "var(--color-brand-400)",
          500: "var(--color-brand-500)",
          600: "var(--color-brand-600)",
          700: "rgba(var(--color-brand-rgb), 0.75)",
          800: "rgba(var(--color-brand-rgb), 0.85)",
          900: "rgba(var(--color-brand-rgb), 0.95)",
        },
        ink: "#0b1020",
      },
      boxShadow: {
        card: "0 10px 30px -12px rgba(0,0,0,0.35)",
      },
      backgroundImage: {
        "hero-gradient": "radial-gradient(1200px 500px at 10% -10%, rgba(58,134,255,0.25), rgba(0,0,0,0)), radial-gradient(800px 400px at 90% -10%, rgba(99,102,241,0.28), rgba(0,0,0,0))",
      }
    },
  },
  plugins: [],
}
