---
name: Apgar
version: alpha
description: Release health for agent traffic. One token set, two themes, dense and flat.
colors:
  light-bg: "#F7F6FA"
  light-surface: "#FFFFFF"
  light-surface-raised: "#F9F8FB"
  light-border: "#E8E4EE"
  light-border-strong: "#D4CEDE"
  light-text: "#1D1728"
  light-text-muted: "#6B6379"
  light-accent: "#5F4FD1"
  light-accent-text: "#FFFFFF"
  light-pass: "#16774B"
  light-pass-bg: "#ECF7F1"
  light-fail: "#B4262C"
  light-fail-bg: "#FDF0F0"
  light-inconclusive: "#8F4C00"
  light-inconclusive-bg: "#FDF4E7"
  light-info: "#1D5EA8"
  light-info-bg: "#EDF4FB"
  light-sidebar: "#211A2E"
  light-sidebar-text: "#C8C0D6"
  light-sidebar-muted: "#8D84A0"
  light-sidebar-active: "#342A47"
  light-sidebar-strong: "#FFFFFF"
  dark-bg: "#121019"
  dark-surface: "#18151F"
  dark-surface-raised: "#1F1B28"
  dark-border: "#2B2636"
  dark-border-strong: "#3A3447"
  dark-text: "#ECE9F2"
  dark-text-muted: "#A29BB1"
  dark-accent: "#9C8EF6"
  dark-accent-text: "#120F1A"
  dark-pass: "#52D497"
  dark-pass-bg: "#10281C"
  dark-fail: "#FF7A78"
  dark-fail-bg: "#35171A"
  dark-inconclusive: "#F2B85A"
  dark-inconclusive-bg: "#33260F"
  dark-info: "#7DB4F5"
  dark-info-bg: "#12243A"
  dark-sidebar: "#0D0B13"
  dark-sidebar-text: "#C2BBD0"
  dark-sidebar-muted: "#857D96"
  dark-sidebar-active: "#231E30"
  dark-sidebar-strong: "#F5F2FA"
typography:
  display:
    fontFamily: Geist
    fontSize: 1.5rem
    fontWeight: 600
    lineHeight: "1.25"
    letterSpacing: "-0.01em"
  title:
    fontFamily: Geist
    fontSize: 1.0625rem
    fontWeight: 600
    lineHeight: "1.3"
  body:
    fontFamily: Geist
    fontSize: 0.875rem
    fontWeight: 400
    lineHeight: "1.5"
  label:
    fontFamily: Geist
    fontSize: 0.75rem
    fontWeight: 500
    lineHeight: "1.3"
    letterSpacing: "0.02em"
  mono:
    fontFamily: JetBrains Mono
    fontSize: 0.8125rem
    fontWeight: 400
    lineHeight: "1.5"
    fontFeature: "tnum"
rounded:
  sm: 4px
  md: 6px
  lg: 8px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 32px
components:
  button-primary:
    backgroundColor: "{colors.light-accent}"
    textColor: "{colors.light-accent-text}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
  badge-verdict:
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "{spacing.xs}"
---

# Apgar design system

## Overview

Apgar is a release health product. The interface is dense and flat, in the family of issue trackers such as Sentry: a dark aubergine sidebar, a white top bar, and white panels on a faintly violet page. Light and dark themes come from one token set. Surfaces stay neutral so verdicts, regressions, and identifiers stay easy to scan.

## Principles

The layout stays dense so an operator can read a release without scrolling past decoration.

Surfaces are flat. Panels are separated by a 1px border, not by shadows. Only overlays (menus, dialogs, toasts) may cast a shadow.

The only gradient is on the login brand panel. The app sidebar is a solid `sidebar` fill.

The product does not use decorative illustration.

The accent color is reserved for primary actions and for the current selection.

Status colors are reserved for verdicts and the health of a connection, token, or delivery.

## Color

Neutral tokens (`bg`, `surface`, `surface-raised`, `border`, `border-strong`, `text`, `text-muted`) carry the chrome. `accent` and `accent-text` mark primary actions and selection. `pass`, `fail`, and `inconclusive`, each with a matching background token, mark verdicts and health state only. `info` and `info-bg` mark neutral, non-judging state, such as a metric that is reported but never decides the verdict. The `sidebar` tokens (`sidebar`, `sidebar-text`, `sidebar-muted`, `sidebar-active`, `sidebar-strong`) color the app sidebar and the login brand panel and nothing else.

Both themes are defined as `light-*` and `dark-*` color tokens. `scripts/themes.ts` maps them onto semantic variables.

