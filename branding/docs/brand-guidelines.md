# musically — Brand Guidelines

A social music-discovery brand. Warm, rhythmic, and a little playful — built around a waveform mark, a rounded geometric wordmark, and a palette that pairs an earthy dark green with a bright coral accent.

---

## 1. Logo

### 1.1 Primary mark
The waveform badge is the core symbol: a hand-drawn-feeling pulse line inside a rounded square, always rendered in **Dark Green (#2D4535)** with a **white** stroke.

### 1.2 Logo toolkit (extended lockup)
For contexts that need extra visual richness (splash screens, marketing headers), the mark can be paired with two supporting glyphs:
- **Play triangle** in a coral circle — represents playback
- **Stacked bars** in a purple pill shape — represents queues/playlists

These three elements together form the "Logo Toolkit" lockup. Use it sparingly — it's a decorative flourish, not the everyday logo.

### 1.3 Wordmark
Set in a semi-bold, rounded geometric sans (**Poppins SemiBold** or equivalent — see Typography), always lowercase: `musically`. The dotted "i" and "l" ligature give it a friendly, musical character — don't switch to a different weight or add letter-spacing.

### 1.4 Files provided
| File | Use |
|---|---|
| `assets/logo/svg/logo-full-color.svg` | Full lockup (icon + wordmark), dark green — default, light backgrounds |
| `assets/logo/svg/logo-full-white.svg` | Full lockup, white — dark or photo backgrounds |
| `assets/logo/svg/logo-full-mono.svg` | Full lockup, single-color dark green — print, engraving, watermarks |
| `assets/logo/svg/icon-square.svg` | Icon only, square, for favicons and app icons |
| `assets/logo/svg/icon-mark.svg` | Icon + play + stack (the "Logo Toolkit" flourish) |
| `assets/logo/png/*.png` | Transparent PNG exports of every SVG above at 640/1240/2480px (lockups) and 64–1024px (icon) |

### 1.5 Clear space & minimum size
Keep clear space around the mark equal to the height of the icon badge. Don't scale the icon below 24px or the full lockup below 120px wide — the wordmark's dot details break down below that.

### 1.6 Don'ts
- Don't recolor the icon outside the approved palette
- Don't stretch or skew the lockup
- Don't place the dark-green wordmark on a dark background — use the white variant
- Don't add drop shadows or outlines to the logo

---

## 2. Color Palette

| Swatch | Name | Hex | Use |
|---|---|---|---|
| 🟩 | Dark Green | `#2D4535` | Primary brand color — logo, headings, dark surfaces |
| 🟢 | Sage Green | `#4B6E55` | Secondary green — hover states, muted UI |
| 🟠 | Orange-Coral | `#FF7F6E` | Primary accent — CTAs, play button, likes |
| 🟣 | Purple | `#A57DCD` | Secondary accent — playlists, bookmarks, tags |
| ⚪ | Off-White | `#F5F5F5` | Default background |
| ⚫️ | Light Grey | `#D0D0D0` | Borders, disabled states, secondary icons |

**Pairing rules**
- Dark Green + Off-White is the default light-mode pairing.
- Coral is the single "action" color — reserve it for the primary call to action per screen (play, follow, like) so it keeps its impact.
- Purple is reserved for collection/library concepts (playlists, saved items, queues) — don't use it interchangeably with coral.
- The four-color stripe (Dark Green / Sage / Coral / Purple) is a signature background treatment for social post templates — see Section 5.

---

## 3. Typography

**Typeface:** Poppins (complementary sans, geometric + rounded). Any similar rounded geometric sans — Quicksand, Nunito, Baloo 2 — can substitute if Poppins isn't licensed for a given surface.

| Role | Weight | Size (web rem) | Example use |
|---|---|---|---|
| Display / Logo | SemiBold (600) | 4rem+ | Wordmark, hero headlines |
| Heading | SemiBold / Bold (600–700) | 1.5–2rem | Section titles, card titles |
| Body | Regular (400) | 1rem | Paragraph copy, descriptions |
| Small / Caption | Regular/Medium | 0.875rem | Timestamps, labels, metadata |

Line height: 1.2 for headings, 1.5 for body copy. Don't justify text; keep left alignment throughout.

---

## 4. Software UI Elements

The interface language is built from **circular icon chips** (48–64px) colored per the palette, **pill-shaped buttons**, and **rounded-rectangle cards** (16–24px radius).

### 4.1 Icon chips
Each functional icon sits inside a solid-color circle:
- Dark Green / Sage Green circles → navigation & primary brand icons (waveform)
- Coral circle → play, profile/social actions
- Purple circle → library, bookmark, queue
- Light Grey circle → secondary/disabled transport icons (shuffle, repeat, volume, image)

Files: `assets/icons/svg/*.svg` and matching transparent PNGs at 48/96/192/512px.

### 4.2 Buttons
- **Primary button** — coral fill, white text, fully rounded (pill) — main call to action
- **Secondary "Content" button** — dark green fill, white text — secondary actions
- Both use SemiBold weight text and generous horizontal padding (28px)

### 4.3 Player component
The now-playing card (dark-green surface) stacks: header (avatar + track title lines + overflow menu) → album art tile → track meta lines → scrubber → transport row (shuffle, previous, play/pause, next, repeat). A light-surface compact variant is also provided for embedding in feeds.

### 4.4 Feed / social cards
White rounded cards with an avatar + name/timestamp header, body text lines, and a bottom action row (like, comment, share) separated by a hairline border in Light Grey.

Implementation-ready code for all of the above lives in `/ui` — see `ui/README.md`.

---

## 5. Social Media Post Templates

Four ready patterns, all at 1:1 square ratio:
1. **Split card** — dark green block (logo + headline + CTA button) beside the 4-color vertical stripe
2. **Full stripe** — the four brand colors as equal vertical bands, wordmark centered in white
3. **Half & half** — dark green icon lockup on one side, off-white on the other
4. **Stripe + stacked icon** — stripe background with an oversized queue/stack icon

Keep post copy short (a headline + one supporting line) — these templates are meant to be scannable in a feed, not read in full.

---

## 6. File Index

```
musically-brand-toolkit/
├── assets/
│   ├── logo/
│   │   ├── svg/        (4 logo SVGs)
│   │   └── png/        (transparent PNG exports, multiple sizes)
│   └── icons/
│       ├── svg/        (12 UI icon SVGs)
│       └── png/        (transparent PNG exports, 48/96/192/512px)
├── docs/
│   ├── brand-guidelines.md   (this file)
│   └── design-tokens.json    (machine-readable tokens)
├── ui/
│   ├── tokens.css
│   ├── components/
│   │   ├── buttons.css
│   │   ├── player.css
│   │   └── cards.css
│   ├── showcase.html          (all components assembled, ready to open)
│   ├── MusicallyUI.jsx        (React component library)
│   └── README.md
└── README.md
```
