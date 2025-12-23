import type { Config } from "tailwindcss"

// Tailwind v4 + Tremor:
// Tremor charts generate Tailwind class names inside node_modules (e.g. fill-blue-500).
// We must include Tremor dist files in Tailwind content so those utility classes get generated.
const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "./node_modules/@tremor/react/dist/**/*.{js,cjs}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}

export default config

