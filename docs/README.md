# ABackup — Documentation

**Generated**: 2026-07-13
**Review skill**: `skill-techreview` (adapted from frontend to a Python/Textual codebase)

## Reviews
- [Technical Review](reviews/2026-07-13-technical-review.md) — executive summary, UI architecture, data flows, features, quality assessment, recommendations.
- [Issues & Improvements](reviews/issues-improvements.md) — prioritized tracker (🔴/🟡/🟢) with roadmap phasing.

## Architecture
- [Component Architecture](architecture/component-architecture.md) — layered structure, screen/engine inventory, communication patterns, testing strategy.
- [Data Flow](architecture/data-flow.md) — storage layout, single-job / batch / add-job / settings flows (Mermaid).
- [State Management](architecture/state-management.md) — file-backed JSON state, atomic write contract, locking, determinism.

## Design
- [Design System](design/design-system.md) — layout primitives, color roles, component states, accessibility, motion.

## Features
- [Implemented](features/implemented.md) — shipped features by category with file references.
- [Roadmap](features/roadmap.md) — phased plan (safety → robustness → polish → new capabilities).

## How to read this
1. Start with the [Technical Review](reviews/2026-07-13-technical-review.md) for the big picture.
2. Use [Issues & Improvements](reviews/issues-improvements.md) as the work queue.
3. Dive into [Architecture](architecture/component-architecture.md) for implementation detail.
4. Track delivery via [Roadmap](features/roadmap.md).
