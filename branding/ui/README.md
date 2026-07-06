# musically — UI Implementation Kit

Ready-to-drop-in code implementing the "Software UI Elements" and "Social Media Post" patterns from the brand toolkit.

## Contents

| File | What it is |
|---|---|
| `tokens.css` | All brand CSS custom properties (colors, type, spacing, radius, shadow). Load this first. |
| `components/buttons.css` | `.btn` (primary/secondary/outline/accent) and `.icon-btn` (circular icon buttons in every brand color) |
| `components/player.css` | Now-playing / mini player card (dark + light variants) |
| `components/cards.css` | Feed post card, activity list row, color swatch, section label |
| `showcase.html` | Static HTML page rendering every component together — open directly in a browser to preview |
| `MusicallyUI.jsx` | React component wrappers (`Button`, `IconButton`, `PlayerCard`, `FeedCard`, `ActivityRow`, `Swatch`) around the same CSS classes |

## Plain HTML / CSS usage

```html
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="tokens.css">
<link rel="stylesheet" href="components/buttons.css">
<link rel="stylesheet" href="components/player.css">
<link rel="stylesheet" href="components/cards.css">

<button class="btn btn-primary">Play</button>
<button class="icon-btn icon-btn-coral"><img src="../assets/icons/svg/play-coral.svg" width="22"></button>
```

## React usage

```jsx
import "./tokens.css";
import "./components/buttons.css";
import "./components/player.css";
import "./components/cards.css";
import { Button, IconButton, PlayerCard, FeedCard } from "./MusicallyUI";

function App() {
  return (
    <>
      <Button variant="primary">Play</Button>
      <PlayerCard theme="dark" title="Song title" artist="Artist" progress={0.4} isPlaying />
      <FeedCard name="Jamie" timestamp="3h ago" body="New playlist is live!" likeCount={42} />
    </>
  );
}
```

## Restyling

Every component reads its colors and type from `tokens.css` custom properties — never edit the component CSS files to change a brand color. Update the value once in `:root` (or in `docs/design-tokens.json` for design-tool sync) and it propagates everywhere.
