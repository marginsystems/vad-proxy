# Voice Lab UI redesign brief

You are redesigning the UI of a small Vite + React + TypeScript app called "vad-proxy Voice Lab".
This is a developer tool for live-testing microphone -> VAD -> STT -> transcript against a local server.
Apply all changes directly to the files in this project (working directory is `frontend/`).

## Scope

Restyle the UI only. Do NOT change any React logic, props, hooks, state, or the GraphQL/audio code.
You may edit `className` attributes and the static markup structure of components (e.g. wrap text in
spans, split rows), but every existing prop, handler, and piece of conditional rendering logic must
keep working exactly as before.

Files you may edit:
- `index.html` (add Google Fonts)
- `src/index.css` (all styling)
- `src/App.tsx` (markup/className only)
- `src/components/ConnectionPanel.tsx` (markup/className only)
- `src/components/Controls.tsx` (markup/className only)
- `src/components/TranscriptPanel.tsx` (markup/className only)
- `src/components/EventLog.tsx` (markup/className only)

Do NOT edit any file under `src/lib/` or `src/hooks/`. Do NOT add npm dependencies.

## Hard constraints (must follow exactly)

1. **Pure CSS only** in `src/index.css`. No Tailwind, no CSS framework, no CSS-in-JS, no animation
   libraries (no Framer Motion). The project must still build with the existing dependencies only.
2. **Border radius**: reduce the radius on every element to a maximum of `2px`. Define a
   `--radius: 2px` token and use it everywhere (panels, buttons, inputs, banners, event log, pills).
3. **Glass morphism**: panels and controls should use a frosted-glass look:
   - semi-transparent backgrounds with `rgba(...)`
   - `backdrop-filter: blur(...)` (include `-webkit-backdrop-filter` for Safari)
   - subtle 1px translucent light borders
   - a dark ambient page background (a CSS gradient, no images) so the blur is visible
4. **Transitions**: use `cubic-bezier(0.4, 0, 0.2, 1)` easing (define a `--ease` token). Apply only to
   hover/focus/active/state changes (background, border-color, transform, opacity). Keep them short
   (~150ms). No keyframe scroll/entrance animations.
5. **Google Fonts, zero font layout shift**:
   - Use **Inter** for UI text and **JetBrains Mono** for the event log / monospace areas.
   - In `index.html` add `preconnect` to `fonts.googleapis.com` and `fonts.gstatic.com` (crossorigin),
     then the stylesheet link with `display=swap`.
   - In CSS, set the font stack on `:root`/`body` with a close system fallback
     (`Inter, system-ui, -apple-system, sans-serif` and `'JetBrains Mono', ui-monospace, monospace`)
     so first paint matches the loaded font as closely as possible.
6. **No layout shift anywhere (CLS = 0)**. This is the most important requirement. See below.

## Layout-shift requirements (critical)

The biggest current problem is the health banner in `ConnectionPanel.tsx`. It renders different text
lengths depending on state ("Checking server…" vs "Server OK — STT: mock, rate 16000 Hz, origins:
http://localhost, http://127.0.0.1, https://biosystems.dev · session: idle"). When data loads or the
origins list is long, the banner changes height and pushes everything down.

Fix it so the health banner has a **fixed height that is identical in every state**:
- loading ("Checking server…")
- healthy (server info + origins)
- error (health error message)

Approach:
- Give the health banner container a fixed height (e.g. `4.5rem`) or a fixed number of fixed-height rows.
- Use a status pill/dot for the connection state, plus metadata "chips" for STT backend, sample rate,
  and session status.
- The origins value can be long: keep it on a single line with `overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;` and put the full list in a `title` attribute for hover. Do not let it wrap.
- For the loading state, render skeleton placeholders with the SAME dimensions as the loaded content
  (not shorter text), so nothing resizes when data arrives.

Other layout-shift sources to fix:
- `TranscriptPanel.tsx`: the `.latest-transcript` area must reserve a fixed `min-height` (~5rem) so the
  panel does not grow when the first transcript appears. Show a muted placeholder line when empty.
- `App.tsx`: the error banner appears/disappears at the top. Make sure its appearance does not cause a
  jarring downward jump — reserve space or treat it consistently.
- `Controls.tsx`: buttons must keep a fixed height and must not change size or font-weight between
  enabled/disabled/listening states.
- `EventLog.tsx`: the collapsed toggle header must always be the same height. The expanded log uses a
  `max-height` + `overflow: auto` (expanding the log is allowed to grow the page; just keep the header
  stable and don't shift other content above it).

## Visual direction

Modern, minimal, precise "lab tool" aesthetic — calm dark theme, good contrast, generous spacing,
clear typographic hierarchy. Not playful, no bright gradients on text. Think developer dashboard.

## Current files (for reference)

The component markup and current CSS are in the files listed above; read them before editing. Preserve
all class names that are referenced by logic, and keep the component export signatures identical.

## When done

Make sure `npm run build` (which runs `tsc --noEmit && vite build`) still passes.
