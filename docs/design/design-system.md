# Design System — ABackup

**Date**: 2026-07-13
**Framework**: [Textual](https://textual.textualize.io/) (TUI). No external theme; relies on Textual defaults + a few CSS variables and inline styles.

## 1. Layout Primitives

| Token | Usage | Example |
|-------|-------|---------|
| `Screen` | Full-viewport container; `align: center top; padding: 1` | [`app.py`](../../src/abackup/tui/app.py:15) |
| `#body` | Scrollable content region | [`settings.py`](../../src/abackup/tui/screens/settings.py:19) |
| `.field` | Vertical form row (label + control + hint) | [`settings.py`](../../src/abackup/tui/screens/settings.py:19) |
| `.field-label` | Bold label above a control | [`settings.py`](../../src/abackup/tui/screens/settings.py:19) |
| `.field-hint` | Muted helper text below a control | [`settings.py`](../../src/abackup/tui/screens/settings.py:19) |

## 2. Color Roles (Textual CSS variables)

| Role | Used for | Notes |
|------|----------|-------|
| `$primary` | Primary action buttons (Run, Save) | Textual default |
| `$success` | Success / completed status | Textual default |
| `$error` | Error messages, failed status | [`app.py`](../../src/abackup/tui/app.py:15) |
| `$text-muted` | Hints, secondary labels | [`app.py`](../../src/abackup/tui/app.py:15) |
| `$surface` | Panel backgrounds | Textual default |

> No custom palette is defined; the app inherits the active Textual theme (dark by default). A light/dark toggle is a backlog item (NTH-001).

## 3. Typography & Spacing

- **Title**: bold, centered, `Header`/large `Label` ([`app.py`](../../src/abackup/tui/app.py:15)).
- **Body**: default monospace terminal font (Textual default).
- **Spacing**: `padding: 1` on screens; `1 2` (vertical/horizontal) on `.field` rows; `1` gap between fields.
- **Alignment**: forms centered horizontally, top-aligned vertically.

## 4. Component States

| Component | States | Styling |
|-----------|---------|----------|
| `Button` | default / primary / success / error | variant param; primary=blue, success=green, error=red |
| `Input` | focused / invalid | border highlight on focus; red border + `$error` text on invalid |
| `ProgressBar` | 0% / active / 100% / cancelled | fill color follows status; cancelled shown in `$error` |
| `ListItem` (job list) | normal / selected | default Textual highlight; no custom selected style yet (NTH-002) |
| `RadioButton` / `Checkbox` | checked / unchecked | Textual default |

## 5. Accessibility

- **Keyboard**: `q` bound to quit at app level ([`app.py`](../../src/abackup/tui/app.py:22)); Textual provides arrow/tab navigation and ARIA-like semantics by default.
- **Focus order**: follows widget declaration order; no custom focus management.
- **Contrast**: relies on Textual's default dark theme (high contrast). No custom low-contrast combinations.
- **Improvements (backlog)**: visible selection styling for the job `ListView` (NTH-002); a one-line key-help footer.

## 6. Motion & Feedback

- **Progress**: smooth byte-level `ProgressBar` updates via `call_from_thread` marshalling ([`run_all.py`](../../src/abackup/tui/screens/run_all.py:86)) — no animation library, just frequent value updates.
- **Status**: `RichLog` appends per-file/per-job lines during a run; final status shown as a colored `Label` (success/error/cancelled).
- **No transitions/transitions library** — TUI is event-driven; updates are immediate.

## 7. Consistency Notes

- All screens share the same `align: center top; padding: 1` root and the `$error`/`$text-muted` roles.
- Settings screen is the most styled (`.field*` classes); other screens use mostly default widgets — a small, consistent form pattern could be extracted (low priority).
