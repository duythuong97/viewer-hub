// Material 3 design system for every Viewer Hub page (docs/GUIDELINE.md §4).
// Loaded as /static/dist/md.js (type=module) + /static/dist/md.css.

import '@fontsource/roboto/300.css';
import '@fontsource/roboto/400.css';
import '@fontsource/roboto/500.css';
import '@fontsource/roboto/700.css';
import '@fontsource/roboto-mono/300.css';
import '@fontsource/roboto-mono/400.css';
import 'material-symbols/outlined.css';
import './tokens.css';
import './typescale.css';
import './md.css';

// Components from @material/web used across the app. Add new ones here, never from a CDN.
import '@material/web/button/filled-button.js';
import '@material/web/button/filled-tonal-button.js';
import '@material/web/button/outlined-button.js';
import '@material/web/button/text-button.js';
import '@material/web/iconbutton/icon-button.js';
import '@material/web/iconbutton/filled-icon-button.js';
import '@material/web/iconbutton/filled-tonal-icon-button.js';
import '@material/web/iconbutton/outlined-icon-button.js';
import '@material/web/fab/fab.js';
import '@material/web/icon/icon.js';
import '@material/web/textfield/outlined-text-field.js';
import '@material/web/textfield/filled-text-field.js';
import '@material/web/select/outlined-select.js';
import '@material/web/select/select-option.js';
import '@material/web/checkbox/checkbox.js';
import '@material/web/switch/switch.js';
import '@material/web/radio/radio.js';
import '@material/web/slider/slider.js';
import '@material/web/chips/chip-set.js';
import '@material/web/chips/assist-chip.js';
import '@material/web/chips/filter-chip.js';
import '@material/web/chips/input-chip.js';
import '@material/web/chips/suggestion-chip.js';
import '@material/web/dialog/dialog.js';
import '@material/web/divider/divider.js';
import '@material/web/list/list.js';
import '@material/web/list/list-item.js';
import '@material/web/menu/menu.js';
import '@material/web/menu/menu-item.js';
import '@material/web/progress/linear-progress.js';
import '@material/web/progress/circular-progress.js';
import '@material/web/tabs/tabs.js';
import '@material/web/tabs/primary-tab.js';
import '@material/web/tabs/secondary-tab.js';
import '@material/web/elevation/elevation.js';
import '@material/web/ripple/ripple.js';
import '@material/web/focus/md-focus-ring.js';

import { applyTheme, cycleTheme, currentTheme } from './theme.js';
import { snackbar } from './snackbar.js';

applyTheme(currentTheme());

// <md-icon-button data-action="theme"> anywhere toggles light / dark / system.
document.addEventListener('click', (event) => {
  const trigger = event.target.closest?.('[data-action="theme"]');
  if (!trigger) return;
  const next = cycleTheme();
  const icon = trigger.querySelector('md-icon');
  if (icon) icon.textContent = { light: 'light_mode', dark: 'dark_mode', system: 'brightness_auto' }[next];
  snackbar({ light: 'Giao diện sáng', dark: 'Giao diện tối', system: 'Theo hệ thống' }[next]);
});

// Server-rendered flash messages: <div data-snackbar="...">.
window.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-snackbar]').forEach((node) => snackbar(node.dataset.snackbar));
  const icon = document.querySelector('[data-action="theme"] md-icon');
  if (icon) icon.textContent = { light: 'light_mode', dark: 'dark_mode', system: 'brightness_auto' }[currentTheme()];
});

// @material/web selects rendered by the server with <md-select-option selected> do not show
// their value until it is set again after upgrade; re-apply it once per select.
async function syncSelects(root = document) {
  await customElements.whenDefined('md-outlined-select');
  for (const select of root.querySelectorAll('md-outlined-select, md-filled-select')) {
    await select.updateComplete;
    const value = select.querySelector('md-select-option[selected]')?.value ?? select.value;
    select.value = '';
    await select.updateComplete;
    select.value = value;
  }
}
window.addEventListener('DOMContentLoaded', () => syncSelects());

window.md = { snackbar, applyTheme, currentTheme, syncSelects };
