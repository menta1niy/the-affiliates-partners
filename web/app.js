(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const tg = window.Telegram?.WebApp;
  const roleLabels = {owner:"Владелец",admin:"Администратор",staff:"Сотрудник",referrer:"Реферер",lead:"Участник",blogger:"Блогер"};
  const statusLabels = {pending:"На рассмотрении",approved:"Подтверждён",active:"Активен",rejected:"Отклонён",blocked:"Заблокирован",invited:"Не зарегистрирован",unregistered:"Не зарегистрирован",new:"Не зарегистрирован"};
  let current = null;
  let bloggerRequestId=0;
  const kopeksMoney = value=>{
    const amount=Number(value);
    if(!Number.isSafeInteger(amount)||amount<0)return "—";
    return new Intl.NumberFormat("ru-RU",{minimumFractionDigits:2,maximumFractionDigits:2}).format(amount/100)+" ₽";
  };
  async function loadBlogger(){
    const request=++bloggerRequestId;
    try{
      const data=await api("/blogger/overview");
      if(request!==bloggerRequestId)return;
      text("blogger-id",data.display_id);
      text("blogger-channel",data.channel);
      text("blogger-invited",data.invited_count);
      text("blogger-earned",kopeksMoney(data.earned_kopeks));
      text("blogger-paid",kopeksMoney(data.paid_kopeks));
      text("blogger-available",kopeksMoney(data.available_kopeks));
      text("blogger-terms","Фиксированное размещение: "+money(data.fixed_rub)+
        " · процент от фактических выплат приглашённым: "+
        new Intl.NumberFormat("ru-RU",{maximumFractionDigits:2}).format(data.percent_bps/100)+"%.");
      $("blogger-link").value=data.active && /^blog_[A-Za-z0-9_-]{8,48}$/.test(data.invite_code)
        ?"https://t.me/affialite_partners_bot?start="+encodeURIComponent(data.invite_code):"";
      const history=$("blogger-history");history.replaceChildren();
      const labels={fixed:"Фиксированное размещение",percent:"Процентное начисление"};
      if(!data.rewards?.length){
        const info=document.createElement("p");info.className="muted";
        info.textContent="Подтверждённых начислений пока нет.";history.append(info);
      }
      for(const reward of data.rewards||[]){
        const item=document.createElement("div");item.className="participant-finance-history-item";
        const name=document.createElement("strong");
        name.textContent=kopeksMoney(reward.amount_kopeks)+" · "+(labels[reward.kind]||"Рекламное начисление");
        const status=document.createElement("small");
        status.textContent=reward.status==="paid"?"Выплачено":"Ожидает фактической выплаты";
        item.append(name,status);history.append(item);
      }
    }catch(e){
      if(request===bloggerRequestId)text("blogger-copy-feedback","Ошибка загрузки: "+e.message);
    }
  }
  let financeRequestId=0;
  let financeAvailableRub=null;
  let statisticsRequestId=0;
  const money = value => Number.isSafeInteger(Number(value))
    ? new Intl.NumberFormat("ru-RU").format(Number(value))+" ₽" : "—";
  async function loadStatistics(){
    const id=++statisticsRequestId;
    const fields=["statistics-not-started","statistics-in-work","statistics-hold",
      "statistics-available","statistics-reserved","statistics-paid","statistics-accrued"];
    for(const field of fields)text(field,"…");
    text("statistics-feedback","Обновляем статистику…");
    try{
      const result=await api("/statistics/overview");
      if(id!==statisticsRequestId)return;
      const potential=result.potential||{};
      const verified=result.verified||{};
      const mapping={
        "statistics-not-started":potential.not_started_rub,
        "statistics-in-work":potential.in_work_rub,
        "statistics-hold":potential.hold_rub,
        "statistics-available":verified.available_rub,
        "statistics-reserved":verified.reserved_rub,
        "statistics-paid":verified.paid_rub,
        "statistics-accrued":verified.accrued_rub
      };
      for(const [field,value] of Object.entries(mapping))text(field,
        Number.isSafeInteger(value)&&value>=0?money(value):"—");
      const counts=$("statistics-counts");counts.replaceChildren();
      const stages=result.stages||{};
      for(const [label,key] of [["Назначено","assigned"],["В работе","in_progress"],
        ["На проверке","submitted"],["Завершено","completed"],["Отклонено","rejected"]]){
        const item=document.createElement("div");
        const caption=document.createElement("span");caption.textContent=label;
        const value=document.createElement("strong");
        value.textContent=Number.isSafeInteger(stages[key])&&stages[key]>=0?String(stages[key]):"—";
        item.append(caption,value);counts.append(item);
      }
      text("statistics-feedback","Показатели рассчитаны по текущему состоянию назначений и финансов.");
    }catch(e){
      if(id!==statisticsRequestId)return;
      for(const field of fields)text(field,"—");
      $("statistics-counts").replaceChildren();
      text("statistics-feedback","Не удалось загрузить статистику: "+e.message);
    }
  }
  async function loadFinance(){
    const id=++financeRequestId;
    const fields=["finance-available","finance-reserved","finance-paid","finance-accrued"];
    for(const field of fields)text(field,"Загрузка…");
    financeAvailableRub=null;
    $("finance-request-submit").disabled=true;
    $("finance-request-amount").removeAttribute("max");
    text("finance-load-status","Проверяем подтверждённый баланс…");
    show("finance-load-status",true);
    const renderRows=(target,items,kind)=>{
      const root=$(target);root.replaceChildren();
      if(!items?.length){const p=document.createElement("p");p.className="muted";
        p.textContent="Записей пока нет.";root.append(p);return;}
      const labels={pending:"На рассмотрении",confirmed:"Подтверждена",
        rejected:"Отклонена",paid:"Выплачена"};
      for(const entry of items){
        const item=document.createElement("div");item.className="participant-finance-history-item";
        const title=document.createElement("strong");
        title.textContent=money(entry.amount_rub)+" · "+
          (kind==="withdrawals"?(labels[entry.status]||entry.status):"Подтверждённое начисление");
        const detail=document.createElement("small");detail.textContent=kind==="withdrawals"
          ?(entry.review_note||"Заявка № "+entry.id.slice(-8))
          :"Основание: "+entry.source_reference;
        item.append(title,detail);root.append(item);
      }
    };
    try{
      const data=await api("/finance/overview");
      if(id!==financeRequestId)return;
      if(!data?.balances || !["available_rub","reserved_rub","paid_rub","accrued_rub"].every(key=>
        Number.isSafeInteger(data.balances[key]) && data.balances[key]>=0))
        throw new Error("Сервер вернул неполные данные о балансе.");
      text("finance-available",money(data.balances.available_rub));
      text("finance-reserved",money(data.balances.reserved_rub));
      text("finance-paid",money(data.balances.paid_rub));
      text("finance-accrued",money(data.balances.accrued_rub));
      financeAvailableRub=data.balances.available_rub;
      $("finance-request-amount").max=String(Math.min(10000000,financeAvailableRub));
      $("finance-request-submit").disabled=financeAvailableRub<1;
      show("finance-load-status",false);
      text("finance-request-feedback",financeAvailableRub<1?"Запрос станет доступен после подтверждённого начисления.":"");
      renderRows("finance-withdrawals",data.withdrawals,"withdrawals");
      renderRows("finance-accruals",data.accruals,"accruals");
      const ref=data.referral;
      if(ref){
        show("participant-referral-summary",true);
        text("referral-invited",ref.invited_count);
        text("referral-earned",kopeksMoney(ref.earned_kopeks));
        const root=$("referral-rewards");root.replaceChildren();
        for(const reward of ref.rewards||[]){
          const item=document.createElement("div");item.className="participant-finance-history-item";
          const heading=document.createElement("strong");
          heading.textContent=kopeksMoney(reward.amount_kopeks)+" · "+reward.referred_display_id;
          const detail=document.createElement("small");
          detail.textContent="15% после фактической выплаты приглашённого";
          item.append(heading,detail);root.append(item);
        }
      }
    }catch(err){
      if(id!==financeRequestId)return;
      financeAvailableRub=null;
      $("finance-request-submit").disabled=true;
      text("finance-available","—");text("finance-reserved","—");text("finance-paid","—");text("finance-accrued","—");
      text("finance-load-status","Баланс временно недоступен. Обновите страницу и повторите попытку.");
      show("finance-load-status",true);
      text("finance-request-feedback","Запрос выплаты недоступен до загрузки подтверждённого баланса.");
    }
  }
  const gateReasons={
    underage:"Оформление недоступно до 18 лет. Реферальные приглашения остаются доступны.",
    identity:"Сначала заполните ФИО и ИНН в профиле.",
    credit_review:"Перед оформлением обновите кредитную анкету в профиле.",
    registration:"Завершите регистрацию и дождитесь одобрения.",
    mfo_request:"Для оформления МФО сначала запросите оффер и дождитесь решения менеджера."
  };
  function unavailableReason(offer){
    return offer?.can_apply===false ? gateReasons[offer.unavailable_reason]||"Оформление сейчас недоступно." : "";
  }
  let referralRequest = 0;
  let offersRequest = 0;
  let crmStatusRequest = 0;
  let participantTabsEnabled = false;
  let participantView = "home";
  const participantViews = {home:"participant-home",offers:"participant-offers-view",statistics:"participant-statistics-view",profile:"participant-profile-view"};
  function setParticipantView(view, addHistory = false) {
    if (!participantTabsEnabled || !Object.hasOwn(participantViews, view)) return;
    if (addHistory && view !== participantView) history.pushState({...history.state,participantView:view},"",location.href);
    participantView = view;
    for (const [name,id] of Object.entries(participantViews)) show(id,name===view);
    if(view==="statistics")loadStatistics();
    document.querySelectorAll("#participant-nav [data-view]").forEach(link=>{
      if(link.dataset.view===view)link.setAttribute("aria-current","page");
      else link.removeAttribute("aria-current");
    });
    document.title={
      home:"The Affiliates — Главная",
      offers:"The Affiliates — Офферы",
      statistics:"The Affiliates — Статистика",
      profile:"The Affiliates — Профиль"
    }[view];
    try { if(view==="home") tg?.BackButton?.hide(); else tg?.BackButton?.show(); } catch {}
    window.scrollTo({top:0,behavior:"instant"});
  }
  function setParticipantTabsEnabled(enabled) {
    participantTabsEnabled=enabled;
    show("participant-nav",enabled);
    show("participant-next-action",enabled);
    if(enabled)setParticipantView(participantView);
    else {
      for(const id of Object.values(participantViews)) show(id,true);
      try {tg?.BackButton?.hide();} catch {}
    }
  }
  document.querySelectorAll("[data-view],[data-go-view]").forEach(link=>link.addEventListener("click",event=>{
    if(!participantTabsEnabled)return;
    event.preventDefault();setParticipantView(link.dataset.view||link.dataset.goView,true);
  }));
  addEventListener("popstate",event=>setParticipantView(event.state?.participantView||"home"));
  try {tg?.BackButton?.onClick?.(()=>{if(participantTabsEnabled && participantView!=="home")history.back();});} catch {}
  function nextStep(title,description,buttonLabel="Посмотреть офферы →"){
    text("participant-next-title",title);
    text("participant-next-description",description);
    text("participant-next-action",buttonLabel);
  }
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
  function displayRegistrationId(user){
    if(typeof user?.display_id==="string" && /^L-[0-9]{6,}$/.test(user.display_id))return user.display_id;
    const numeric=Number(user?.internal_id);
    if(!Number.isSafeInteger(numeric)||numeric<=0)return "—";
    return ["lead","referrer"].includes(user?.role)
      ?"L-"+String(numeric).padStart(6,"0")
      :String(numeric);
  }
  function ageFromBirthDate(value){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;
    const [year,month,day]=value.split("-").map(Number);
    const parsed=new Date(year,month-1,day);
    if(parsed.getFullYear()!==year || parsed.getMonth()!==month-1 || parsed.getDate()!==day)return null;
    const today=new Date();
    if(parsed>today||year<1900)return null;
    return today.getFullYear()-year -
      ((today.getMonth()+1<month || (today.getMonth()+1===month && today.getDate()<day))?1:0);
  }
  function updateBirthPreview(){
    const age=ageFromBirthDate($("register-birth-date").value);
    const node=$("register-age-preview");
    node.textContent=age===null?"Укажите действительную дату рождения.":"Ваш возраст: "+age+" "+(
      age%10===1&&age%100!==11?"год":age%10>=2&&age%10<=4&&(age%100<12||age%100>14)?"года":"лет")+
      ". "+(age<18?"Оформление офферов будет недоступно до 18 лет.":"После одобрения сможете оформлять назначенные офферы.");
  }
  function referralUrl(response) {
    // Invite codes come from the authorized server endpoint. Never copy
    // arbitrary remote URLs into a participant's referral invitation.
    const code=response?.code || response?.invite_code;
    if (typeof code === "string" && /^ref_[a-zA-Z0-9_-]{8,48}$/.test(code)) return "https://t.me/affialite_partners_bot?start=" + encodeURIComponent(code);
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
  function offerMessage(message, kind = "empty", retry = null) {
    const el = $("offers");
    el.replaceChildren();
    const panel=document.createElement("div");panel.className="participant-offer-state participant-offer-state-"+kind;
    const mark=document.createElement("span");mark.className="participant-state-mark";mark.setAttribute("aria-hidden","true");
    mark.textContent=kind==="error"?"!":"○";
    const heading=document.createElement("h3");
    heading.textContent=kind==="error"?"Не удалось загрузить офферы":kind==="filtered"?"По этому фильтру пока пусто":"Офферы пока не назначены";
    const paragraph=document.createElement("p");paragraph.className="participant-empty";paragraph.textContent=message;
    panel.append(mark,heading,paragraph);
    if(typeof retry==="function"){
      const button=document.createElement("button");button.type="button";button.className="btn primary";button.textContent=kind==="filtered"?"Показать все":"Повторить попытку";
      button.addEventListener("click",retry);panel.append(button);
    }
    el.append(panel);
  }
  function offerLoading(){
    const el=$("offers");el.replaceChildren();
    const list=document.createElement("div");list.className="participant-offer-skeletons";
    list.setAttribute("role","status");list.setAttribute("aria-label","Загружаем ваши офферы");
    const caption=document.createElement("p");caption.className="muted";caption.textContent="Загружаем ваши офферы…";
    list.append(caption);
    for(let i=0;i<2;i++){
      const card=document.createElement("div");card.className="participant-offer-skeleton";card.setAttribute("aria-hidden","true");
      for(let j=0;j<3;j++){const line=document.createElement("span");line.className="participant-skeleton-line";card.append(line);}
      list.append(card);
    }
    el.append(list);
  }
  function taskNotice(message) {
    const element = $("task-notice");
    element.textContent = message || "";
    element.hidden = !message;
  }
  function safeHttpsUrl(value) {
    if (typeof value !== "string" || value.length > 2048 || /[\\\u0000-\u001f\u007f]/.test(value)) return "";
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
        const offerUrl=safeHttpsUrl(offer.referral_url);
        if (offerUrl) {
          const link=document.createElement("a");link.className="btn ghost";link.textContent="Перейти к предложению ↗";link.href=offerUrl;link.target="_blank";link.rel="noopener noreferrer";link.referrerPolicy="no-referrer";item.append(link);
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
  const manualStages={
    assigned:{label:"Назначено",symbol:"○",next:"Изучите условия оффера и инструкцию перед выполнением действия."},
    in_progress:{label:"В работе",symbol:"◷",next:"Продолжайте выполнять условия оффера. Если возник вопрос, уточните его у администратора."},
    submitted:{label:"На проверке",symbol:"↻",next:"Ожидайте проверки администратором. Это не подтверждение результата банком."},
    completed:{label:"Завершено",symbol:"✓",next:"Администратор отметил задание завершённым. Это не подтверждение банковского начисления или выплаты."},
    rejected:{label:"Отклонено",symbol:"×",next:"Посмотрите комментарий администратора и уточните причину отклонения."}
  };
  const leadStageLabels={
    application_sent:"Отправил заявку",meeting_scheduled:"Назначена встреча",
    product_received:"Продукт получен",account_opened:"Счёт открыт",loan_issued:"Займ получен"
  };
  function offerLogoUrl(offer){
    const url=offer?.logo_url;
    return typeof url==="string" && /^\/partners\/api\/offer-logo\/[a-f0-9]{64}$/.test(url)?url:"";
  }
  function attachOfferLogo(card,offer){
    const url=offerLogoUrl(offer);
    if(!url)return;
    const img=document.createElement("img");
    img.className="offer-logo-watermark";img.src=url;img.alt="";
    img.loading="lazy";img.decoding="async";img.setAttribute("aria-hidden","true");
    card.prepend(img);card.classList.add("has-offer-logo");
  }
  let manualOffers=[];
  let manualFilter="all";
  let manualSort="recent";
  function stageLabel(stage){
    return (manualStages[stage]||manualStages.assigned).label;
  }
  function offerStatus(stage){
    const info=manualStages[stage]||manualStages.assigned;
    const status=document.createElement("span");status.className="pill participant-offer-status";
    status.dataset.status=stage||"assigned";
    const symbol=document.createElement("span");symbol.className="participant-status-symbol";symbol.setAttribute("aria-hidden","true");symbol.textContent=info.symbol;
    const label=document.createElement("span");label.textContent=info.label;
    status.append(symbol,label);
    if(stage==="completed")status.title="Ручная отметка администратора — не банковское подтверждение";
    return status;
  }
  function nextOfferAction(stage){
    const row=document.createElement("p");row.className="participant-offer-next";
    const descriptions={
      assigned:"Прочитать условия",
      in_progress:"Продолжить выполнение",
      submitted:"Ожидает проверки",
      completed:"Отмечено администратором",
      rejected:"Уточнить причину"
    };
    const description=document.createElement("span");
    description.textContent=descriptions[stage]||descriptions.assigned;
    row.append(description);
    row.title=(manualStages[stage]||manualStages.assigned).next;
    return row;
  }
  function offerPayment(value){
    const amount=Number(value);
    return value!==null&&value!==undefined&&value!==""&&Number.isFinite(amount)&&amount>=0
      ?new Intl.NumberFormat("ru-RU",{maximumFractionDigits:0}).format(amount)+" ₽":"—";
  }
  function offerExternalLink(value){
    const url=safeHttpsUrl(value);
    if(!url)return null;
    const link=document.createElement("a");
    link.className="btn primary participant-offer-link";
    link.textContent="Перейти к предложению ↗";
    link.href=url;link.target="_blank";link.rel="noopener noreferrer";link.referrerPolicy="no-referrer";
    return link;
  }
  const offerDialog=$("participant-offer-dialog");
  const offerDialogContent=$("participant-offer-dialog-content");
  function closeOfferDialog(){if(offerDialog.open)offerDialog.close();}
  $("participant-offer-close").addEventListener("click",closeOfferDialog);
  offerDialog.addEventListener("click",event=>{if(event.target===offerDialog)closeOfferDialog();});
  function openOfferDetail(offer){
    offerDialogContent.replaceChildren();
    const title=document.createElement("h2");
    title.id="participant-offer-dialog-title";title.textContent=offer.name||"Предложение";
    const category=document.createElement("p");category.className="participant-offer-category";
    category.textContent=offer.category||"Банковское предложение";
    const status=offerStatus(offer.stage);
    const values=document.createElement("div");values.className="participant-offer-details";
    values.append(offerDetail("СТАВКА ЗА ДЕЙСТВИЕ",offerPayment(offer.payout_rub),"participant-offer-payment"),
      offerDetail("СРОК ПРОВЕРКИ",offer.hold_days==null?"Не указан":String(offer.hold_days)+" дн."));
    const target=offerDetail("ЧТО НУЖНО СДЕЛАТЬ",offer.target_action||"Уточните у администратора","participant-offer-target");
    const notice=document.createElement("p");notice.className="participant-offer-warning";
    notice.textContent="Указанная ставка — условие предложения, а не подтверждение начисления или выплаты. Статусы отмечает администратор.";
    const fullNext=document.createElement("p");fullNext.className="participant-offer-full-next";
    const fullNextTitle=document.createElement("strong");fullNextTitle.textContent="Следующий шаг";
    const fullNextText=document.createElement("span");fullNextText.textContent=(manualStages[offer.stage]||manualStages.assigned).next;
    fullNext.append(fullNextTitle,fullNextText);
    offerDialogContent.append(category,title,status,fullNext,values,target,notice);
    if(offer.instructions){
      const section=document.createElement("section");section.className="participant-offer-instruction-section";
      const heading=document.createElement("h3");heading.textContent="Инструкция";
      const content=document.createElement("p");content.className="participant-offer-instructions";content.textContent=offer.instructions;
      section.append(heading,content);offerDialogContent.append(section);
    }
    if(offer.note){
      const section=document.createElement("section");section.className="participant-offer-instruction-section";
      const heading=document.createElement("h3");heading.textContent="Комментарий администратора";
      const content=document.createElement("p");content.className="participant-offer-note";content.textContent=offer.note;
      section.append(heading,content);offerDialogContent.append(section);
    }
    if(Array.isArray(offer.lead_stages)&&offer.lead_stages.length){
      const section=document.createElement("section");section.className="participant-offer-instruction-section";
      const heading=document.createElement("h3");heading.textContent="Этапы оформления";
      const list=document.createElement("ol");list.className="participant-offer-stage-list";
      for(const code of offer.lead_stages){
        if(!Object.hasOwn(leadStageLabels,code))continue;
        const item=document.createElement("li");item.textContent=leadStageLabels[code];list.append(item);
      }
      section.append(heading,list);
      const hint=document.createElement("p");hint.className="participant-offer-stage-hint";
      hint.textContent="Это возможные этапы. Отметки о выполнении будут доступны после подключения подтверждений.";
      section.append(hint);offerDialogContent.append(section);
    }
    if(offer.latest_event){
      const event=offer.latest_event;
      const section=document.createElement("section");section.className="participant-offer-activity";
      const title=document.createElement("strong");title.textContent="Последнее действие";
      const description=document.createElement("p");
      const names={pending:"Ожидает рассмотрения",approved:"Подтверждено менеджером",
                   rejected:"Отклонено менеджером"};
      description.textContent=(event.kind==="mfo_request"?"Запрос МФО":
        leadStageLabels[event.lead_stage]||"Отчёт")+" · "+(names[event.review_status]||event.review_status);
      section.append(title,description);
      if(event.review_note)section.append(document.createTextNode("Комментарий: "+event.review_note));
      offerDialogContent.append(section);
    }
    const eligible=offer.can_apply===true||
      (offer.unavailable_reason==="mfo_request" && offer.requires_request===true);
    if(eligible&&offer.requires_request&&!offer.mfo_approved&&
       !["completed","rejected"].includes(offer.stage)){
      const request=document.createElement("button");request.type="button";
      request.className="btn primary participant-offer-request";
      request.textContent="Запросить оффер";
      request.disabled=offer.latest_event?.review_status==="pending"&&offer.latest_event?.kind==="mfo_request";
      if(request.disabled)request.textContent="Запрос на рассмотрении";
      request.addEventListener("click",async()=>{
        request.disabled=true;
        try{
          await api("/mvp/submit",{kind:"mfo_request",offer_id:offer.id});
          closeOfferDialog();await loadManualOverview();
        }catch(e){request.disabled=false;error(e.message);}
      });
      offerDialogContent.append(request);
    }
    if(offer.can_apply===true && (!offer.requires_request||offer.mfo_approved) &&
       !["completed","rejected"].includes(offer.stage)){
      const section=document.createElement("section");section.className="participant-offer-report";
      section.append(document.createElement("hr"));
      const title=document.createElement("h3");title.textContent="Отметить этап";
      const hint=document.createElement("p");hint.textContent="Выберите действие и добавьте ссылку, скриншот или оба подтверждения. Отчёт проверит менеджер.";
      section.append(title,hint);
      const form=document.createElement("form");form.className="participant-offer-report-form";
      const stageLabel=document.createElement("label");stageLabel.textContent="Этап выполнения";
      const stages=document.createElement("select");stages.required=true;
      for(const code of offer.lead_stages||[]){
        if(!Object.hasOwn(leadStageLabels,code))continue;
        const option=document.createElement("option");option.value=code;option.textContent=leadStageLabels[code];stages.append(option);
      }
      stageLabel.append(stages);
      const urlLabel=document.createElement("label");urlLabel.textContent="Ссылка на подтверждение (HTTPS)";
      const url=document.createElement("input");url.type="url";url.maxLength=2048;
      url.placeholder="https://";url.inputMode="url";urlLabel.append(url);
      const fileLabel=document.createElement("label");fileLabel.textContent="Скриншот (PNG, JPG, WebP)";
      const file=document.createElement("input");file.type="file";file.accept="image/png,image/jpeg,image/webp";
      fileLabel.append(file);
      const note=document.createElement("p");note.className="participant-offer-report-hint";
      note.textContent="Фото будет уменьшено. Без банковского подтверждения выплаты не начисляются.";
      const submit=document.createElement("button");submit.type="submit";submit.className="btn primary";
      submit.textContent="Отправить этап на проверку";
      const message=document.createElement("p");message.className="participant-form-feedback";message.setAttribute("role","status");
      form.append(stageLabel,urlLabel,fileLabel,note,submit,message);
      form.addEventListener("submit",async event=>{
        event.preventDefault();submit.disabled=true;message.textContent="Отправляем…";
        try{
          const values={kind:"stage",offer_id:offer.id,lead_stage:stages.value,proof_url:url.value.trim()};
          if(file.files?.[0]){
            const uploaded=file.files[0];
            if(!["image/png","image/jpeg","image/webp"].includes(uploaded.type)||uploaded.size>5_000_000)
              throw new Error("Выберите PNG, JPG или WebP размером до 5 МБ.");
            const bitmap=await createImageBitmap(uploaded);
            try{
              const scale=Math.min(1,1280/Math.max(bitmap.width,bitmap.height));
              const canvas=document.createElement("canvas");
              canvas.width=Math.max(1,Math.round(bitmap.width*scale));
              canvas.height=Math.max(1,Math.round(bitmap.height*scale));
              canvas.getContext("2d").drawImage(bitmap,0,0,canvas.width,canvas.height);
              values.screenshot=canvas.toDataURL("image/webp",.70);
              if(values.screenshot.length>735000)throw new Error("Слишком большой скриншот, выберите другой.");
            }finally{bitmap.close();}
          }
          if(!values.screenshot&&!values.proof_url)throw new Error("Добавьте ссылку или скриншот.");
          await api("/mvp/submit",values);
          closeOfferDialog();await loadManualOverview();
        }catch(e){message.textContent=e.message;submit.disabled=false;}
      });
      section.append(form);offerDialogContent.append(section);
    }
    const denied=unavailableReason(offer);
    if(denied){
      const hint=document.createElement("p");hint.className="participant-offer-blocked-hint";hint.textContent=denied;
      const button=document.createElement("button");button.className="btn participant-offer-unavailable";
      button.type="button";button.disabled=true;button.textContent="Недоступно";
      offerDialogContent.append(hint,button);
      if(offer.unavailable_reason!=="underage"&&participantTabsEnabled){
        const action=document.createElement("button");action.type="button";action.className="btn ghost participant-offer-profile-action";
        action.textContent="Перейти в профиль →";
        action.addEventListener("click",()=>{closeOfferDialog();setParticipantView("profile",true);});
        offerDialogContent.append(action);
      }
    }else{
      const link=offerExternalLink(offer.referral_url);
      if(link)offerDialogContent.append(link);
    }
    if(!offerDialog.open)offerDialog.showModal();
  }
  function renderManualOffers(){
    const root=$("offers");root.replaceChildren();
    let offers=manualOffers.filter(offer=>manualFilter==="all"||offer.stage===manualFilter);
    offers=[...offers];
    if(manualSort==="payout_desc")offers.sort((a,b)=>(Number(b.payout_rub)||0)-(Number(a.payout_rub)||0));
    else if(manualSort==="name")offers.sort((a,b)=>String(a.name||"").localeCompare(String(b.name||""),"ru"));
    // Recent uses the authorized server's original assignment order.
    text("offer-filter-count","Показано "+offers.length+" из "+manualOffers.length);
    show("offer-filter-count",true);
    if(!offers.length){
      offerMessage(manualOffers.length?"Попробуйте другой статус или посмотрите все назначенные предложения.":"Администратор ещё не назначил вам предложения. Когда они появятся, вы увидите здесь условия и инструкцию.",manualOffers.length?"filtered":"empty",manualOffers.length?()=>{
        manualFilter="all";
        document.querySelectorAll("[data-offer-filter]").forEach(tab=>tab.setAttribute("aria-pressed",String(tab.dataset.offerFilter==="all")));
        renderManualOffers();
      }:null);
      return;
    }
    const list=document.createElement("div");list.className="offer-list";
    for(const offer of offers){
      const item=document.createElement("article");item.className="offer-item";
      attachOfferLogo(item,offer);
      const top=document.createElement("div");top.className="participant-offer-top";
      const heading=document.createElement("div");heading.className="participant-offer-heading";
      const category=document.createElement("span");category.className="participant-offer-category";
      category.textContent=offer.category||"Банковский оффер";
      const title=document.createElement("h3");title.textContent=offer.name||"Предложение";
      title.title=offer.name||"Предложение";
      heading.append(category,title);
      const status=offerStatus(offer.stage);
      top.append(heading,status);
      const summary=document.createElement("div");summary.className="participant-offer-summary";
      const payment=offerDetail("СТАВКА",offerPayment(offer.payout_rub),"participant-offer-payment");
      const target=offerDetail("ЦЕЛЬ",offer.target_action||"Уточните условия","participant-offer-target");
      summary.append(payment,target);
      const button=document.createElement("button");button.type="button";button.className="btn ghost participant-offer-detail-button";
      button.textContent="Подробнее →";button.setAttribute("aria-label","Подробнее: "+(offer.name||"Предложение"));
      button.addEventListener("click",()=>openOfferDetail(offer));
      item.append(top,summary,nextOfferAction(offer.stage));
      if(offer.latest_event){
        const feedback=document.createElement("p");feedback.className="participant-offer-event-feedback";
        const labels={pending:"Отправлено на проверку",approved:"Отметка подтверждена менеджером",
                      rejected:"Отметка отклонена менеджером"};
        feedback.textContent=labels[offer.latest_event.review_status]||"Получено решение менеджера";
        item.append(feedback);
      }
      if(unavailableReason(offer)){
        const restriction=document.createElement("div");restriction.className="participant-offer-access-status";
        const pill=document.createElement("span");pill.className="participant-offer-access-pill";pill.textContent="Недоступно";
        const explanation=document.createElement("small");explanation.textContent=unavailableReason(offer);
        restriction.append(pill,explanation);item.append(restriction);
      }
      item.append(button);list.append(item);
    }
    root.append(list);
  }
  document.querySelectorAll("[data-offer-filter]").forEach(button=>button.addEventListener("click",()=>{
    manualFilter=button.dataset.offerFilter;
    document.querySelectorAll("[data-offer-filter]").forEach(tab=>tab.setAttribute("aria-pressed",String(tab===button)));
    renderManualOffers();
  }));
  $("offer-sort").addEventListener("change",event=>{
    manualSort=event.target.value;
    event.target.title="Сортировать: "+event.target.selectedOptions[0].textContent;
    event.target.parentElement.classList.toggle("is-custom-sort",manualSort!=="recent");
    renderManualOffers();
  });
  function updateParticipantKpis(offers,stats){
    const stages={in_progress:0,submitted:0,completed:0};
    for(const offer of offers){
      if(offer && Object.prototype.hasOwnProperty.call(stages,offer.stage))stages[offer.stage]++;
    }
    // The overview returns all assignments. Derive split counters from this
    // single authorized payload; backend in_progress includes submitted.
    const total=Number(stats?.total);
    const assigned=Number.isSafeInteger(total) && total>=0 && total===offers.length ? total : offers.length;
    text("kpi-total",assigned);
    text("kpi-in-progress",stages.in_progress);
    text("kpi-submitted",stages.submitted);
    text("kpi-completed",stages.completed);
    if(!offers.length)nextStep("Пока нет офферов","Новые назначения появятся здесь автоматически.","К офферам →");
    else if(stages.in_progress>0)nextStep("Продолжить работу",stages.in_progress+" в работе","Открыть →");
    else if(offers.some(offer=>offer?.stage==="assigned"))nextStep("Новые задания","Посмотрите условия перед началом.","Открыть →");
    else if(stages.submitted>0)nextStep("На проверке",stages.submitted+" ожидают решения администратора.","Посмотреть →");
    else nextStep("Всё обработано","Новые офферы появятся после назначения.","К офферам →");
  }
  function resetParticipantKpis(){
    for(const id of ["kpi-total","kpi-in-progress","kpi-submitted","kpi-completed"])text(id,"—");
  }
  function offerDetail(label,value,className=""){
    const wrapper=document.createElement("div");
    wrapper.className="participant-offer-detail"+(className?" "+className:"");
    const name=document.createElement("span");name.textContent=label;
    const content=document.createElement("strong");content.textContent=value==null||value===""?"—":String(value);
    wrapper.append(name,content);return wrapper;
  }
  async function loadManualOverview(){
    const request=++offersRequest;
    resetParticipantKpis();
    show("offer-controls",false);show("offer-filter-count",false);
    nextStep("Загружаем офферы","Получаем назначения.");
    offerLoading();
    try{
      const result=await api("/mvp/overview");
      if(request!==offersRequest)return;
      const root=$("offers");root.replaceChildren();
      const stats=result.statistics||{};
      const offers=Array.isArray(result.offers)?result.offers:[];
      updateParticipantKpis(offers,stats);
      manualOffers=offers.filter(offer=>offer&&typeof offer==="object");
      show("offer-controls",manualOffers.length>0);
      closeOfferDialog();
      renderManualOffers();
    }catch(e){if(request===offersRequest){
      manualOffers=[];resetParticipantKpis();show("offer-controls",false);show("offer-filter-count",false);
      nextStep("Ошибка загрузки","Повторите попытку в разделе офферов.","К офферам →");
      offerMessage("Проверьте интернет-соединение и попробуйте снова. Если ошибка повторится, обратитесь к администратору.","error",loadManualOverview);
    }}
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
    try{const result=await api("/lead-view");if(request!==crmStatusRequest)return;
      if(!Array.isArray(result.applications)||!Array.isArray(result.lead_payouts))throw new Error("Неполный ответ CRM");
      renderCrmStatus(result);
    }catch(e){if(request===crmStatusRequest)$("crm-state").textContent="Не удалось загрузить статусы CRM: "+e.message;}
  }
  function render(session) {
    current = session;
    for(const id of ["register-legal-version","legacy-legal-version"]){
      const element=$(id);
      if(element)element.textContent=session.legal_version||"Черновик — на утверждении";
    }
    window.renderOwnerLeadPreview?.(session);
    taskNotice("");
    const user = session.user || {};
    const role = session.role || user.role || "user";
    const rawStatus = session.status || user.status || (session.registered === false ? "unregistered" : "unregistered");
    const state = statusInfo(rawStatus);
    const active=["approved","active"].includes(state.key);
    if(role==="blogger"){
      ++offersRequest;++crmStatusRequest;++referralRequest;++financeRequestId;++statisticsRequestId;
      setParticipantTabsEnabled(false);
      document.querySelector(".participant-hero").hidden=true;
      show("connect",false);show("account",false);show("register-panel",false);
      show("pending-panel",false);show("rejected-panel",false);
      show("blogger-panel",active);
      if(active)loadBlogger();
      return;
    }
    show("blogger-panel",false);++bloggerRequestId;++statisticsRequestId;
    const standalone = active && session.open_registration===true;
    if(!standalone)participantView="home";
    setParticipantTabsEnabled(standalone);
    document.querySelector(".participant-hero").hidden=standalone || !active;
    show("stats-section",active && session.open_registration===true);
    show("participant-access-summary",!standalone);
    show("hero-cta",!standalone && active);
    $("hero-cta").href=active?"#offers-section":"#register-panel";
    $("hero-cta").firstChild.textContent=active?"Мои офферы ":"Подать заявку ";
    show("connect",false);show("account",active);
    const unregistered = ["invited","unregistered","new","not_registered"].includes(state.key);
    show("register-panel",unregistered);
    show("pending-panel",state.key==="pending");
    show("rejected-panel",state.key==="rejected");
    text("pending-internal-id",displayRegistrationId(user));
    text("rejected-internal-id",displayRegistrationId(user));
    const rejectedReason=String(user.decision_reason||"").slice(0,500);
    text("rejected-reason",rejectedReason);show("rejected-reason",state.key==="rejected"&&Boolean(rejectedReason));
    const verifiedInvite = Boolean(session.source_info?.inviter_id);
    show("register-form",unregistered && (verifiedInvite || session.open_registration===true));
    text("registration-instructions",session.open_registration===true ? "Заполните короткую анкету прямо здесь. После отправки вы получите постоянный внутренний ID, а заявку рассмотрит администратор." : verifiedInvite ? "Вы вошли по приглашению. Заполните анкету в Mini App и отправьте заявку на рассмотрение." : "Откройте персональную ссылку приглашения через Telegram, затем вернитесь в кабинет и обновите данные.");
    text("welcome",user.first_name ? "Здравствуйте, " + user.first_name : "Личный кабинет");
    nextStep("Загружаем офферы","Получаем назначения…");
    text("hero-status",state.label);text("status-pill",state.label);text("status-title",state.label);
    text("status-description",unregistered && session.open_registration===true
      ? "Вы можете подать заявку через Telegram. Администратор рассмотрит её перед открытием доступа к офферам."
      : state.description);
    $("status-pill").dataset.status=state.key;
    const displayName=[user.first_name,user.last_name].filter(Boolean).join(" ") || user.username || "Участник";
    text("profile-name",displayName);
    text("profile-avatar",displayName.trim().slice(0,1).toUpperCase());
    text("profile-username",user.username?"@"+user.username:"Telegram");
    text("profile-id",user.id);text("profile-internal-id",user.internal_id == null ? "После регистрации" : displayRegistrationId(user));text("profile-role",roleLabels[role] || role);text("profile-status",state.label);
    const canEditProfile=active && ["lead","referrer"].includes(role) && session.open_registration===true;
    show("participant-finance-panel",canEditProfile);
    if(canEditProfile)loadFinance();else ++financeRequestId;
    show("participant-identity-panel",canEditProfile);
    show("participant-credit-panel",canEditProfile);
    show("profile-age-row",Boolean(session.registration?.age!==undefined&&session.registration?.age!==null));
    if(session.registration?.age!==undefined)text("profile-age",session.registration.age+" лет");
    if(canEditProfile){
      const identity=session.identity||{complete:false};
      const legacyOnboarding=!session.registration;
      show("participant-legacy-onboarding",legacyOnboarding);
      $("participant-legacy-birth").required=legacyOnboarding;
      $("participant-legacy-privacy").required=legacyOnboarding;
      $("participant-legacy-terms").required=legacyOnboarding;
      $("participant-identity-save").disabled=legacyOnboarding;
      $("participant-credit-save").textContent=legacyOnboarding?"Завершить анкету":"Обновить анкету";
      text("participant-identity-status",identity.complete
        ?"Реквизиты сохранены · ИНН "+identity.inn_masked
        :legacyOnboarding?"Сначала завершите анкету ниже. Ваш ID сохранится."
        :"Реквизиты не заполнены · оформление недоступно");
      $("participant-surname").value=identity.surname||"";
      $("participant-given-name").value=identity.given_name||"";
      $("participant-patronymic").value=identity.patronymic||"";
      $("participant-inn").value="";
      const registration=session.registration;
      if(registration?.credit_products){
        for(const [name,id] of [["credit_cards","participant-credit-cards"],["installments","participant-installments"],
                                 ["loans","participant-loans"],["mortgages","participant-mortgages"]]){
          $(id).value=String(registration.credit_products[name]??0);
        }
      }else if(legacyOnboarding){
        for(const id of ["participant-credit-cards","participant-installments","participant-loans","participant-mortgages"]){
          $(id).value="0";
        }
      }
      const updated=Number(registration?.credit_updated_at);
      const currentAge=Number(registration?.age);
      const recent=Number.isFinite(updated)&&updated>0&&Date.now()/1000-updated<=30*86400;
      text("participant-credit-updated",Number.isFinite(updated)&&updated>0
        ?"Последнее обновление: "+new Date(updated*1000).toLocaleDateString("ru-RU")+(recent?" · актуально":" · нужно обновить")
        :"Анкета не заполнена");
      if(Number.isFinite(currentAge)&&currentAge<18){
        text("participant-identity-status","Оформление офферов недоступно до 18 лет; приглашать друзей можно.");
      }
    }
    const source = session.source_info || session.attribution || session.invitation || (user.source==="referral" ? {description:"Реферальное приглашение"} : user.source==="agency" ? {description:"Приглашение от агентства"} : {});
    const sourceLabel = typeof source === "object" ? (source.name || source.label || source.inviter_name || source.description || source.code) : source;
    text("source-title",sourceLabel || session.invited_by_name || "Не указан");
    text("source-details",typeof source === "object" ? source.description || (source.inviter_id || user.introduced_by_id ? "Приглашение подтверждено." : "Дополнительная информация не указана.") : "Информация о приглашении");
    show("admin-link",["owner","admin","staff"].includes(role) && ["approved","active"].includes(state.key));
    if (["approved","active"].includes(state.key) && session.open_registration===true){
      text("offers-description","Ваши задания и условия.");
      $("task-history").closest("section").hidden=true;
      $("crm-state").closest("section").hidden=true;
      loadManualOverview();
    }else if (["approved","active"].includes(state.key)){resetParticipantKpis();loadTasks();loadCrmStatus();}
    else {++offersRequest;++crmStatusRequest;resetParticipantKpis();show("offer-controls",false);show("offer-filter-count",false);offerMessage("Предложения станут доступны после одобрения заявки и назначения офферов.");$("task-history").textContent="История недоступна до подтверждения регистрации.";$("crm-state").textContent="Статусы CRM недоступны до подтверждения регистрации.";}
    if (["approved","active"].includes(state.key)) loadReferral(); else {++referralRequest;show("referral-panel",false);}
  }
  function unregisteredStatus(key){return ["invited","unregistered","new","not_registered"].includes(key);}
  async function refresh() {
    const button = $("refresh");
    const pendingButton = $("pending-refresh");
    if(button.disabled)return;
    button.disabled=true;pendingButton.disabled=true;$("rejected-refresh").disabled=true;
    error("");
    try {
      if (!initData()) {
        show("hero-cta",false);
        taskNotice("");
        ++offersRequest;++crmStatusRequest;
        ++referralRequest;show("referral-panel",false);
        show("connect",true);show("account",false);show("register-panel",false);show("pending-panel",false);show("rejected-panel",false);
        show("blogger-panel",false);
        text("hero-status","Нужен вход через Telegram");return;
      }
      text("hero-status","Проверяем доступ…");
      const session = await api("/session");
      if (!session.user || session.source !== "telegram") throw new Error("Сессия не подтверждена сервером");
      render(session);
    } catch(e) {
      show("hero-cta",false);
      taskNotice("");
      ++offersRequest;++crmStatusRequest;
      ++referralRequest;
      show("account",false);show("register-panel",false);show("pending-panel",false);show("rejected-panel",false);show("referral-panel",false);
      show("blogger-panel",false);
      show("connect",true);
      error(e.message);text("hero-status","Не удалось проверить вход");
    } finally {button.disabled=false;pendingButton.disabled=false;$("rejected-refresh").disabled=false;}
  }
  {
    const today=new Date();
    $("register-birth-date").max=[today.getFullYear(),
      String(today.getMonth()+1).padStart(2,"0"),
      String(today.getDate()).padStart(2,"0")].join("-");
  }
  $("register-birth-date").addEventListener("change",updateBirthPreview);
  $("register-birth-date").addEventListener("input",updateBirthPreview);
  $("register-form").addEventListener("submit",async event => {
    event.preventDefault();error("");
    const button=$("register-submit");button.disabled=true;
    text("registration-message","Отправляем заявку…");
    try {
      if(ageFromBirthDate($("register-birth-date").value)===null)throw new Error("Проверьте дату рождения.");
      const values={birth_date:$("register-birth-date").value,consent:$("consent").checked,
        legal_version:current?.legal_version,
        privacy_accepted:$("consent").checked,
        terms_accepted:$("register-terms-consent").checked};
      for(const [name,id] of [["credit_cards","register-credit-cards"],["installments","register-installments"],
                              ["loans","register-loans"],["mortgages","register-mortgages"]]){
        const input=$(id);const count=Number(input.value);
        if(!input.value.trim()||!Number.isInteger(count)||count<0||count>50)
          throw new Error("Укажите количество каждого вида кредитных продуктов от 0 до 50.");
        values[name]=count;
      }
      if(!values.privacy_accepted||!values.terms_accepted)throw new Error("Подтвердите согласие и ознакомление с правилами.");
      const result=await api("/register",values);
      text("registration-message","Заявка отправлена. Ваш ID: "+displayRegistrationId(result.user)+".");
      await refresh();
    } catch(e) {
      text("registration-message",e.message);
    } finally {button.disabled=false;}
  });
  $("participant-identity-form").addEventListener("submit",async event=>{
    event.preventDefault();
    const save=$("participant-identity-save");save.disabled=true;
    text("participant-identity-message","Сохраняем реквизиты…");
    try{
      await api("/profile/identity",{
        surname:$("participant-surname").value.trim(),
        given_name:$("participant-given-name").value.trim(),
        patronymic:$("participant-patronymic").value.trim(),
        inn:$("participant-inn").value.trim()
      });
      text("participant-identity-message","Реквизиты сохранены.");
      await refresh();
    }catch(e){text("participant-identity-message",e.message);}
    finally{save.disabled=false;}
  });
  $("participant-finance-request").addEventListener("submit",async event=>{
    event.preventDefault();
    const submit=$("finance-request-submit");submit.disabled=true;
    const field=$("finance-request-amount");
    const amount=Number(field.value);
    try{
      if(financeAvailableRub===null)throw new Error("Баланс ещё не подтверждён. Повторите загрузку.");
      if(!field.value.trim()||!Number.isSafeInteger(amount)||amount<1)
        throw new Error("Введите положительную сумму в целых рублях.");
      if(amount>financeAvailableRub)throw new Error("Сумма превышает доступный баланс.");
      if(!window.confirm("Запросить выплату "+money(amount)+"? Сумма будет зарезервирована до решения."))
        return;
      await api("/finance/withdraw",{amount_rub:amount});
      field.value="";
      text("finance-request-feedback","Заявка отправлена на рассмотрение.");
      await loadFinance();
    }catch(e){text("finance-request-feedback",e.message);}
    finally{submit.disabled=financeAvailableRub===null || financeAvailableRub<1;}
  });
  $("participant-credit-form").addEventListener("submit",async event=>{
    event.preventDefault();
    const save=$("participant-credit-save");save.disabled=true;
    text("participant-credit-message","Сохраняем обновления…");
    try{
      const values={};
      for(const [name,id] of [["credit_cards","participant-credit-cards"],["installments","participant-installments"],
                              ["loans","participant-loans"],["mortgages","participant-mortgages"]]){
        const input=$(id);const count=Number(input.value);
        if(!input.value.trim()||!Number.isInteger(count)||count<0||count>50)
          throw new Error("Укажите целое количество каждого вида продуктов от 0 до 50.");
        values[name]=count;
      }
      const legacy=!current?.registration;
      if(legacy){
        if(ageFromBirthDate($("participant-legacy-birth").value)===null)
          throw new Error("Укажите действительную дату рождения.");
        values.birth_date=$("participant-legacy-birth").value;
        values.consent=true;
        values.legal_version=current?.legal_version;
        values.privacy_accepted=$("participant-legacy-privacy").checked;
        values.terms_accepted=$("participant-legacy-terms").checked;
        if(!values.privacy_accepted||!values.terms_accepted)
          throw new Error("Подтвердите согласие и ознакомление с правилами.");
      }
      await api(legacy?"/profile/onboarding":"/profile/credit-survey",values);
      text("participant-credit-message","Анкета актуализирована.");
      await refresh();
    }catch(e){text("participant-credit-message",e.message);}
    finally{save.disabled=false;}
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
  $("blogger-copy").addEventListener("click",async()=>{
    const link=$("blogger-link").value;
    if(!link){text("blogger-copy-feedback","Рекламная ссылка сейчас недоступна.");return;}
    try{
      if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(link);
      else if(tg?.showPopup){tg.showPopup({message:link,buttons:[{type:"ok"}]});return;}
      else throw new Error("Копирование недоступно");
      text("blogger-copy-feedback","Ссылка скопирована.");
    }catch(e){text("blogger-copy-feedback",e.message);}
  });
  $("refresh").addEventListener("click",refresh);
  $("pending-refresh").addEventListener("click",refresh);
  $("rejected-refresh").addEventListener("click",refresh);
  try {tg?.ready();tg?.expand();tg?.setHeaderColor?.("#080909");} catch {}
  refresh();
})();
