import type { NextConfig } from "next";

/**
 * No telemetry, no external image hosts, no analytics.
 *
 * PART 3 lists third-party analytics SDKs and crash reporters among the
 * deliberate omissions: every one of them would exfiltrate something about a
 * force's welfare posture to somebody outside the data centre. The absence is
 * the feature.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  /**
   * A verification build must not clobber a running server.
   *
   * `next build` and `next dev` share `.next` by default, so running the build
   * to check a change wipes the assets the running server is still serving. The
   * page then renders with its HTML intact and its stylesheet 404 — which looks
   * exactly like a design failure and is not one. It happened twice here before
   * being diagnosed.
   *
   * `check.sh` sets NEXT_DIST_DIR so its build writes somewhere else entirely.
   */
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  eslint: { dirs: ["app", "components", "lib"] },
  async rewrites() {
    // The console talks to the on-prem API only. The origin is configurable so
    // a deployment can point at its own host without a rebuild.
    const api =
      process.env.NEXT_PUBLIC_API_ORIGIN ??
      `http://127.0.0.1:${process.env.SAMVEDNA_API_PORT ?? "8090"}`;
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
