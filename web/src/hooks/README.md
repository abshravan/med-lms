# `src/hooks`

**Cross-cutting** React hooks — ones used by more than one feature.

Feature-specific hooks do **not** belong here. They live beside the feature that
owns them, in `src/features/<feature>/hooks/`, so that deleting a feature deletes
its hooks with it and no orphaned code accumulates.

A hook earns a place in this directory only once a second feature needs it.
Promoting it early creates a shared dependency that nothing shares.

Examples of what would live here: `use-media-query`, `use-debounced-value`,
`use-local-storage`.

Currently empty — Feature 1 (authentication) produced only feature-scoped hooks:

- `src/features/auth/hooks/use-profile.ts`
- `src/features/auth/hooks/use-auth-actions.ts`
