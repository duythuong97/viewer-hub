// M3 snackbar (not provided by @material/web): one at a time, bottom center.
let host;
let timer;

export function snackbar(message, { action, onAction, timeout = 4000 } = {}) {
  if (!host) {
    host = document.createElement('div');
    host.className = 'md-snackbar';
    host.setAttribute('role', 'status');
    host.setAttribute('aria-live', 'polite');
    document.body.append(host);
  }
  host.replaceChildren();
  const text = document.createElement('span');
  text.className = 'md-snackbar__text';
  text.textContent = message;
  host.append(text);
  if (action) {
    const button = document.createElement('md-text-button');
    button.className = 'md-snackbar__action';
    button.textContent = action;
    button.addEventListener('click', () => {
      hide();
      onAction?.();
    });
    host.append(button);
  }
  host.classList.add('md-snackbar--open');
  clearTimeout(timer);
  timer = setTimeout(hide, timeout);
}

function hide() {
  host?.classList.remove('md-snackbar--open');
}
