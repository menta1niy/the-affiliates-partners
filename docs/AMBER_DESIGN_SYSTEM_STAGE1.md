# The Affiliates Partners — Amber Edition design foundation

Stage 1 of the approved v3.2 implementation plan. Scope: **design-system consolidation only**. No registration, API, data, role, navigation-count, or payment changes.

## Source of truth

Shared styles and tokens live in the first expanded `:root` of `web/style.css`.
The old compact foundational CSS is retained for compatibility; do not add new
overrides in its minified block. Use named tokens in subsequent components.

| Role | CSS token | Value |
| --- | --- | --- |
| Canvas | `--color-bg` | `#080909` |
| Surface | `--color-surface` | `#131416` |
| Elevated | `--color-elevated` | `#1B1D20` |
| Muted text | `--color-secondary` | `#A2A4A7` |
| Main text | `--color-text` | `#F7F7F5` |
| Warm action / important payout | `--accent-amber` | `#E4A34A` |
| Hover action | `--accent-amber-hover` | `#F0B660` |
| Primary action text | `--accent-amber-ink` | `#18110A` |
| Body font | `--font-body` | Plus Jakarta Sans with system fallback |
| Display font | `--font-display` | Self-hosted Unbounded with fallback |
| Panel/inner/control radius | `--float-panel-radius` / `--float-inner-radius` / `--float-control-radius` | `28/22/18px` desktop; panel/control `25/17px` mobile |
| Dock action | `--dock-action-width` / `--dock-action-height` | `48 × 46px` |
| Dock blur/radius | `--dock-blur` / `--dock-radius` | `22/25px` |
| Button height | `--control-height` / `--control-height-compact` | `48/44px` |
| Spacing scale | `--space-1` to `--space-16` | `4, 8, 12, 16, 20, 24, 32, 40, 48, 64px` |

`--color-accent` remains neutral white for legacy foundations, **not** a
replacement for Amber. Do not recolor financial/semantic status badges with
Amber just because a value is highlighted.

## Screen layout conventions

- Lead screen-intro cards now share one selector `.participant-screen-intro`.
  It covers the existing Offers and Profile views and is intended for the
  future Statistics view. Desktop minimum height `155px`, mobile `132px`;
  display size `clamp(17px,3.1vw,30px)` desktop and
  `clamp(16px,5vw,24px)` mobile. Keep one-line headings at narrow widths.
- The current lead dock remains **three** icon-only entries. The planned
  fourth Statistics tab must be added with the functional navigation stage;
  change `--lead-nav-columns` from 3 to 4 **together** with the markup/router.
  Never add labels or stretch the dock to full viewport width.
- At mobile widths use the existing 17px shell horizontal inset as rendered;
  future work may unify to 16px only after a full visual comparison.
- Display font applies to short branded headlines; body font applies to
  paragraphs, forms, statuses and instructions. Never shrink operational
  messages to decorative 8–10px kicker sizes.
- Offer dialog title and 44px close control share the native dialog surface.
  The older opaque, sticky heading was removed. Do not reintroduce it.
- Use amber focus outlines on user-facing lead/admin controls; keep keyboard
  navigation and reduced-motion/transparency support.

## Stage 1 maintenance changes

1. Moved previously scattered typography, Amber, Rounded Float, dock and
   control tokens into the root token set.
2. Reused tokens in the actual headline and dock styles without changing
   the active layout or number of tabs.
3. Removed superseded sticky-modal heading and contrasting Offers/Profile
   background definitions, preventing older CSS from resurfacing accidentally.
4. Standardized lead/admin keyboard focus color and disabled pointer cursor.

## Acceptance checklist for this stage

- The live CSS loads and preserves graphitic surfaces plus amber CTAs.
- Offers and Profile title geometry matches at 320, 390 and 430px.
- The offer dialog has a transparent, non-sticky header with 44px close area.
- Lead dock stays compact, icon-only, `48 × 46px` actions and `22px` blur.
- Existing admin navigation and permissions are unchanged.
- Basic browser tests and `git diff --check` pass. Full end-to-end financial
  regression is reserved for stages that actually alter business logic.

## Deferred to later stages

New admin navigation, a fourth lead tab, logos, animation variants, personal
data, credit questionnaires, referrals, payouts, MFO workflows, and bot
notifications are **not** part of this commit. No server publication until
the user explicitly starts the final release after all stages.
