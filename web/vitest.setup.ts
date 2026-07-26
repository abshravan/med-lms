import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

/**
 * Public env vars must be present before any module reading `clientEnv` is
 * imported, because that validation runs at module load and throws on a miss.
 */
process.env.NEXT_PUBLIC_API_URL = "http://api.test";
process.env.NEXT_PUBLIC_APP_URL = "http://app.test";

/**
 * `next/navigation` throws outside a Next request context, so the hooks used by
 * the auth forms are stubbed. `replace`/`push` are spies, letting tests assert on
 * post-submit navigation.
 */
export const routerMock = {
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  prefetch: vi.fn(),
};

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
