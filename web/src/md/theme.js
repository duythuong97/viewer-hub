// Light / dark / system. The choice is a per-viewer convenience, so localStorage is fine;
// every access is guarded because storage can be blocked by browser policy.
const KEY = 'viewer-hub.theme';
const ORDER = ['system', 'light', 'dark'];

export function currentTheme() {
  try {
    const value = localStorage.getItem(KEY);
    return ORDER.includes(value) ? value : 'system';
  } catch {
    return 'system';
  }
}

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
}

export function cycleTheme() {
  const next = ORDER[(ORDER.indexOf(currentTheme()) + 1) % ORDER.length];
  applyTheme(next);
  return next;
}
