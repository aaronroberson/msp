---
name: macOS Security Console Pro
colors:
  surface: '#0c1322'
  surface-dim: '#0c1322'
  surface-bright: '#323949'
  surface-container-lowest: '#070e1d'
  surface-container-low: '#141b2b'
  surface-container: '#191f2f'
  surface-container-high: '#232a3a'
  surface-container-highest: '#2e3545'
  on-surface: '#dce2f7'
  on-surface-variant: '#c0c6d6'
  inverse-surface: '#dce2f7'
  inverse-on-surface: '#293040'
  outline: '#8b91a0'
  outline-variant: '#414754'
  surface-tint: '#aac7ff'
  primary: '#aac7ff'
  on-primary: '#003064'
  primary-container: '#3e90ff'
  on-primary-container: '#002957'
  inverse-primary: '#005db8'
  secondary: '#c2c6d4'
  on-secondary: '#2b303b'
  secondary-container: '#444955'
  on-secondary-container: '#b3b8c6'
  tertiary: '#ffb691'
  on-tertiary: '#552000'
  tertiary-container: '#eb6a12'
  on-tertiary-container: '#4a1b00'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#d6e3ff'
  primary-fixed-dim: '#aac7ff'
  on-primary-fixed: '#001b3e'
  on-primary-fixed-variant: '#00468d'
  secondary-fixed: '#dee2f0'
  secondary-fixed-dim: '#c2c6d4'
  on-secondary-fixed: '#161c26'
  on-secondary-fixed-variant: '#424752'
  tertiary-fixed: '#ffdbcb'
  tertiary-fixed-dim: '#ffb691'
  on-tertiary-fixed: '#341100'
  on-tertiary-fixed-variant: '#793100'
  background: '#0c1322'
  on-background: '#dce2f7'
  surface-variant: '#2e3545'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.015em
  headline-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.012em
  headline-md:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: -0.008em
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: -0.003em
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0em
  mono-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: -0.01em
  mono-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: -0.005em
  mono-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 14px
    letterSpacing: 0em
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 0.75rem
  margin: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style

This design system embodies Apple-grade professional systems engineering: ultra-precise, understated, and functional. It rejects cyberpunk tropes, artificial bloom, and superfluous neon styling in favor of the focused utility expected by macOS systems architects, security researchers, and enterprise site reliability engineers. 

The interface communicates stability, speed, and deep kernel-level visibility. Every layout element adheres to the philosophy of high-density clarity:
- **Tone:** Methodical, surgical, and authoritative.
- **Visual Style:** Pro Utility Minimalist. Contrast is achieved through crisp typographic hierarchy, precise surface separation, and restrained hairline borders rather than heavy atmospheric dropshadows.
- **Materiality:** Opaque dark graphite substrates, subtle 1px division lines, and razor-sharp data alignment that mimics native AppKit and SwiftUI desktop instrumentation.

## Colors

The color system utilizes an architectural dark theme engineered for prolonged terminal and console monitoring without ocular fatigue.

### Palette Construction
- **Canvas Base (`#0B0F14`):** Deep carbon substrate that provides grounding depth across the global window workspace and left-rail chrome.
- **Surface Elevation (`#111827`):** Refined graphite tone for inspection panels, telemetry feeds, card bodies, and modal sheets.
- **Hairline Dividers (`#2D323A`):** Low-contrast architectural structural lines (1px) defining grid bounds, table rows, and panel separations.
- **Primary Text (`#F2F4F8`):** High-legibility optic white with a hint of coolness for active process identifiers, critical alerts, and headings.
- **Muted Text (`#8E93A0`):** Mid-tone neutral for secondary labels, inactive states, column headers, and structural metadata.

### System Indicators & Telemetry
Color is deployed strictly for semantic distinction and status verification:
- **Interactive Blue (`#0A84FF`):** Selection states, active command triggers, and system keyboard navigation cues.
- **Integrity Green (`#34C759`):** Hardened SIP states, valid code signatures, active firewall rules, and healthy daemons.
- **Advisory Amber (`#FF9F0A`):** Gatekeeper overrides, unsigned kernel extensions, elevated privilege requests, and background daemon changes.
- **Critical Red (`#FF3B30`):** Tampered binaries, non-notarized process executions, rogue sockets, and active XProtect revocations.

## Typography

The typographic strategy pairs a clean system sans-serif (Inter standing in for SF Pro) for window navigation, structural headings, and administrative copy with a high-performance monospace typeface (JetBrains Mono standing in for SF Mono) for technical telemetry.

### Typographic Rules
- **UI Labels & Controls:** Use `Inter` at weights 400 through 600. Keep button text, section categories, and sidebar menu items crisp, setting uppercase labels with subtle positive letter spacing (`0.04em`).
- **Telemetry & Kernel Data:** Process IDs (PIDs), SHA-256 hashes, IPv4/IPv6 addresses, memory offsets, timestamp logs, and Mach port states must always be rendered in `JetBrains Mono`.
- **Tabular Figures:** Monospace text elements enforce vertical column alignment across rapidly updating stream panels and tables.

## Layout & Spacing

The spatial model enforces dense desktop utility ergonomics optimized for macOS widescreen views, multi-monitor operations, and rapid keyboard scrubbing.

