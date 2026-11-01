(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const tg = window.Telegram?.WebApp;
  const roleLabels = {owner:"Владелец",admin:"Администратор",staff:"Сотрудник",referrer:"Реферер",lead:"Участник"};
  const statusLabels = {pending:"На рассмотрении",approved:"Подтверждён",active:"Активен",rejected:"Отклонён",blocked:"Заблокирован",invited:"Не зарегистрирован",unregistered:"Не зарегистрирован",new:"Не зарегистрирован"};
  let current = null;
  let referralRequest = 0;
  let offersRequest = 0;
  let crmStatusRequest = 0;
  const actions={opened:"Открыл предложение",started:"Приступил к заданию",submitted:"Отправил заявку"};
  const applicationStageLabels={applied:"Заявка отправлена",meeting_scheduled:"Назначена встреча",picked_up:"Получено",target_done:"Целевое действие выполнено",credited:"Подтверждено CRM",paid:"Выплата отмечена CRM"};
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
    const descriptions = {pending:"Заявка ожидает решения модератора. Доступ к предложениям пока закрыт.",approved:"Аккаунт подтверждён. Доступ зависит от действующих предложений и вашей роли.",active:"Ваш аккаунт активен.",rejected:"Заявка отклонена. Для уточнения причины обратитесь к команде.",blocked:"Доступ к аккаунту приостановлен.",invited:"Откройте ссылку приглашения через Telegram и отправьте заявку.",unregistered:"Откройте ссылку приглашения через Telegram и отправьте заявку."};
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
    const request = ++referralRequest;
    show("referral-panel",false);
    try {
      const result = await api("/invitations/referral");
      if(request !== referralRequest) return;
      const link = referralUrl(result);
      if (!link || !/^https:\/\//i.test(link)) return;
      $("referral-link").value = link;
      show("referral-panel",true);
    } catch { /* Server decides whether this role can invite. */ }
  }
  function offerMessage(message) {
    const el = $("offers");
    el.replaceChildren();
    const paragraph=document.createElement("p");paragraph.className="muted";paragraph.textContent=message;el.append(paragraph);
  }
  function taskNotice(message) {
    const element = $("task-notice");
    element.textContent = message || "";
    element.hidden = !message;
  }
  function safeHttpsUrl(value) {
    if (typeof value !== "string" || value.length > 2048 || /[\u0000-\u001f\u007f]/.test(value)) return "";
    try {
      const url = new URL(value);
      if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return "";
      return url.href;
    } catch { return ""; }
  }
  function renderPublishedInstructions(item, offer) {
    // Only consume CRM's explicitly published snapshot; never render draft fields.
    const published = offer.published_instruction;
    if (!published || typeof published !== "object" || Array.isArray(published)) return;
    const text = typeof published.text === "string" ? published.text.slice(0, 12000) : "";
    if (text) {
      const paragraph = document.createElement("p");
      paragraph.className = "published-instruction-text";
      paragraph.textContent = text;
      item.append(paragraph);
    }
    const images = Array.isArray(published.images) ? published.images.slice(0, 12) : [];
    const gallery = document.createElement("div");
    gallery.className = "published-instruction-images";
    images.forEach(entry => {
      const url = safeHttpsUrl(typeof entry === "string" ? entry : entry?.url);
      if (!url) return;
      const img = document.createElement("img");
      img.src = url;
      img.alt = typeof entry?.alt === "string" ? entry.alt.slice(0, 160) : "Иллюстрация к инструкции";
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      gallery.append(img);
    });
    if (gallery.childElementCount) item.append(gallery);
    const links = Array.isArray(published.links) ? published.links.slice(0, 20) : [];
    const list = document.createElement("div");
    list.className = "published-instruction-links";
    links.forEach(entry => {
      const url = safeHttpsUrl(typeof entry === "string" ? entry : entry?.url);
      if (!url) return;
      const link = document.createElement("a");
      link.href = url;
      link.textContent = typeof entry?.label === "string" ? entry.label.slice(0, 160) : "Открыть материал";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.referrerPolicy = "no-referrer";
      list.append(link);
    });
    if (list.childElementCount) item.append(list);
  }
  function renderOffers(offers) {
    const el=$("offers");el.replaceChildren();
    if (!offers.length) {offerMessage("CRM не назначила вам доступных предложений.");return;}
    {
      const list = document.createElement("div");list.className="offer-list";
      offers.forEach(offer => {
        if (!offer || typeof offer !== "object") return;
        const item = document.createElement("article");item.className="offer-item";
        const title = document.createElement("h3");title.textContent=String(offer.name || offer.title || "Предложение без названия");
        const summary = document.createElement("p");summary.textContent=offer.published_instruction ? "Опубликованная инструкция CRM:" : String(offer.instructions || "Инструкция CRM не указана.");
        item.append(title,summary);
        renderPublishedInstructions(item,offer);
        const details=[offer.advertiser ? "Рекламодатель: "+offer.advertiser : "",offer.type ? "Тип: "+offer.type : "",offer.target_action ? "Целевое действие: "+offer.target_action : ""].filter(Boolean);
        if(details.length){const info=document.createElement("p");info.className="muted";info.textContent=details.join(" · ");item.append(info);}
        if (typeof offer.referral_url === "string" && /^https:\/\//i.test(offer.referral_url)) {
          const link=document.createElement("a");link.className="btn ghost";link.textContent="Перейти к предложению ↗";link.href=offer.referral_url;link.target="_blank";link.rel="noopener noreferrer";item.append(link);
        }
        if(offer.id !== undefined && offer.id !== null){
          const form=document.createElement("form");form.className="task-report";
          const selection=document.createElement("select");selection.setAttribute("aria-label","Действие по заданию");
          Object.entries(actions).forEach(([value,label])=>{const option=document.createElement("option");option.value=value;option.textContent=label;selection.append(option);});
          const note=document.createElement("input");note.placeholder="Комментарий (необязательно)";note.maxLength=1000;note.setAttribute("aria-label","Комментарий к действию");
          const submit=document.createElement("button");submit.className="btn primary";submit.type="submit";submit.textContent="Сообщить о действии";
          const feedback=document.createElement("p");feedback.className="muted";feedback.setAttribute("role","status");
          form.append(selection,note,submit,feedback);
          form.addEventListener("submit",async event=>{event.preventDefault();submit.disabled=true;taskNotice("");feedback.textContent="Отправляем отчёт…";
            try{await api("/tasks/report",{offer_id:String(offer.id),action:selection.value,note:note.value});taskNotice("Отчёт принят. Подтверждение результата ожидается от CRM.");note.value="";await loadTasks();}
            catch(e){feedback.textContent="Не удалось отправить отчёт: "+e.message;}finally{submit.disabled=false;}});
          item.append(form);
        }
        list.append(item);
      });
      el.append(list);return;
    }
  }
  async function loadOffers() {
    const request=++offersRequest;
    offerMessage("Загружаем назначенные предложения из CRM…");
    try {
      const result=await api("/offers");
      if(request!==offersRequest)return;
      if(!result || !Array.isArray(result.offers))throw new Error("Сервер вернул неполный список предложений.");
      renderOffers(result.offers);
    } catch(e) {
      if(request===offersRequest)offerMessage("Не удалось получить предложения из CRM: "+e.message+". Обновите данные для повторной попытки.");
    }
  }
  function renderHistory(history){
    const container=$("task-history");container.replaceChildren();
    if(!history.length){const p=document.createElement("p");p.className="muted";p.textContent="Отправленных отчётов пока нет.";container.append(p);return;}
    history.forEach(record=>{const item=document.createElement("div");item.className="history-entry";
      const heading=document.createElement("strong");heading.textContent=actions[record.action]||"Действие участника";
      const info=document.createElement("p");info.className="muted";info.textContent="Задание: "+record.offer_id+" · "+new Date(record.created_at*1000).toLocaleString("ru-RU")+" · Отчёт отправлен";
      item.append(heading,info);if(record.note){const note=document.createElement("p");note.textContent=record.note;item.append(note);}container.append(item);
    });
  }
  async function loadTasks(){
    const request=++offersRequest;
    offerMessage("Загружаем задания из CRM…");
    $("task-history").textContent="Загружаем историю…";
    try{const result=await api("/tasks");if(request!==offersRequest)return;
      if(!Array.isArray(result.tasks)||!Array.isArray(result.history))throw new Error("Неполный ответ сервера");
      renderOffers(result.tasks);renderHistory(result.history);
    }catch(e){if(request===offersRequest){offerMessage("Не удалось загрузить задания: "+e.message);$("task-history").textContent="История временно недоступна.";}}
  }
  function renderCrmStatus(result){
    const container=$("crm-state");container.replaceChildren();
    const applications=result.applications,payouts=result.lead_payouts;
    if(!applications.length&&!payouts.length){const p=document.createElement("p");p.className="muted";p.textContent="CRM пока не передала статусы заявок или подтверждённые выплаты.";container.append(p);return;}
    for(const item of applications){
      const row=document.createElement("div");row.className="history-entry";
      const heading=document.createElement("strong");heading.textContent=applicationStageLabels[item.stage]||"Статус CRM";
      const details=document.createElement("p");details.className="muted";details.textContent="Оффер: "+String(item.offer_id||"—");
      row.append(heading,details);container.append(row);
    }
    for(const payout of payouts){
      const row=document.createElement("div");row.className="history-entry";
      const heading=document.createElement("strong");
      heading.textContent=payout.reversed?"Начисление отменено CRM":payout.status==="paid"?"Выплата отмечена CRM":"Вознаграждение подтверждено CRM";
      const details=document.createElement("p");details.className="muted";
      details.textContent="Оффер: "+String(payout.offer_id||"—")+" · Сумма: "+String(payout.amount||"0")+" ₽";
      row.append(heading,details);container.append(row);
    }
  }
  async function loadCrmStatus(){
    const request=++crmStatusRequest;
    $("crm-state").textContent="Загружаем подтверждения CRM…";
    try{const result=await api("/status");if(request!==crmStatusRequest)return;
      if(!Array.isArray(result.applications)||!Array.isArray(result.lead_payouts))throw new Error("Неполный ответ CRM");
      renderCrmStatus(result);
    }catch(e){if(request===crmStatusRequest)$("crm-state").textContent="Не удалось загрузить статусы CRM: "+e.message;}
  }
  function render(session) {
    current = session;
    window.renderOwnerLeadPreview?.(session);
    taskNotice("");
    const user = session.user || {};
    const role = session.role || user.role || "user";
    const rawStatus = session.status || user.status || (session.registered === false ? "unregistered" : "unregistered");
    const state = statusInfo(rawStatus);
    show("connect",false);show("account",true);
    const unregistered = ["invited","unregistered","new","not_registered"].includes(state.key);
    show("register-panel",unregistered);
    const verifiedInvite = Boolean(session.source_info?.inviter_id);
    show("register-form",unregistered && verifiedInvite);
    text("registration-instructions",verifiedInvite ? "Источник приглашения подтверждён Telegram. Проверьте данные и отправьте заявку." : "Чтобы подать заявку, откройте персональную ссылку приглашения через Telegram, затем вернитесь в кабинет и обновите данные. Ввод одного кода не подтверждает источник.");
    text("welcome",user.first_name ? "Здравствуйте, " + user.first_name : "Личный кабинет");
    text("hero-status",state.label);text("status-pill",state.label);text("status-title",state.label);
    text("status-description",state.description);
    $("status-pill").dataset.status=state.key;
    text("profile-name",[user.first_name,user.last_name].filter(Boolean).join(" ") || user.username);
    text("profile-id",user.id);text("profile-internal-id",user.internal_id == null ? "После регистрации" : user.internal_id);text("profile-role",roleLabels[role] || role);text("profile-status",state.label);
    const source = session.source_info || session.attribution || session.invitation || (user.source==="referral" ? {description:"Реферальное приглашение"} : user.source==="agency" ? {description:"Приглашение от агентства"} : {});
    const sourceLabel = typeof source === "object" ? (source.name || source.label || source.inviter_name || source.description || source.code) : source;
    text("source-title",sourceLabel || session.invited_by_name || "Не указан");
    text("source-details",typeof source === "object" ? [source.description,user.introduced_by_id ? "Пригласил ID: " + user.introduced_by_id : (unregistered && source.inviter_id ? "Источник подтверждён ID: " + source.inviter_id : ""),user.agency_id ? "Агентство ID: " + user.agency_id : "",user.referrer_id ? "Реферер ID: " + user.referrer_id : "",user.manager_id ? "Менеджер ID: " + user.manager_id : ""].filter(Boolean).join(" · ") || "Источник приглашения ещё не указан." : "Источник регистрации");
    show("admin-link",["owner","admin","staff"].includes(role) && ["approved","active"].includes(state.key));
    if (["approved","active"].includes(state.key)){loadTasks();loadCrmStatus();}
    else {++offersRequest;++crmStatusRequest;offerMessage("Предложения недоступны до подтверждения регистрации.");$("task-history").textContent="История недоступна до подтверждения регистрации.";$("crm-state").textContent="Статусы CRM недоступны до подтверждения регистрации.";}
    if (["approved","active"].includes(state.key)) loadReferral(); else {++referralRequest;show("referral-panel",false);}
  }
  async function refresh() {
    const button = $("refresh");button.disabled=true;
    error("");
    try {
      if (!initData()) {
        taskNotice("");
        ++offersRequest;++crmStatusRequest;
        ++referralRequest;show("referral-panel",false);
        show("connect",true);show("account",false);show("register-panel",false);
        text("hero-status","Нужен вход через Telegram");return;
      }
      text("hero-status","Проверяем доступ…");
      const session = await api("/session");
      if (!session.user || session.source !== "telegram") throw new Error("Сессия не подтверждена сервером");
      render(session);
    } catch(e) {
      taskNotice("");
      ++offersRequest;++crmStatusRequest;
      ++referralRequest;
      show("account",false);show("register-panel",false);show("referral-panel",false);
      show("connect",true);
      error(e.message);text("hero-status","Не удалось проверить вход");
    } finally {button.disabled=false;}
  }
  $("register-form").addEventListener("submit",async event => {
    event.preventDefault();error("");
    const button=$("register-submit");button.disabled=true;
    try {
      await api("/register",{consent:$("consent").checked});
      text("registration-message","Заявка отправлена.");
      await refresh();
    } catch(e) {
      text("registration-message",e.message);
    } finally {button.disabled=false;}
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
  refresh();
})();
