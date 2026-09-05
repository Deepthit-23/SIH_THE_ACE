/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Restrained governance-tool palette.
        ink: "#1f2933",
        slatebg: "#f5f7fa",
      },
    },
  },
  plugins: [],
};
