import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tsconfigPaths()],

  /**
   * Override PostCSS with an empty plugin set.
   *
   * Tailwind v4 declares its plugin as the string `"@tailwindcss/postcss"`, which
   * Next.js resolves but Vite's PostCSS loader rejects. Tests assert on behaviour
   * and never on computed styles, so processing CSS here would be cost without
   * benefit — and this stops Vite reading postcss.config.mjs at all.
   */
  css: {
    postcss: { plugins: [] },
  },

  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // Server-only modules (Better Auth config, the pg pool) are excluded: they
    // open real connections on import and are covered by the backend integration
    // suite instead.
    include: ["tests/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.d.ts",
        // Server-side modules; not exercised by jsdom tests.
        "src/lib/auth/server.ts",
        "src/lib/auth/db.ts",
        "src/app/**/layout.tsx",
        "src/app/api/**",
      ],
    },
  },
});
