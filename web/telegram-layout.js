(() => {
  'use strict';
  const app = window.Telegram?.WebApp;
  if (!app) return;

  const root = document.documentElement;
  root.classList.add('tg-webapp');
  const inset = (value) => Math.max(0, Math.min(160, Number(value) || 0));
  let doneButton;
  const editable = (element) => element?.matches?.('input:not([readonly]):not([disabled]), textarea:not([readonly]):not([disabled]), select:not([disabled]), [contenteditable="true"]');
  const ensureDoneButton = () => {
    if (doneButton || !document.body) return;
    doneButton = document.createElement('button');
    doneButton.type = 'button';
    doneButton.className = 'tg-keyboard-done';
    doneButton.textContent = 'Готово';
    doneButton.setAttribute('aria-label', 'Закрыть клавиатуру');
    doneButton.hidden = true;
    doneButton.addEventListener('pointerdown', (event) => event.preventDefault());
    doneButton.addEventListener('click', () => {
      document.activeElement?.blur?.();
      updateKeyboard();
    });
    document.body.append(doneButton);
  };
  const updateKeyboard = () => {
    ensureDoneButton();
    const viewport = window.visualViewport;
    const visibleHeight = viewport?.height || window.innerHeight;
    const occlusion = Math.max(0, window.innerHeight - visibleHeight - Math.max(0, viewport?.offsetTop || 0));
    const editing = Boolean(editable(document.activeElement));
    // iOS Telegram may resize its own content viewport without resizing
    // visualViewport. Focus, not keyboard-height heuristics, owns the dock.
    root.classList.toggle('tg-keyboard-open', editing);
    // If Telegram does not report a keyboard resize, keep "Готово" in the
    // visible upper half rather than underneath the iOS numeric keyboard.
    root.style.setProperty('--tg-keyboard-done-top', `${Math.max(75, (viewport?.offsetTop || 0) + Math.min(visibleHeight - 52, window.innerHeight * .53))}px`);
    if (doneButton) doneButton.hidden = !editing;
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
    if (!editable(document.activeElement) || editable(event.target) || event.target === doneButton) return;
    // Tapping outside a form input dismisses the iOS numeric keypad too.
    if (!event.target.closest('label')) document.activeElement.blur();
  }, {capture:true});
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' || (event.key === 'Enter' && editable(document.activeElement) && document.activeElement.tagName !== 'TEXTAREA')) {
      if (event.key === 'Escape') event.preventDefault();
      document.activeElement?.blur?.();
    }
  });

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
    // expand() only expands Telegram's bottom sheet. The fullscreen request
    // removes the persistent sheet header so the Mini App looks native.
    // Telegram may reject it on older clients; keep the normal layout as a
    // fallback, and apply content safe-area padding on fullscreenChanged.
    if (typeof app.requestFullscreen === 'function' && !app.isFullscreen) {
      try { app.requestFullscreen(); } catch { updateInsets(); }
    }
  } catch {
    // Older Telegram versions still use expand() and the CSS safe-area fallback.
    updateInsets();
  }
})();
