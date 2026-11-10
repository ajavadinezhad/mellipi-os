"use strict";
// Restore only validated color values before styles paint; no network or workers.
(() => {
  const keys = ["background", "surface", "raised", "hover", "border", "text", "muted", "faint"];
  const color = value => typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);
  const valid = row => row && /^[a-z][a-z0-9-]{0,31}$/.test(row.id) && ["dark", "light"].includes(row.mode) && color(row.accent) && row.palette && keys.every(key => color(row.palette[key]));
  const properties = {background: "bg", surface: "surface", raised: "raised", hover: "hover", border: "line", text: "ink", muted: "muted", faint: "faint"};
  const apply = (row, remember = false) => {
    if (!valid(row)) return false;
    const root = document.documentElement;
    keys.forEach(key => root.style.setProperty(`--${properties[key]}`, row.palette[key]));
    root.style.setProperty("--accent", row.accent);
    const rgb = row.accent.slice(1).match(/../g).map(value => parseInt(value, 16) / 255);
    const linear = value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
    const luminance = .2126 * linear(rgb[0]) + .7152 * linear(rgb[1]) + .0722 * linear(rgb[2]);
    const brightness = hex => { const values = hex.slice(1).match(/../g).map(value => linear(parseInt(value, 16) / 255)); return .2126 * values[0] + .7152 * values[1] + .0722 * values[2]; };
    const ratio = (a, b) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    const surfaces = [row.palette.background, row.palette.surface, row.palette.raised].map(brightness);
    // Keep exact accent fills, with readable text/focus on pale themes.
    root.style.setProperty("--accent-ink", surfaces.every(value => ratio(luminance, value) >= 4.5) ? row.accent : row.palette.text);
    root.style.setProperty("--focus", surfaces.every(value => ratio(luminance, value) >= 3) ? row.accent : row.palette.text);
    root.style.setProperty("--accent-text", luminance > .179 ? "#000000" : "#ffffff");
    root.style.colorScheme = row.mode;
    root.dataset.theme = row.id;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = row.palette.background;
    if (remember) {
      try { localStorage.setItem("abstract-site-theme", JSON.stringify(row)); } catch { /* Private browsing may forbid storage. */ }
    }
    return true;
  };
  window.AbstractSiteTheme = {valid, apply};
  try { apply(JSON.parse(localStorage.getItem("abstract-site-theme"))); } catch { /* Keep the default palette. */ }
})();
