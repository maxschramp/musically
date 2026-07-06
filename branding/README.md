# musically — Brand Toolkit

A complete, implementation-ready export of the musically brand system: logo files, UI icon set, design tokens, and coded components.

## Quick start

- **Need the logo?** → `assets/logo/svg/` (vector) and `assets/logo/png/` (transparent raster, multiple sizes)
- **Need UI icons?** → `assets/icons/svg/` and `assets/icons/png/`
- **Need the full guidelines?** → `docs/brand-guidelines.md`
- **Building a UI?** → `ui/` — CSS + React components, plus `ui/showcase.html` to preview everything in a browser
- **Syncing with a design tool?** → `docs/design-tokens.json`

## Folder structure

```
musically-brand-toolkit/
├── assets/
│   ├── logo/
│   │   ├── svg/     4 vector lockups (color, white, mono, icon-only, icon+flourish)
│   │   └── png/     transparent PNGs @640/1240/2480px (lockups), @64–1024px (icon)
│   └── icons/
│       ├── svg/     12 UI glyph icons (waveform, play, stack, profile, bookmark, etc.)
│       └── png/     transparent PNGs @48/96/192/512px
├── docs/
│   ├── brand-guidelines.md   full written guidelines
│   └── design-tokens.json    machine-readable color/type/spacing tokens
└── ui/
    ├── tokens.css                CSS custom properties (source of truth for styling)
    ├── components/
    │   ├── buttons.css
    │   ├── player.css
    │   └── cards.css
    ├── showcase.html              open in any browser — live preview of every component
    ├── MusicallyUI.jsx            React component wrappers
    └── README.md                  implementation instructions
```

## Brand at a glance

| | |
|---|---|
| **Primary color** | Dark Green `#2D4535` |
| **Accent** | Orange-Coral `#FF7F6E` |
| **Secondary accent** | Purple `#A57DCD` |
| **Typeface** | Poppins (SemiBold headings, Regular body) |
| **Shape language** | Rounded squares (logo), full pill buttons, circular icon chips |

See `docs/brand-guidelines.md` for full usage rules, do's and don'ts, and component specs.
