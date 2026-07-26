import type { NextConfig } from "next";

/**
 * Security headers applied to every response.
 *
 * A Content-Security-Policy is deliberately *not* set here: Next.js injects
 * inline bootstrap scripts, so a correct CSP needs per-request nonces threaded
 * through middleware. Shipping a broken or `unsafe-inline` policy would be worse
 * than none, because it looks like protection without providing any. Tracked as
 * follow-up work in docs/features/authentication.md.
 */
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
  {
    key: "Permissions-Policy",
    // Microphone is intentionally left unrestricted at this level because the
    // voice-viva feature will need it; it is gated per-route instead.
    value: "camera=(), geolocation=(), payment=()",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // `standalone` produces a minimal server bundle for the production Docker
  // image — a much smaller final layer than copying node_modules.
  output: "standalone",

  // `pg` is a native-ish Node driver used only by Better Auth on the server. It
  // must never be bundled into a client or edge chunk.
  serverExternalPackages: ["pg"],

  typescript: {
    // Never ship a build that does not typecheck.
    ignoreBuildErrors: false,
  },
  eslint: {
    ignoreDuringBuilds: false,
  },

  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
