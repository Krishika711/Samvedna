import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  // Generated output is not ours to fix. `next-env.d.ts` carries a
  // triple-slash reference the shared config rejects, and the build
  // directories contain Next's own `validator.ts` — 392 errors of
  // `@ts-ignore` and unused type bindings that belong to the framework's
  // codegen. `.next-check` is the dist dir `check.sh` builds into so that a
  // verification build cannot wipe a running dev server's `.next`; it needs
  // the same exemption as `.next` itself for exactly the same reason.
  {
    ignores: [
      ".next/**",
      ".next-check/**",
      "node_modules/**",
      "next-env.d.ts",
    ],
  },
];

export default config;
