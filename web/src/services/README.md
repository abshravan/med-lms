# `src/services`

**Cross-cutting client-side services** — stateful or side-effecting modules shared
by several features, such as an analytics client, a WebSocket connection manager,
or a file-upload orchestrator.

This is deliberately *not* where HTTP calls live:

| Concern | Location |
| --- | --- |
| Transport (auth headers, retry, envelope unwrapping) | `src/lib/api/client.ts` |
| Per-feature endpoint calls | `src/features/<feature>/api/` |
| Server state, caching, invalidation | `src/features/<feature>/hooks/` (TanStack Query) |

Currently empty. The first real occupants will arrive with the realtime voice
viva (a WebSocket session manager) and media upload.