### Spatial Architecture
- **Desktop Shell:** Fixed 240px left-rail navigation docked flush to the window frame. Main stage utilizes a dynamic column grid with a strict 0.75rem (`12px`) gutter system.
- **Top Utility Header:** Fixed 48px height containing the window traffic light offset, current security state summary, profile switcher, and persistent `⌘K` Command Palette entry trigger.
- **Vitals Strip:** High-density horizontal ribbon directly below the header presenting global integrity indicators (SIP, Gatekeeper, TCC, Endpoint Security subsystem health) spaced using `space-md` gaps.
- **Split Telemetry Pane:** 60/40 two-column main partition: left side displays real-time security events and alerts; right side hosts continuous network connection streams and socket inspections.
- **Padding Discipline:** Cards and data grids use compact padding (`space-sm` to `space-md`) to ensure critical diagnostic information remains above the fold without unnecessary scrolling.

## Elevation & Depth

This system avoids floating cloud shadows, colored halos, or dramatic blurs. Depth is achieved purely through precise tone stepped layering and crisp boundaries:

- **Level 0 (Canvas Base):** `#0B0F14` — Foundation canvas behind the sidebar and stage workspace.
- **Level 1 (Panels & Surfaces):** `#111827` bordered by a 1px solid `#2D323A` line. Used for all primary cards, inspector drawers, and log frames.
- **Level 2 (Active/Hover Controls):** `#1A2233` with active borders shifting to `#3B4250`. Used for row highlights, selected tree items, and active input backgrounds.
- **Level 3 (Command Palette & Overlays):** `#161F30` with a 1px `#3E4756` border and a restrained system modal drop shadow (`0 16px 32px rgba(0, 0, 0, 0.60)`), establishing direct focus without visual clutter.
- **Dividers:** Internal table separators, tree node guides, and header splitters rely strictly on 1px `#2D323A` hairline rules.

## Shapes

The interface adheres to an 8px (`0.5rem`) primary corner radius across primary panels, input controls, and system overlays to match modern macOS window conventions.

- **Panels & Surface Cards:** Exact 8px (`0.5rem`) radius.
- **Inline Badges & Indicators:** 4px (`0.25rem`) radius to preserve maximum interior density.
- **Input Fields & Buttons:** 6px to 8px radius with inset borders.
- **Pills / Status Dots:** Strict circular geometry (`50%` / 6px × 6px) placed adjacent to monospaced text to denote daemon uptime and real-time socket connections.

## Components

### Buttons & Action Triggers
- **Primary:** Background `#0A84FF`, Text `#F2F4F8`, border none, 6px radius, height 28px, font size 12px (Inter Medium). Focus outline: 2px `#0A84FF` with 2px offset.
- **Secondary / Ghost:** Background `transparent`, border 1px solid `#2D323A`, Text `#F2F4F8`. On hover: background `#1A2233`, border `#3B4250`.
- **Destructive (Revoke/Kill):** Background `rgba(255, 59, 48, 0.1)`, border 1px solid `rgba(255, 59, 48, 0.3)`, Text `#FF3B30`. On hover: background `rgba(255, 59, 48, 0.2)`.

### Chips & Telemetry Badges
- **Format:** Inset pill container, height 20px, padding `0 6px`, font `JetBrains Mono` 11px.
- **Status Types:**
  - *Hardened/Signed:* Surface `rgba(52, 199, 89, 0.1)`, text `#34C759`, border 1px solid `rgba(52, 199, 89, 0.25)`.
  - *Advisory/Elevated:* Surface `rgba(255, 159, 10, 0.1)`, text `#FF9F0A`, border 1px solid `rgba(255, 159, 10, 0.25)`.
  - *Revoked/Untrusted:* Surface `rgba(255, 59, 48, 0.1)`, text `#FF3B30`, border 1px solid `rgba(255, 59, 48, 0.25)`.

### Data Tables & Log Streams
- **Header:** Height 28px, background `#0B0F14`, bottom border 1px solid `#2D323A`, typography `Inter` 11px uppercase (`label-caps`), text `#8E93A0`.
- **Rows:** Height 28px, typography `JetBrains Mono` 12px, border-bottom 1px solid `#1C2430`. Alternate row zebra stripping omitted; hover triggers background `#161F2E`.
- **Selection:** Selected row background `rgba(10, 132, 255, 0.15)` with a 2px vertical highlight on the left edge in `#0A84FF`.

### Command Palette (⌘K)
- **Geometry:** Centered modal, width 580px, max-height 380px, background `#111827`, border 1px solid `#3E4756`, radius 8px.
- **Input Field:** Height 44px, flush borderless top region, icon-prefixed, placeholder text `#8E93A0`, active caret `#0A84FF`.
- **Result Row:** Height 36px, keyboard navigation active index marked with background `#1A2438` and trailing shortcut glyphs in monospace caps.

### Cards & Container Panels
- Surface `#111827`, border 1px solid `#2D323A`, radius 8px. Header strip inside cards features a 32px height, baseline 1px divider, panel title in `Inter` 13px SemiBold, and trailing utility icons (filter, pause stream, export).