| Semantic variable | Light token | Dark token |
| --- | --- | --- |
| `--bg` | `light-bg` | `dark-bg` |
| `--surface` | `light-surface` | `dark-surface` |
| `--surface-raised` | `light-surface-raised` | `dark-surface-raised` |
| `--border` | `light-border` | `dark-border` |
| `--border-strong` | `light-border-strong` | `dark-border-strong` |
| `--text` | `light-text` | `dark-text` |
| `--text-muted` | `light-text-muted` | `dark-text-muted` |
| `--accent` | `light-accent` | `dark-accent` |
| `--accent-text` | `light-accent-text` | `dark-accent-text` |
| `--pass` | `light-pass` | `dark-pass` |
| `--pass-bg` | `light-pass-bg` | `dark-pass-bg` |
| `--fail` | `light-fail` | `dark-fail` |
| `--fail-bg` | `light-fail-bg` | `dark-fail-bg` |
| `--inconclusive` | `light-inconclusive` | `dark-inconclusive` |
| `--inconclusive-bg` | `light-inconclusive-bg` | `dark-inconclusive-bg` |
| `--info` | `light-info` | `dark-info` |
| `--info-bg` | `light-info-bg` | `dark-info-bg` |
| `--sidebar` | `light-sidebar` | `dark-sidebar` |
| `--sidebar-text` | `light-sidebar-text` | `dark-sidebar-text` |
| `--sidebar-muted` | `light-sidebar-muted` | `dark-sidebar-muted` |
| `--sidebar-active` | `light-sidebar-active` | `dark-sidebar-active` |
| `--sidebar-strong` | `light-sidebar-strong` | `dark-sidebar-strong` |

## Typography

Geist is the UI face for display, title, body, and label text. Inter is the fallback.

JetBrains Mono is the face for identifiers, hashes, and numeric columns. Those runs use `tnum` so digits line up in tables.

The root font size stays at the browser default of 16px, so every `rem` value maps to the scale below. Body text is 14px, the same base that Sentry and Datadog use for dense dashboards. No text is smaller than 12px.

| Token | Size | Use |
| --- | --- | --- |
| `--text-xs` | 12px | Badges, table headers, labels, captions |
| `--text-mono` | 13px | Identifiers, hashes, token fields |
| `--text-sm` | 14px | Body, table cells, nav, buttons, inputs |
| `--text-base` | 16px | Panel titles |
| `--text-lg` | 18px | Wordmark |
| `--text-xl` | 20px | Summary card numbers |
| `--text-2xl` | 24px | Page heading |

Section and panel titles use the full `text` color. `text-muted` is for supporting text such as table headers, counts, captions, and secondary columns, never for a title. Emphasis comes from one change at a time (weight or a status color), not from stacking several.

The login headline uses a `clamp()` above this scale. Components use the tokens or the matching Tailwind classes (`text-xs`, `text-sm`, and so on), not raw pixel sizes.

## Spacing and radius

Spacing steps are 4, 8, 12, 16, 24, and 32 pixels. Radius steps are 4, 6, and 8 pixels. Buttons and inputs use 6. Panels, cards, and tables use 8. Badges are fully rounded pills.

The spacing tokens export as `--spacing-xs` through `--spacing-2xl`, which Tailwind v4 also uses for named sizes. `max-w-lg` therefore means 16px, not 32rem. Write container widths as explicit values such as `max-w-[32rem]`.

## Components

The app shell is a 228px `sidebar` column and a 52px `surface` top bar with a breadcrumb. The sidebar holds the wordmark, icon nav items, and Settings pinned to the bottom. The current item gets the `sidebar-active` fill and `sidebar-strong` text.

Each page opens with a page head: a 24px heading, a muted one line description, and actions on the right.

`button-primary` uses the accent fill and accent text. It is the only filled action in a view. Secondary buttons are 32px high with a `border-strong` outline on `surface`.

A panel is a `surface` box with a 1px `border` and the large radius. Tables, forms, and summary cards sit inside panels.

Summary cards show a 12px muted label over a 20px tabular number. A number that reports failure takes the `fail` color.

`badge-verdict` is a 20px pill with a text label (`PASS`, `FAIL`, `INCONCLUSIVE`, `PENDING`). Color repeats the label. It does not replace it.

Tables sit in a panel. The header is 12px, muted, and not filled. Rows are divided by a faint line and highlight on hover. Numeric columns are right aligned with tabular numbers, identifiers are monospace, and links use the accent color. A row can take keyboard focus and opens on Enter.

Tables stacked in one section share fixed column widths (`table-fixed` with the same `colgroup`) so their columns line up. A sortable header is a button with a small arrow icon; a click cycles descending, ascending, then the default order, and only one column sorts at a time. A repeated row action, such as opening a trace, is an accent icon with an accessible name instead of repeated link text. An identifier the operator may need elsewhere shows a copy button on row hover and focus.

