/**
 * musically — React UI Component Library
 * -----------------------------------------------------------
 * Import tokens.css, components/buttons.css, components/player.css,
 * and components/cards.css once (e.g. in your app's root) before
 * using these components. They rely entirely on the CSS custom
 * properties defined in tokens.css, so no inline color values live
 * here — restyle the brand by editing tokens.css only.
 *
 * Usage:
 *   import { Button, IconButton, PlayerCard, FeedCard } from "./MusicallyUI";
 */

import React from "react";

/* ---------- Button ---------- */
export function Button({
  children,
  variant = "primary", // primary | secondary | outline | accent
  disabled = false,
  onClick,
  ...rest
}) {
  return (
    <button
      className={`btn btn-${variant}`}
      disabled={disabled}
      onClick={onClick}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ---------- Icon Button ---------- */
export function IconButton({
  children,
  color = "dark", // dark | sage | coral | purple | grey | ghost
  size,           // sm | lg | undefined (default 48px)
  onClick,
  ariaLabel,
  ...rest
}) {
  const sizeClass = size ? `size-${size}` : "";
  return (
    <button
      className={`icon-btn icon-btn-${color} ${sizeClass}`}
      onClick={onClick}
      aria-label={ariaLabel}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ---------- Now Playing Card ---------- */
export function PlayerCard({
  theme = "dark", // dark | light
  title = "Track title",
  artist = "Artist name",
  progress = 0.4, // 0..1
  artwork,
  isPlaying = false,
  onTogglePlay,
  onNext,
  onPrev,
  onShuffle,
  onRepeat,
}) {
  return (
    <div className={`player-card ${theme}`}>
      <div className="player-header">
        <div className="player-avatar" />
        <div className="player-track-lines">
          <div className="line" style={{ width: "60%" }} />
        </div>
        <button className="player-more" aria-label="More options">
          &#8942;
        </button>
      </div>

      {theme === "dark" && (
        <div className="player-art">
          {artwork ? (
            <img src={artwork} alt={title} />
          ) : (
            <span style={{ opacity: 0.4, fontSize: 12 }}>Album art</span>
          )}
        </div>
      )}

      <div className="player-meta">
        <div className="line wide" style={{ opacity: 1 }}>
          <span className="sr-only">{title}</span>
        </div>
        <div className="line mid">
          <span className="sr-only">{artist}</span>
        </div>
      </div>

      <div className="player-scrubber">
        <div className="fill" style={{ width: `${progress * 100}%` }} />
        <div className="thumb" style={{ left: `${progress * 100}%` }} />
      </div>

      <div className="player-transport">
        <IconButton color="ghost" size="sm" ariaLabel="Shuffle" onClick={onShuffle}>
          &#8646;
        </IconButton>
        <IconButton color="ghost" ariaLabel="Previous" onClick={onPrev}>
          &#9198;
        </IconButton>
        <IconButton
          color={theme === "dark" ? "grey" : "dark"}
          size="lg"
          ariaLabel={isPlaying ? "Pause" : "Play"}
          onClick={onTogglePlay}
        >
          {isPlaying ? "\u23F8" : "\u25B6"}
        </IconButton>
        <IconButton color="ghost" ariaLabel="Next" onClick={onNext}>
          &#9197;
        </IconButton>
        <IconButton color="ghost" size="sm" ariaLabel="Repeat" onClick={onRepeat}>
          &#8635;
        </IconButton>
      </div>
    </div>
  );
}

/* ---------- Feed Card ---------- */
export function FeedCard({
  avatarColor = "coral", // coral | purple | grey
  name = "User name",
  timestamp = "2h ago",
  body,
  likeCount = 0,
  commentCount = 0,
  onLike,
  onComment,
  onShare,
}) {
  return (
    <div className="feed-card">
      <div className="feed-card-header">
        <div className={`feed-avatar ${avatarColor}`} />
        <div className="feed-lines">
          <div className="line" style={{ width: "65%" }}>
            <span className="sr-only">{name}</span>
          </div>
          <div className="line short">
            <span className="sr-only">{timestamp}</span>
          </div>
        </div>
      </div>

      {body && <p style={{ margin: "0 0 16px", fontSize: "0.95rem" }}>{body}</p>}

      <div className="feed-actions">
        <button onClick={onLike}>&#9825; {likeCount}</button>
        <button onClick={onComment}>&#128172; {commentCount}</button>
        <button onClick={onShare}>&#10148; Share</button>
      </div>
    </div>
  );
}

/* ---------- Activity Row (compact list item) ---------- */
export function ActivityRow({ avatarColor = "grey", label, liked = false }) {
  return (
    <div className="activity-row">
      <div
        className={`feed-avatar ${avatarColor}`}
        style={{ width: 36, height: 36 }}
      />
      <div className="feed-lines">
        <div className="line" style={{ width: "70%" }}>
          <span className="sr-only">{label}</span>
        </div>
      </div>
      <span className={`heart ${liked ? "" : "muted"}`}>&#9829;</span>
    </div>
  );
}

/* ---------- Color Swatch (for style-guide pages) ---------- */
export function Swatch({ name, hex, onLight = false }) {
  return (
    <div
      className={`swatch ${onLight ? "on-light" : ""}`}
      style={{ background: hex }}
    >
      {name}
      <br />
      {hex}
    </div>
  );
}
