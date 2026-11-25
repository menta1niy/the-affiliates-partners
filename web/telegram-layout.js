(() => {
  'use strict';
  const app = window.Telegram?.WebApp;
  if (!app) return;

  const root = document.documentElement;
  root.classList.add('tg-webapp');
  const inset = (value) => Math.max(0, Math.min(160, Number(value) || 0));
  const optional = (method, ...args) => {
    try { app[method]?.(...args); } catch { /* Optional Telegram API failed. */ }
  };
  const editable = (element) => element?.matches?.('input:not([readonly]):not([disabled]), textarea:not([readonly]):not([disabled]), select:not([disabled]), [contenteditable="true"]');
  const updateKeyboard = () => {
    const editing = Boolean(editable(document.activeElement));
    // iOS Telegram may resize its own content viewport without resizing
    // visualViewport. Focus, not keyboard-height heuristics, owns the dock.
    root.classList.toggle('tg-keyboard-open', editing);
  };
  const updateInsets = () => {
    const safe = app.safeAreaInset || {};
    const content = app.contentSafeAreaInset || {};
    for (const edge of ['top', 'right', 'bottom', 'left']) {
      root.style.setProperty(`--tg-safe-${edge}`, `${inset(safe[edge])}px`);
      root.style.setProperty(`--tg-content-${edge}`, `${inset(content[edge])}px`);
    }
    root.classList.toggle('tg-fullscreen', app.isFullscreen === true);
    updateKeyboard();
  };

  window.visualViewport?.addEventListener('resize', updateKeyboard);
  window.visualViewport?.addEventListener('scroll', updateKeyboard);
  window.addEventListener('resize', updateKeyboard);
  document.addEventListener('focusin', updateKeyboard);
  document.addEventListener('focusout', () => requestAnimationFrame(updateKeyboard));
  document.addEventListener('pointerdown', (event) => {
    if (!editable(document.activeElement) || editable(event.target)) return;
    // Tapping outside a form input dismisses the iOS numeric keypad too.
    if (!event.target.closest('label')) document.activeElement.blur();
  }, {capture:true});
  document.addEventListener('keydown', (event) => {
    if ((event.key === 'Escape' && editable(document.activeElement)) ||
        (event.key === 'Enter' && editable(document.activeElement) && document.activeElement.tagName !== 'TEXTAREA')) {
      if (event.key === 'Escape') event.preventDefault();
      document.activeElement?.blur?.();
    }
  });

  optional('ready');
  optional('expand');
  optional('disableVerticalSwipes');
  optional('setHeaderColor', '#080909');
  optional('setBackgroundColor', '#080909');
  optional('setBottomBarColor', '#080909');
  for (const event of ['safeAreaChanged', 'contentSafeAreaChanged', 'fullscreenChanged', 'fullscreenFailed']) {
    optional('onEvent', event, updateInsets);
  }
  updateInsets();
  // expand() resizes the bottom sheet; fullscreen removes the sheet header.
  // Failure is non-fatal and preserves ordinary CSS safe-area fallbacks.
  if (typeof app.requestFullscreen === 'function' && !app.isFullscreen) {
    try { app.requestFullscreen(); } catch { updateInsets(); }
  }
})();
