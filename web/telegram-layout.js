(() => {
  'use strict';
  const app = window.Telegram?.WebApp;
  if (!app) return;

  const root = document.documentElement;
  root.classList.add('tg-webapp');
  const inset = (value) => Math.max(0, Math.min(160, Number(value) || 0));
  const updateKeyboard = () => {
    const viewport = window.visualViewport;
    const visibleHeight = viewport?.height || window.innerHeight;
    const occlusion = Math.max(0, window.innerHeight - visibleHeight - Math.max(0, viewport?.offsetTop || 0));
    const editing = document.activeElement?.matches?.('input:not([readonly]), textarea, select, [contenteditable="true"]');
    root.classList.toggle('tg-keyboard-open', Boolean(editing && occlusion > 120));
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

  try {
    app.ready();
    app.expand();
    app.disableVerticalSwipes?.();
    app.setHeaderColor?.('#080909');
    app.setBackgroundColor?.('#080909');
    app.setBottomBarColor?.('#080909');
    app.onEvent?.('safeAreaChanged', updateInsets);
    app.onEvent?.('contentSafeAreaChanged', updateInsets);
    app.onEvent?.('fullscreenChanged', updateInsets);
    app.onEvent?.('fullscreenFailed', updateInsets);
    updateInsets();
    // expand() is sufficient: forcing fullscreen on iOS places Telegram's
    // status and navigation overlays on top of a scrolling document.
  } catch {
    // Older Telegram versions still use expand() and the CSS safe-area fallback.
    updateInsets();
  }
})();
