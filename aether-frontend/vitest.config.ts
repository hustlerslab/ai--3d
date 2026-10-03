import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// tsconfig says `jsx: preserve` because Next compiles JSX itself; vitest has to
// be told to use React's automatic runtime so components can be rendered in
// tests (react-dom/server) without importing React into every file.
export default defineConfig({
  esbuild: { jsx: "automatic" },
  // tsconfig's `@/*` path alias, which Next resolves on its own.
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: { include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
});
