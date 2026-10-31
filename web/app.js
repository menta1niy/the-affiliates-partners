/* Minimal client: no tokens in localStorage and no trust in initDataUnsafe. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const tg = window.Telegram?.WebApp;
  const status = $("connection-status");
  const details = $("connection-details");
  const indicator = $("indicator");
  const button = $("refresh-button");

  function telegramData() {
    if (tg?.initData) return tg.initData;
    for (const part of [location.hash.slice(1), location.search.slice(1)]) {
      const data = new URLSearchParams(part).get("tgWebAppData");
      if (data) return data;
    }
    return "";
  }

  function showStatus(kind, title, description) {
    status.textContent = title;
    details.textContent = description;
    indicator.className = "circle-indicator " + kind;
  }

  function profile(user, role) {
    const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
    $("profile-name").textContent = name || "Партнёр";
    $("profile-username").textContent = user.username ? "@" + user.username : "Без имени пользователя";
    $("avatar").textContent = (user.first_name || "П").slice(0, 1).toUpperCase();
    $("profile-id").textContent = String(user.id);
    $("profile-role").textContent = role === "owner" ? "Владелец" : "Партнёр";
    $("hero-title").textContent = "Добро пожаловать, " + (user.first_name || "партнёр") + ".";
    $("hero-description").textContent = "Telegram подтвердил ваш вход. Новый кабинет готов к подключению следующих функций.";
  }

  async function connect() {
    showStatus("pending", "Проверяем данные входа…", "Сверяем подпись Telegram с сервером.");
    button.disabled = true;
    try {
      const data = telegramData();
      if (!data) {
        showStatus("unavailable", "Данные входа не получены", "Откройте Mini App кнопкой внутри Telegram-бота. В обычном браузере вход недоступен.");
        return;
      }
      const result = await fetch("/partners/api/session", {
        method: "POST",
        cache: "no-store",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({initData: data}),
      });
      const body = await result.json().catch(() => ({}));
      if (!result.ok || !body.user || body.source !== "telegram") {
        throw new Error(typeof body.error === "string" ? body.error : "Не удалось подтвердить вход");
      }
      profile(body.user, body.role);
      showStatus("connected", "Подключено", "Вход подтверждён сервером Telegram. Данные пользователя получены из проверенной подписи.");
    } catch (error) {
      showStatus("unavailable", "Не удалось подключиться", error instanceof Error ? error.message : "Проверка завершилась ошибкой.");
    } finally {
      button.disabled = false;
    }
  }

  function setTab(name) {
    const overview = name === "overview";
    $("panel-overview").hidden = !overview;
    $("panel-profile").hidden = overview;
    for (const tab of ["overview", "profile"]) {
      const active = tab === name;
      $("tab-" + tab).classList.toggle("active", active);
      if (active) $("tab-" + tab).setAttribute("aria-current", "page");
      else $("tab-" + tab).removeAttribute("aria-current");
    }
  }

  $("tab-overview").addEventListener("click", () => setTab("overview"));
  $("tab-profile").addEventListener("click", () => setTab("profile"));
  button.addEventListener("click", connect);
  try {
    tg?.ready();
    tg?.expand();
    tg?.setHeaderColor?.("#f7f7f2");
  } catch {
    // The app remains usable in clients without these cosmetic capabilities.
  }
  connect();
})();
