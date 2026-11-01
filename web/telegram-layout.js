(() => {
  'use strict';
  const app = window.Telegram?.WebApp;
  if (!app) return;

  const root = document.documentElement;
  const inset = (value) => Math.max(0, Math.min(160, Number(value) || 0));
  const updateInsets = () => {
    const safe = app.safeAreaInset || {};
    const content = app.contentSafeAreaInset || {};
    for (const edge of ['top', 'right', 'bottom', 'left']) {
      root.style.setProperty(`--tg-safe-${edge}`, `${inset(safe[edge])}px`);
      root.style.setProperty(`--tg-content-${edge}`, `${inset(content[edge])}px`);
    }
    root.classList.toggle('tg-fullscreen', app.isFullscreen === true);
  };

  try {
    app.ready();
    app.expand();
    app.disableVerticalSwipes?.();
    app.setHeaderColor?.('#111310');
    app.setBackgroundColor?.('#111310');
    app.setBottomBarColor?.('#111310');
    app.onEvent?.('safeAreaChanged', updateInsets);
    app.onEvent?.('contentSafeAreaChanged', updateInsets);
    app.onEvent?.('fullscreenChanged', updateInsets);
    app.onEvent?.('fullscreenFailed', updateInsets);
    updateInsets();
    if (typeof app.requestFullscreen === 'function') app.requestFullscreen();
  } catch {
    // Older Telegram versions still use expand() and the CSS safe-area fallback.
    updateInsets();
  }
})();
