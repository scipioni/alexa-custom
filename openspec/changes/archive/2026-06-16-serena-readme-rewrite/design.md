## Context

The project currently has a single `README.md` (353 lines) that serves as both marketing material and technical reference. This mixed purpose makes it:

- **Hard to scan** — opens with prerequisites and dense config blocks before telling you what the project does
- **Hard to navigate** — everything is in one file with minimal hierarchy
- **Uninspiring** — no features section, no architecture diagram, no screenshots, no personality

The goal is to split this into two files with distinct roles and audiences:

| File | Role | Audience | Voice |
|------|------|----------|-------|
| `README.md` | Product page | Newcomers, GitHub browsers | Polished, benefit-driven, excitable |
| `details.md` | Technical reference | Developers setting up/integrating | Precise, thorough, reference-style |

The brand name "Serena" is introduced in the README only — no code, package, or CLI renames.

## Goals / Non-Goals

**Goals:**
- Rewrite `README.md` as a ~150-line captivating product page with the Serena brand
- Create `details.md` as a companion technical reference inheriting all detail from the current README
- Preserve all technical accuracy — no information lost, just better organized
- Add architecture diagram, feature grid, dashboard description, and quick start
- Keep existing `docs/` directory untouched (linked from both files)

**Non-Goals:**
- No code, config, CLI, or package renames
- No changes to build system, tests, or CI
- No new screenshots or media assets (placeholder added for future)
- No changes to `docs/` content

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **File split** | README.md + details.md | Single technical reference file is simpler than many focused docs; keeps navigation easy |
| **Brand scope** | Documentation-only | Avoiding code rename reduces risk and keeps this a pure documentation change |
| **Logo** | Use existing `docs/logo_alexa.png` | Already available; new branding assets can be a follow-up |
| **Badges** | shields.io inline | Standard practice, no external deps rendered at build time |
| **details.md format** | Sections with `##` headings, numbered in TOC | Same format as current README, familiar to contributors |
| **Config examples** | README: 1 minimal snippet; details.md: full reference | README shows "what it looks like", details.md documents every field |
| **Audio workarounds** | details.md only | Too much detail for a product page; keep in technical reference |
| **Architecture diagram** | ASCII art in README | Renders in any Markdown viewer, no external image hosting |

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **Information loss** — something from current README not carried over | Cross-reference both files against current README line by line before finalizing |
| **Broken links** — external repos or docs linking to old README anchors | Keep `details.md` as a superset; use same section heading text where possible |
| **README too light** — users can't find what they need without scrolling to details.md | The "balanced" approach (~150 lines) includes enough to get started independently |
| **Brand confusion** — "Serena" in README, "alexa-custom" everywhere else | Make the distinction clear in the README: "Serena (package: alexa-custom)" |
