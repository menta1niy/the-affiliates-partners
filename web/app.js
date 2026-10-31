(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const tg = window.Telegram?.WebApp;
  const roleLabels = {owner:"Владелец",admin:"Администратор",staff:"Сотрудник",referrer:"Реферер",lead:"Участник"};
  const statusLabels = {pending:"На рассмотрении",approved:"Подтверждён",active:"Активен",rejected:"Отклонён",blocked:"Заблокирован",invited:"Не зарегистрирован",unregistered:"Не зарегистрирован",new:"Не зарегистрирован"};
  let current = null;
  function initData() {
    if (tg?.initData) return tg.initData;
    for (const part of [location.hash.slice(1),location.search.slice(1)]) {
      const value = new URLSearchParams(part).get("tgWebAppData");
      if (value) return value;
    }
    return "";
  }
  async function api(path, values = {}) {
    const result = await fetch("/partners/api" + path, {method:"POST",cache:"no-store",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:initData(),...values})});
    const data = await result.json().catch(() => ({}));
    if (!result.ok) throw new Error(data.error || data.message || "Ошибка запроса (" + result.status + ")");
    return data;
  }
  function show(id, visible) { $(id).hidden = !visible; }
  function error(message) { $("error").textContent = message || "";show("error",Boolean(message)); }
  function text(id,value) { $(id).textContent = value == null || value === "" ? "—" : String(value); }
  function statusInfo(status) {
    const key = String(status || "unregistered").toLowerCase();
    const descriptions = {pending:"Заявка ожидает решения модератора. Доступ к предложениям пока закрыт.",approved:"Аккаунт подтверждён. Доступ зависит от действующих предложений и вашей роли.",active:"Ваш аккаунт активен.",rejected:"Заявка отклонена. Для уточнения причины обратитесь к команде.",blocked:"Доступ к аккаунту приостановлен.",invited:"Чтобы продолжить, отправьте заявку с кодом приглашения.",unregistered:"Чтобы продолжить, отправьте заявку с кодом приглашения."};
    return {key,label:statusLabels[key] || key,description:descriptions[key] || "Для уточнения статуса обратитесь к администратору."};
  }
  function referralUrl(response) {
    if (typeof response.url === "string") return response.url;
    if (typeof response.link === "string") return response.link;
    if (typeof response.referral_link === "string") return response.referral_link;
    if (typeof response.code === "string" && /^ref_[a-zA-Z0-9_-]{8,48}$/.test(response.code)) return "https://t.me/affiliates_partners_bot?start=" + encodeURIComponent(response.code);
    return "";
  }
  async function loadReferral() {
    show("referral-panel",false);
    try {
      const result = await api("/invitations/referral");
      const link = referralUrl(result);
      if (!link || !/^https:\/\//i.test(link)) return;
      $("referral-link").value = link;
      show("referral-panel",true);
    } catch { /* Server decides whether this role can invite. */ }
  }
  function renderOffers(session, status) {
    const el = $("offers");
    el.replaceChildren();
    const paragraph = document.createElement("p");
    paragraph.className = "muted";
    const offers = Array.isArray(session.offers) ? session.offers : [];
    if (!["approved","active"].includes(status)) paragraph.textContent = "Предложения закрыты до подтверждения регистрации.";
    else if (!offers.length) paragraph.textContent = "Сейчас нет опубликованных для вас банковских предложений.";
    else {
      const list = document.createElement("div");list.className="offer-list";
      offers.forEach(offer => {
        if (!offer || typeof offer !== "object") return;
        const item = document.createElement("article");item.className="offer-item";
        const title = document.createElement("h3");title.textContent=String(offer.title || offer.name || "Банковское предложение");
        const summary = document.createElement("p");summary.textContent=String(offer.description || "Подробности доступны после выбора предложения.");
        item.append(title,summary);
        if (typeof offer.url === "string" && /^https:\/\//.test(offer.url)) {
          const link=document.createElement("a");link.className="btn ghost";link.textContent="Подробнее ↗";link.href=offer.url;link.target="_blank";link.rel="noopener noreferrer";item.append(link);
        }
        list.append(item);
      });
      el.append(list);return;
    }
    el.append(paragraph);
  }
  function render(session) {
    current = session;
    const user = session.user || {};
    const role = session.role || user.role || "user";
    const rawStatus = session.status || user.status || (session.registered === false ? "unregistered" : "unregistered");
    const state = statusInfo(rawStatus);
    show("connect",false);show("account",true);
    const unregistered = ["invited","unregistered","new","not_registered"].includes(state.key);
    show("register-panel",unregistered);
    text("welcome",user.first_name ? "Здравствуйте, " + user.first_name : "Личный кабинет");
    text("hero-status",state.label);text("status-pill",state.label);text("status-title",state.label);
    text("status-description",state.description);
    $("status-pill").dataset.status=state.key;
    text("profile-name",[user.first_name,user.last_name].filter(Boolean).join(" ") || user.username);
    text("profile-id",user.id);text("profile-role",roleLabels[role] || role);text("profile-status",state.label);
    const source = session.source_info || session.attribution || session.invitation || (user.referrer_id ? {inviter_id:user.referrer_id,description:"Реферальное приглашение"} : user.agency_id ? {inviter_id:user.agency_id,description:"Приглашение от агентства"} : {});
    const sourceLabel = typeof source === "object" ? (source.name || source.label || source.inviter_name || source.code) : source;
    text("source-title",sourceLabel || session.invited_by_name || "Не указан");
    text("source-details",typeof source === "object" ? [source.description,source.inviter_id ? "ID: " + source.inviter_id : ""].filter(Boolean).join(" · ") || "Источник приглашения ещё не указан." : "Источник регистрации");
    show("admin-link",["owner","admin","staff"].includes(role) && ["approved","active"].includes(state.key));
    renderOffers(session,state.key);
    if (["approved","active"].includes(state.key)) loadReferral(); else show("referral-panel",false);
  }
  async function refresh() {
    const button = $("refresh");button.disabled=true;
    error("");
    try {
      if (!initData()) {
        show("connect",true);show("account",false);show("register-panel",false);
        text("hero-status","Нужен вход через Telegram");return;
      }
      text("hero-status","Проверяем доступ…");
      const session = await api("/session");
      if (!session.user || session.source !== "telegram") throw new Error("Сессия не подтверждена сервером");
      render(session);
    } catch(e) {
      error(e.message);text("hero-status","Не удалось проверить вход");
    } finally {button.disabled=false;}
  }
  $("register-form").addEventListener("submit",async event => {
    event.preventDefault();error("");
    const button=$("register-submit");button.disabled=true;
    try {
      await api("/register",{invite_code:$("invite-code").value.trim(),consent:$("consent").checked});
      text("registration-message","Заявка отправлена.");
      await refresh();
    } catch(e) {text("registration-message",e.message);} finally {button.disabled=false;}
  });
  $("copy-referral").addEventListener("click",async () => {
    const link=$("referral-link").value;
    if (!link) return;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(link);
      else if (tg?.showPopup) {tg.showPopup({message:link,buttons:[{type:"ok"}]});return;}
      else throw new Error("Не удалось скопировать ссылку");
      text("referral-message","Ссылка скопирована.");
    } catch(e) {text("referral-message",e.message);}
  });
  $("refresh").addEventListener("click",refresh);
  try {tg?.ready();tg?.expand();tg?.setHeaderColor?.("#111310");} catch {}
  const start = tg?.initDataUnsafe?.start_param || new URLSearchParams(location.search).get("startapp") || "";
  if (/^[a-zA-Z0-9_-]{1,128}$/.test(start)) $("invite-code").value=start;
  refresh();
})();
