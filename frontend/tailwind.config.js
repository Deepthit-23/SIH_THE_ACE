/** @type {import('tailwindcss').Config} */
// Token system for the MPLAD audit tool. Everything visual derives from these; raw Tailwind palette
// colours (slate, red, amber, emerald, ...) are not used in the app.
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    // Only the tokens exist: a stray `text-red-600` becomes a build-time no-op instead of a silent off-palette colour.
    colors: {
      transparent: "transparent",
      current: "currentColor",
      ink: { DEFAULT: "#142440", soft: "#4B5872", faint: "#7C8496" }, // text, top bar, primary action; tints of ink
      canvas: "#F2F1EC",                                              // page ground
      surface: "#FFFFFF",                                             // sheets that carry data
      hairline: "#D8D5CC",                                            // every divider and border
      accent: "#9C7A3C",                                              // brass: active-nav rule, focus ring, one login rule
      high: "#A23B3B",                                                // risk tiers: marks first, tints for chip fills
      medium: "#B8862E",                                              // (about 3.2:1 on white: never small text)
      low: "#5F7A5A",
      clear: "#8B8880",
    },
    fontFamily: {
      sans: ['"Public Sans"', "system-ui", "sans-serif"],
      mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],         // scores, hashes, work IDs, money only
    },
    extend: {
      // a bare `border` / `divide-y` is a hairline, never currentColor
      borderColor: { DEFAULT: "#D8D5CC" },
      divideColor: { DEFAULT: "#D8D5CC" },
      borderRadius: { none: "0", sm: "2px", DEFAULT: "2px", md: "2px", lg: "2px" }, // radius is rationed, not a default
    },
  },
  plugins: [],
};
