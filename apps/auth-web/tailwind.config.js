/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"] },
      colors: {
        brand: { 50: "#eef3ff", 100: "#dce6ff", 400: "#6f93ff", 500: "#4f7cff", 600: "#3a63e6", 700: "#2c4db8", 900: "#16255c" },
        ink: { 900: "#0b1020", 800: "#121a33", 700: "#1c2747", 400: "#8a95b5", 200: "#d6dbea" },
      },
      keyframes: {
        mesh: { "0%,100%": { transform: "translate(0,0) scale(1)" }, "50%": { transform: "translate(4%,-3%) scale(1.08)" } },
        shake: { "0%,100%": { transform: "translateX(0)" }, "25%": { transform: "translateX(-6px)" }, "75%": { transform: "translateX(6px)" } },
      },
      animation: { mesh: "mesh 18s ease-in-out infinite", "mesh-slow": "mesh 26s ease-in-out infinite reverse", shake: "shake .3s" },
    },
  },
  plugins: [],
};