Times are UTC everywhere. Relative times read `just now`, `12m ago`, `5h ago`, and `2d ago`, then switch to a date such as `Oct 3` after seven days. Lists that are compared row by row, such as example turns, show the absolute time (`Oct 10, 18:42`) with `(UTC)` in the header.

Banners have a 4px left border in the status color over the matching background token.

The primitives below live in `src/components/ui/`. Pages compose them instead of styling raw elements.

| Component | Use |
| --- | --- |
| `Panel`, `PanelHeader`, `PanelBody`, `PanelFooter` | A titled box. The header holds a 14px title, a 12px muted description, and actions on the right. The footer holds the form actions, right aligned. |
| `Field` | A 12px label over one control, with an optional hint under it and an optional `InfoTip` beside the label. A required field shows a `fail` colored `*` directly after the label text, and its control sets `aria-required`; optional fields carry no mark. Explanations of what a field does go in the `InfoTip`; the hint line holds only validation errors and links the operator needs to act on. Forms lay fields out in an auto fill grid. |
| `Input`, `Select` | 32px controls with a `border-strong` outline and an accent focus ring. `Select` draws its own chevron and is at least 144px wide, so it never looks empty. `Suffixed` adds a unit such as `days` or `pp`. |
| `Modal`, `ModalBody`, `ModalFooter` | A centered dialog with a title, an optional description, and a close button. Sizes `sm`, `md`, and `lg`. The body scrolls; the footer sits on the muted color with actions right aligned. |
| `Sheet` | A panel that slides in from the right for the details of a selected row, without an overlay, so the page stays visible. It closes on an outside click, Escape, or the close button. The header holds a title and one muted line that names the selection. |
| `useConfirm` | Returns `confirm(options)` and a `dialog` node to render. Resolves `true` or `false`. Use it for every destructive confirmation instead of `window.confirm`. |
| `Switch` | A binary setting that applies on save, or immediately when the row says so. It keeps `role="switch"` and `aria-checked`. |
| `Notice` | An inline message with an icon and a 4px left border. Tones are `info` (accent), `success`, `warning`, and `fail`. |
| `StatusPill` | A pill with a leading dot for health state: `ok`, `active`, and `sent` use `pass`; `error` and `failed` use `fail`; `pending` uses `inconclusive`; anything else is neutral. |
| `InfoTip` | An info icon that shows a short explanation on hover or focus. Use it for terms an operator may not know, not for instructions they need to finish a task. |
| `Button` | Variants `default` (the one filled action), `outline`, `ghost`, `danger` (fail text on an outline, for the trigger), and `destructive` (filled fail, for the confirm button). Sizes `md` (32px) and `sm` (28px, for table rows). |

Underline tabs sit on a bottom border. The selected tab takes the accent underline and full text color. Tabs scroll horizontally when they do not fit.

Settings tables use the `.data-table` class. Each table shows an empty row with a short sentence when it has no data. The name column uses `.cell-name`: the identifier in 13px mono at full text color, with one 12px muted line of context under it, such as when it was added.

Destructive actions use the `danger` button and open `useConfirm`. The dialog names the object and says what happens, and its confirm button uses the `destructive` variant. A whole object delete sits in its own panel at the bottom of the page.

Create flows open in a `Modal`. When the server returns a secret, the same modal switches to a reveal step: the secret in a mono box, a copy button that confirms with "Copied", a warning that it is shown once, and a single Done button. The secret never appears on the page itself.

Code and JSON previews use `.code-block`: mono 12px on the `bg` color with the medium radius.

## Accessibility

Text and status pairs target WCAG 2.1 AA. The focus ring is `2px solid var(--accent)` with a `2px` offset, and it is visible on every interactive control. Every action is reachable from the keyboard in DOM order. Icon-only controls have an accessible name. Trend direction is exposed as text, not only as an arrow.

## Theme mapping

`npm run tokens` exports `DESIGN.md` to `src/theme.generated.css` as Tailwind v4 `--color-light-*` and `--color-dark-*` variables. `scripts/themes.ts` reads that file and writes `src/themes.generated.css` with `[data-theme="light"]` and `[data-theme="dark"]` selectors. Each selector aliases the semantic variables (`--bg`, `--surface`, `--text`, `--accent`, `--pass`, `--fail`, `--inconclusive`, `--sidebar`, and their companions) to the matching theme tokens and sets `color-scheme`. Components reference the semantic variables only.

## Attribution

Structure derived from `examples/ai-devtool/DESIGN.md` in `abhayjnayakk/awesome-design-md` at commit `dbd98792cc3f39de547a183f8e549691b8e7bfc0`, MIT License. Palette and typography are original.
