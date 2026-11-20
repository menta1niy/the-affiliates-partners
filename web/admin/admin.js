(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const tg = window.Telegram?.WebApp;
  const state = {users:[],pending:[],invites:[],tab:"pending",section:"overview",role:"",actorId:null,
    pages:{users:1,pending:1},requests:{users:0,pending:0,assignments:0}};
  let participantRequestId = 0;
  const roles = {owner:"Владелец",admin:"Администратор",staff:"Сотрудник",referrer:"Реферер",lead:"Участник",manager:"Менеджер"};
  const statuses = {pending:"Ожидает",active:"Активен",approved:"Подтверждён",rejected:"Отклонён",blocked:"Заблокирован"};
  const manualStages={assigned:"Назначено",in_progress:"В работе",submitted:"На проверке",completed:"Завершено",rejected:"Отклонено"};
  const leadStageOptions={
    application_sent:"Отправил заявку",meeting_scheduled:"Назначена встреча",
    product_received:"Продукт получен",account_opened:"Счёт открыт",loan_issued:"Займ получен"
  };
  function defaultLeadStages(category){
    const kind=String(category||"").toLowerCase().replaceAll("ё","е");
    if(kind.includes("мфо")||kind.includes("микрозайм")||kind.includes("микрокредит"))return ["application_sent","loan_issued"];
    if(kind.includes("бизнес")||kind.includes("рко")||kind.includes("расчетн"))return ["application_sent","meeting_scheduled","product_received"];
    if(kind.includes("карт"))return ["application_sent","meeting_scheduled","product_received"];
    return ["application_sent","product_received"];
  }
  function offerLogoUrl(offer){
    const url=offer?.logo_url;
    return typeof url==="string" && /^\/partners\/api\/offer-logo\/[a-f0-9]{64}$/.test(url)?url:"";
  }
  function attachOfferLogo(card,offer){
    const url=offerLogoUrl(offer);
    if(!url)return;
    const img=make("img",undefined,"offer-logo-watermark");
    img.alt="";img.loading="lazy";img.decoding="async";img.src=url;
    img.setAttribute("aria-hidden","true");card.prepend(img);card.classList.add("has-offer-logo");
  }
  function initData() {
    if (tg?.initData) return tg.initData;
    for (const part of [location.hash.slice(1),location.search.slice(1)]) {
      const data=new URLSearchParams(part).get("tgWebAppData");
      if(data) return data;
    }
    return "";
  }
  async function api(path, payload={}) {
    const response=await fetch("/partners/api"+path,{method:"POST",cache:"no-store",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:initData(),...payload})});
    const result=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(result.error || result.message || "Сервер вернул код "+response.status);
    return result;
  }
  function show(id,value){$(id).hidden=!value;}
  function error(message){$("admin-error").textContent=message;show("admin-error",!!message);}
  function notice(message){$("admin-notice").textContent=message;show("admin-notice",!!message);}
  function number(value){return value!==null && value!==undefined && Number.isFinite(Number(value))?new Intl.NumberFormat("ru-RU").format(Number(value)):"—";}
  function personName(user){return [user.first_name,user.last_name].filter(Boolean).join(" ") || user.name || (user.username ? "@"+user.username : "Без имени");}
  function roleOf(user){return user.role || "lead";}
  function statusOf(user){return user.status || "pending";}
  function make(tag,content,className) {
    const el=document.createElement(tag);
    if (content!==undefined && content!==null) el.textContent=String(content);
    if (className) el.className=className;
    return el;
  }
  function action(label,fn,variant="ghost"){const button=make("button",label,"btn "+variant);button.type="button";button.addEventListener("click",async()=>{button.disabled=true;error("");try{await fn();}catch(e){error(e.message);}finally{button.disabled=false;}});return button;}
  function detailLine(root,label,value){const p=make("p");p.append(make("strong",label+": "),make("span",value===null || value===undefined || value===""?"—":value));root.append(p);}
  function detailRows(root,title,items,fields){root.append(make("h3",title));if(!items?.length){root.append(make("p","Нет данных","muted"));return;}items.forEach(item=>{const card=make("div",undefined,"participant-detail-item");fields.forEach(([label,key])=>detailLine(card,label,item[key]));root.append(card);});}
  async function openParticipant(user){
    const requestId=++participantRequestId;
    const id=Number(user.id || user.user_id);
    const dialog=$("participant-detail");const content=$("participant-detail-content");
    content.replaceChildren(make("p","Загрузка…"));if(!dialog.open)dialog.showModal();
    try{
      const data=await api("/admin/participant",{user_id:id});
      if(!dialog.open || requestId!==participantRequestId)return;
      content.replaceChildren();const person=data.user || {};
      const profileHeader=make("div",undefined,"admin-profile-header");
      const identity=make("div",undefined,"admin-profile-identity");
      const avatar=make("span",(personName(person).trim().slice(0,1)||"—").toUpperCase(),"admin-profile-avatar");
      const heading=make("div");heading.append(make("span","TELEGRAM PARTICIPANT","admin-profile-eyebrow"),make("h2",personName(person)));
      if(person.username)heading.append(make("span","@"+person.username,"admin-profile-handle"));
      identity.append(avatar,heading);
      const statusBadge=make("span",statuses[person.status]||person.status||"—","pill");
      statusBadge.dataset.status=person.status||"pending";
      profileHeader.append(identity,statusBadge);content.append(profileHeader);
      const meta=make("div",undefined,"admin-profile-meta");
      [["Telegram ID",person.id],["Username",person.username?"@"+person.username:null],["Роль",roles[person.role]||person.role],["Состояние",statuses[person.status]||person.status],["Источник (сохранённый)",person.source],["Агентство",person.agency_id],["Реферер",person.referrer_id],["Пригласил",person.introduced_by_id],["Менеджер",person.manager_id],["CRM Lead ID",data.crm_lead_id]].forEach(([key,value])=>detailLine(meta,key,value));
      content.append(meta);
      if(data.crm_lead_id){
        detailRows(content,"Назначенные офферы CRM",data.offers,[["Оффер","name"],["Рекламодатель","advertiser"],["Действие","target_action"],["Вознаграждение участника","lead_reward"],["Условия","instructions"]]);
        detailRows(content,"Отчёты участника",data.reports,[["Оффер","offer_id"],["Действие","action"],["Комментарий","note"],["Время","created_at"]]);
        detailRows(content,"Стадии заявок CRM",data.status?.applications,[["Оффер","offer_id"],["Стадия","stage"]]);
        detailRows(content,"Подтверждённые выплаты CRM",data.status?.lead_payouts,[["Оффер","offer_id"],["Сумма","amount"],["Статус","status"],["Отменена","reversed"]]);
      }
      if(["lead","referrer"].includes(person.role) && ["owner","admin"].includes(state.role)){
        const section=make("section",undefined,"panel admin-profile-assignments");section.append(make("span","ОФФЕРЫ / РУЧНЫЕ СТАТУСЫ","section-kicker"),make("h3","Управление назначениями"));
        const stats=data.manual?.statistics||{};
        const summary=make("div",undefined,"admin-profile-stats");
        for(const [name,count] of [["Назначено",stats.total],["В работе",stats.in_progress],["Завершено",stats.completed]]){
          const cell=make("div",undefined,"admin-profile-stat");cell.append(make("span",name),make("strong",number(count??0)));summary.append(cell);
        }
        section.append(summary);
        const assignments=Array.isArray(data.manual?.offers)?data.manual.offers:[];
        for(const offer of assignments){
          const item=make("div",undefined,"participant-detail-item admin-assignment");
          item.append(make("span",offer.category||"Банковский оффер","section-kicker"),make("strong",offer.name),make("p",`${offer.payout_rub} ₽ за целевое действие · Холд ${offer.hold_days} дн. · ${offer.target_action}`));
          const select=make("select");
          select.setAttribute("aria-label","Статус оффера "+offer.name);
          for(const [key,label] of Object.entries(manualStages)){const option=make("option",label);option.value=key;select.append(option);}select.value=offer.stage;
          const note=make("input");note.placeholder="Комментарий для участника";note.maxLength=300;note.value=offer.note||"";
          note.setAttribute("aria-label","Комментарий к офферу "+offer.name);
          const buttons=make("div",undefined,"admin-assignment-actions");
          buttons.append(action("Сохранить статус",async()=>{
            await api("/admin/mvp/assignment",{user_id:id,offer_id:offer.id,stage:select.value,note:note.value});
            notice("Статус обновлён");await openParticipant(person);
          },"primary"),action("Убрать оффер",async()=>{
            if(!window.confirm("Убрать назначение оффера?"))return;
            await api("/admin/mvp/assignment",{user_id:id,offer_id:offer.id,enabled:false,note:""});
            await openParticipant(person);
          },"danger"));
          item.append(select,note,buttons);
          if(state.role==="owner" || state.role==="admin"){
            const credit=make("div",undefined,"admin-finance-credit-inline");
            const amount=make("input");amount.type="number";amount.min="1";amount.max="10000000";
            amount.step="1";amount.inputMode="numeric";amount.placeholder="Сумма начисления, ₽";
            amount.setAttribute("aria-label","Подтверждённое начисление для "+offer.name);
            const reference=make("input");reference.type="text";reference.maxLength=120;
            reference.placeholder="Внешний ID подтверждения";
            reference.setAttribute("aria-label","Уникальный номер подтверждения для "+offer.name);
            const submit=action("Добавить подтверждённое начисление",async()=>{
              const value=Number(amount.value);
              if(!amount.value.trim()||!Number.isSafeInteger(value)||value<1||value>10000000)
                throw new Error("Укажите сумму в целых рублях.");
              const source=reference.value.trim();
              if(!/^[A-Za-z0-9][A-Za-z0-9._:/-]{3,119}$/.test(source))
                throw new Error("Укажите уникальный внешний ID подтверждения (4–120 символов).");
              if(!window.confirm("Добавить вручную подтверждённое начисление "+number(value)+
                " ₽ участнику "+personName(person)+"? Статус оффера не подтверждает банковское начисление."))
                return;
              await api("/admin/finance/accrue",{user_id:id,offer_id:offer.id,amount_rub:value,source_reference:source});
              notice("Начисление подтверждено. Повтор с таким ID невозможен.");
              await openParticipant(person);
            },"primary");
            credit.append(make("p","Финансовое подтверждение только при наличии независимого основания.","muted"),amount,reference,submit);
            item.append(credit);
          }
          section.append(item);
        }
        const available=await api("/admin/mvp/catalog");
        if(requestId!==participantRequestId || !dialog.open)return;
        const picker=make("select");picker.setAttribute("aria-label","Оффер для назначения");
        for(const offer of available.offers||[]){if(!offer.active || assignments.some(a=>a.id===offer.id))continue;const option=make("option",offer.name);option.value=offer.id;picker.append(option);}
        if(picker.options.length){const assignRow=make("div",undefined,"admin-assignment-picker");assignRow.append(picker,action("Назначить оффер",async()=>{
          await api("/admin/mvp/assignment",{user_id:id,offer_id:picker.value,stage:"assigned",note:""});
          notice("Оффер назначен");await openParticipant(person);
        },"primary"));section.append(assignRow);}else section.append(make("p","Нет новых доступных офферов. Добавьте их в каталоге.","muted"));
        if(person.status==="pending")section.append(action("Одобрить участника",async()=>{
          await api("/admin/decision",{user_id:id,decision:"approve"});notice("Участник одобрен");await loadDashboard();await openParticipant(person);
        }));
        content.append(section);
      }
      detailRows(content,"Журнал действий",data.audit,[["Действие","action"],["Кем","actor_id"],["Комментарий","details"],["Время","created_at"]]);
    }catch(e){if(dialog.open && requestId===participantRequestId)content.replaceChildren(make("p",e.message,"message error"));}
  }
  async function decide(user,decision) {
    const id=Number(user.id || user.user_id);
    let reason;
    if (decision !== "approve") {
      reason=window.prompt(decision==="block"?"Причина блокировки:":"Причина отклонения:");
      if (reason===null) return;
      reason=reason.trim();
      if (!reason || reason.length>500) {error("Укажите причину решения от 1 до 500 символов.");return;}
    }
    if (decision==="block" && !window.confirm("Заблокировать пользователя "+id+"?")) return;
    if (decision==="approve" && statusOf(user)==="blocked" && !window.confirm("Разблокировать пользователя "+id+" и восстановить активный статус?")) return;
    if (decision==="approve" && statusOf(user)==="rejected" && !window.confirm("Повторно одобрить отклонённую заявку пользователя "+id+"?")) return;
    await api("/admin/decision",{user_id:id,decision,...(reason?{reason}:{})});
    notice("Решение сохранено для "+personName(user));
    await loadDashboard();
  }
  async function assign(user) {
    const id=Number(user.id || user.user_id);
    const role=window.prompt("Роль: admin, staff, referrer, lead (пусто — сохранить текущую)", "");
    if (role===null) return;
    const normalized=role.trim().toLowerCase();
    if (normalized && !["admin","staff","referrer","lead"].includes(normalized)){error("Недопустимая роль.");return;}
    if (normalized==="admin" && state.role!=="owner"){error("Назначение администратора доступно только владельцу.");return;}
    const input=window.prompt("Менеджер: пусто — сохранить текущего; ID — назначить; CLEAR — снять назначение", "");
    if(input===null)return;
    const managerId=input.trim();
    if(managerId && managerId!=="CLEAR" && (!/^[1-9][0-9]*$/.test(managerId) || !Number.isSafeInteger(Number(managerId)) || Number(managerId)===id)){error("Введите корректный Telegram ID другого пользователя либо CLEAR.");return;}
    const update={user_id:id,...(normalized?{role:normalized}:{}),...(managerId==="CLEAR"?{clear_manager:true}:managerId?{manager_id:Number(managerId)}:{})};
    if(Object.keys(update).length===1){notice("Назначение оставлено без изменений.");return;}
    await api("/admin/assign",update);
    notice("Назначение обновлено для "+personName(user));await loadDashboard();
  }
  async function correctSource(user) {
    const userId=Number(user.id || user.user_id);
    if (!Number.isSafeInteger(userId) || userId <= 0 || !["agency","referral"].includes(user.source)) {
      error("Исправить источник можно только у зарегистрированного участника.");
      return;
    }
    const source=window.prompt("Источник: agency или referral",user.source || "agency");
    if(source===null)return;
    const normalized=source.trim().toLowerCase();
    if(!["agency","referral"].includes(normalized)){error("Источник должен быть agency или referral.");return;}
    const field=normalized==="agency"?"agency_id":"referrer_id";
    const sourceId=window.prompt("Telegram ID "+(normalized==="agency"?"агентства":"реферера")+" (обязателен)",String(user[field] || ""));
    if(sourceId===null)return;
    if(!/^[1-9][0-9]*$/.test(sourceId.trim()) || !Number.isSafeInteger(Number(sourceId)) || Number(sourceId)===userId){error("Укажите корректный Telegram ID другого участника.");return;}
    let introducedById;
    if(normalized==="agency"){
      const introduced=window.prompt("Фактически пригласивший: Telegram ID (необязательно; пусто — сохранить предложенный ID)",String(user.introduced_by_id || sourceId.trim()));
      if(introduced===null)return;
      const value=introduced.trim() || String(user.introduced_by_id || sourceId.trim());
      if(!/^[1-9][0-9]*$/.test(value) || !Number.isSafeInteger(Number(value)) || Number(value)===userId){error("Укажите корректный Telegram ID фактически пригласившего.");return;}
      introducedById=Number(value);
    }
    const reason=window.prompt("Причина исправления источника (обязательна, фиксируется в журнале):");
    if(reason===null)return;
    if(!reason.trim() || reason.trim().length>500){error("Причина должна содержать от 1 до 500 символов.");return;}
    if(!window.confirm("Исправить источник для Telegram ID "+userId+"?"))return;
    const result=await api("/admin/attribution",{user_id:userId,source:normalized,[field]:Number(sourceId),...(normalized==="agency"?{introduced_by_id:introducedById}:{}),reason:reason.trim()});
    notice(result.changed===false?"Источник уже соответствует указанным данным.":"Источник обновлён для "+personName(user));
    await loadDashboard();
  }
  function renderTable(container,users,mode) {
    container.replaceChildren();
    if (!users.length){container.append(make("p","Записей нет.","empty"));return;}
    const table=make("table");
    const head=make("thead"),headRow=make("tr");
    ["Участник","Внутренний ID","Telegram ID","Статус","Роль","Источник","Менеджер","Действия"].forEach(v=>headRow.append(make("th",v)));
    head.append(headRow);table.append(head);
    const body=make("tbody");
    users.forEach(user=>{
      const row=make("tr");
      const sourceDescription=user.source==="referral"?"Реферал":user.source==="agency"?"Агентство":"Не указан";
      const ids=[user.introduced_by_id?"Пригласил: "+user.introduced_by_id:"",user.agency_id?"Агентство: "+user.agency_id:"",user.referrer_id?"Реферер: "+user.referrer_id:""].filter(Boolean);
      row.append(make("td",personName(user)+(user.username?" · @"+user.username:"")),make("td",user.internal_id ?? "—"),make("td",user.id || user.user_id || "—"),make("td",statuses[statusOf(user)] || statusOf(user)),make("td",roles[roleOf(user)] || roleOf(user)),make("td",sourceDescription+(ids.length?" · "+ids.join(" · "):"")),make("td",user.manager_id || "—"));
      row.className="admin-data-row";
      const actions=make("td");const group=make("div",undefined,"actions");
      group.append(action("Карточка",()=>openParticipant(user)));
      const targetRole=roleOf(user);
      const permitted=targetRole!=="owner" &&
        !(state.role==="admin" && targetRole==="admin") &&
        (state.role!=="staff" || (Number(user.manager_id)===state.actorId && ["lead","referrer"].includes(targetRole)));
      if(permitted && statusOf(user)==="pending"){
        group.append(action("Одобрить",()=>decide(user,"approve")),action("Отклонить",()=>decide(user,"reject")));
      }
      if(permitted && statusOf(user)==="rejected" && (state.role==="owner" || state.role==="admin"))group.append(action("Одобрить",()=>decide(user,"approve")));
      if(permitted && statusOf(user)==="blocked" && (state.role==="owner" || state.role==="admin"))group.append(action("Разблокировать",()=>decide(user,"approve")));
      if(permitted && state.role!=="staff")group.append(action("Роль / менеджер",()=>assign(user)));
      if(permitted && state.role==="owner" && ["agency","referral"].includes(user.source))group.append(action("Исправить источник",()=>correctSource(user)));
      if(permitted && statusOf(user)!=="blocked")group.append(action("Блокировать",()=>decide(user,"block")));
      actions.append(group);row.append(actions);
      row.querySelectorAll("td").forEach((cell,index)=>cell.dataset.label=["Участник","Внутренний ID","Telegram ID","Статус","Роль","Источник","Менеджер","Действия"][index]);
      body.append(row);
    });
    table.append(body);container.append(table);
  }
  async function loadUsersPage(kind,page=state.pages[kind]){
    const requestId=++state.requests[kind];
    const container=$(kind==="pending"?"pending-list":"users-list");
    container.replaceChildren(make("p","Загрузка…","muted"));
    const filters=kind==="pending"?{status:"pending"}:{
      query:$("user-query").value.trim(),status:$("user-filter").value,role:$("role-filter").value};
    try{
      const data=await api("/admin/users",{page,...filters});
      if(requestId!==state.requests[kind])return;
      state.pages[kind]=page;
      const users=Array.isArray(data.users)?data.users:[];
      state[kind]=users;
      renderTable(container,users,kind);
      const controls=make("div",undefined,"actions");
      const total=Number(data.total)||0;
      controls.append(make("span",`Страница ${page} · всего ${number(total)}`));
      const previous=action("Назад",()=>loadUsersPage(kind,page-1));previous.disabled=page<=1;
      const next=action("Далее",()=>loadUsersPage(kind,page+1));next.disabled=!data.has_next;
      controls.append(previous,next);container.append(controls);
    }catch(e){if(requestId===state.requests[kind]){container.replaceChildren(make("p",e.message,"message error"));error(e.message);}}
  }
  function renderInvites(){
    const root=$("invites-list");
    root.replaceChildren();
    if(!state.invites.length){root.append(make("p","Предварительных приглашений пока нет.","empty"));return;}
    const table=make("table"),head=make("thead"),headRow=make("tr");
    ["Кандидат","Источник","Код","Ответственный","Состояние","Ссылка"].forEach(value=>headRow.append(make("th",value)));
    head.append(headRow);table.append(head);
    const body=make("tbody");
    state.invites.forEach(invite=>{
      const row=make("tr");
      // Older servers do not expose usable; keep the state visible but do not
      // offer a share action without an explicit server-side eligibility check.
      const usable=invite.active===1 || invite.active===true;
      const canShare=usable && invite.usable===true;
      const stateLabel=!usable?"Неактивно":invite.usable===false?"Недействительно (права/статус)":invite.usable===true?"Действует":"Статус не проверен";
      row.append(
        make("td",invite.candidate_label || "Без имени"),
        make("td",invite.kind==="agency"?"Агентство":"Реферал"),
        make("td",invite.code || "—"),
        make("td",invite.assignee_id || invite.issuer_id || "—"),
        make("td",stateLabel)
      );
      const cell=make("td");
      if(canShare && typeof invite.code==="string" && /^(?:ag|ref)_[a-zA-Z0-9_-]{8,48}$/.test(invite.code)){
        const link="https://t.me/affialite_partners_bot?start="+encodeURIComponent(invite.code);
        cell.append(action("Копировать",async()=>{
          if(!navigator.clipboard?.writeText)throw new Error("Копирование недоступно: выделите код приглашения в таблице.");
          await navigator.clipboard.writeText(link);
          notice("Ссылка приглашения скопирована.");
        }));
        const start=make("a","Открыть /start","btn ghost");start.href=link;start.target="_blank";start.rel="noopener noreferrer";cell.append(start);
      }
      if(usable && (state.role==="owner" || Number(invite.issuer_id)===state.actorId) &&
         typeof invite.code==="string" && /^(?:ag|ref)_[a-zA-Z0-9_-]{8,48}$/.test(invite.code)){
        cell.append(action("Отозвать",async()=>{
          if(!window.confirm("Отозвать приглашение "+invite.code+"? Ссылка перестанет действовать, отменить отзыв нельзя."))return;
          const result=await api("/invitations/revoke",{code:invite.code});
          notice(result.changed===false?"Приглашение уже отозвано.":"Приглашение отозвано.");
          await loadDashboard();
        }));
      }
      row.append(cell);
      row.className="admin-data-row";
      row.querySelectorAll("td").forEach((field,index)=>field.dataset.label=["Кандидат","Источник","Код","Ответственный","Состояние","Ссылка"][index]);
      body.append(row);
    });
    table.append(body);root.append(table);
  }
  function renderDashboard(data){
    const counts=data.counts || data.stats || {};
    const users=Array.isArray(data.users)?data.users:(Array.isArray(data.results)?data.results:[]);
    const pending=Array.isArray(data.pending)?data.pending:users.filter(u=>statusOf(u)==="pending");
    state.users=users;state.pending=pending;
    state.invites=Array.isArray(data.invites)?data.invites:[];
    const totals={total:counts.total ?? counts.users ?? counts.total_users ?? Object.values(counts).reduce((sum,value)=>sum+(Number(value)||0),0),pending:counts.pending,active:counts.active,blocked:counts.blocked};
    for(const key of ["total","pending","active","blocked"])$("count-"+key).textContent=number(totals[key]);
    renderTable($("pending-list"),pending,"pending");renderTable($("users-list"),users,"users");
    renderInvites();
  }
  async function loadDashboard(){const data=await api("/admin/dashboard");renderDashboard(data);await Promise.all([loadUsersPage("pending"),loadUsersPage("users")]);}
  async function loadAudit(){
    const root=$("audit-list");root.replaceChildren();
    try {
      const data=await api("/admin/audit");
      const events=Array.isArray(data.events)?data.events:(Array.isArray(data.audit)?data.audit:[]);
      if(!events.length){root.append(make("p","Записей пока нет.","empty"));return;}
      events.forEach(event=>{
        const item=make("div",undefined,"audit-entry");
        item.append(make("strong",event.action || event.event || "Действие"),make("div",[event.actor_id ? "Автор: "+event.actor_id : "",event.target_id ? "Участник: "+event.target_id : "",event.details || event.reason || ""].filter(Boolean).join(" · ")));
        if(event.created_at || event.timestamp)item.append(make("time",event.created_at || event.timestamp));
        root.append(item);
      });
    }catch(e){root.append(make("p",e.message,"empty"));error(e.message);}
  }
  async function openOfferCatalog(focusOfferId=null){
    let dialog=$("mvp-catalog-dialog");
    if(!dialog){dialog=make("dialog");dialog.id="mvp-catalog-dialog";dialog.className="panel admin-catalog-dialog";document.body.append(dialog);}
    dialog.replaceChildren();
    const top=make("div",undefined,"admin-dialog-toolbar");
    top.append(make("span","КАТАЛОГ / CONTROL","section-kicker"),action("Закрыть",()=>dialog.close()));
    dialog.append(top,make("h2","Каталог офферов"));
    dialog.append(make("p","Параметры и условия банковских предложений. Указанная ставка не является подтверждённым начислением.","muted"));
    const list=make("div",undefined,"admin-catalog-list");dialog.append(list);
    const fields=[["name","Название","text"],["category","Категория","text"],["target_action","Целевое действие","text"],["payout_rub","Оплата, ₽","number"],["hold_days","Холд, дней","number"],["instructions","Инструкция","textarea"],["referral_url","HTTPS-ссылка","url"]];
    const form=make("form");form.className="admin-catalog-form";
    const inputs={};let editingId=null;
    const head=make("div",undefined,"admin-catalog-form-heading");
    const heading=make("h3","Добавить оффер");
    head.append(make("span","НАСТРОЙКА ПРЕДЛОЖЕНИЯ","section-kicker"),heading);
    form.append(head);
    const grid=make("div",undefined,"admin-catalog-field-grid");
    for(const [key,label,type] of fields){
      const wrap=make("label",undefined,"admin-catalog-field admin-catalog-field-"+key);
      const title=make("span",label);
      const input=make(type==="textarea"?"textarea":"input");
      if(type!=="textarea")input.type=type;
      else {input.rows=3;input.placeholder="Условия и порядок выполнения целевого действия";}
      input.name=key;input.maxLength=key==="instructions"?2000:2048;
      if(type==="number"){input.min="0";input.step="1";}
      if(key==="payout_rub"||key==="hold_days")input.value="0";
      if(key==="name"||key==="category"||key==="target_action")input.required=true;
      if(key==="referral_url")input.placeholder="https://";
      inputs[key]=input;wrap.append(title,input);grid.append(wrap);
    }
    form.append(grid);
    const categories=make("datalist");categories.id="admin-offer-category-options";
    for(const name of ["Дебетовые карты","Кредитные карты","Бизнес-счета","МФО","Рассрочка","Другие продукты"]){
      const option=make("option");option.value=name;categories.append(option);
    }
    inputs.category.setAttribute("list",categories.id);form.append(categories);
    const visual=make("section",undefined,"admin-offer-visual");
    visual.append(make("h4","Логотип оффера"),make("p","PNG, JPG или WebP. На карточке изображение будет полупрозрачным (15%)."));
    const uploadRow=make("div",undefined,"admin-logo-upload-row");
    const preview=make("div",undefined,"admin-logo-preview");
    const fileLabel=make("label","Загрузить изображение","btn ghost admin-logo-file-label");
    const fileInput=make("input");fileInput.type="file";fileInput.accept="image/png,image/jpeg,image/webp";
    fileInput.id="admin-offer-logo-file";fileLabel.append(fileInput);
    const removeImage=make("button","Убрать логотип","btn ghost");removeImage.type="button";
    const fileHint=make("small","Файл обрабатывается при сохранении.");
    const uploadActions=make("div",undefined,"admin-logo-upload-actions");uploadActions.append(fileLabel,removeImage,fileHint);
    uploadRow.append(preview,uploadActions);visual.append(uploadRow);form.append(visual);
    let pendingFile=null,removeLogo=false,previewUrl="";
    function setPreview(src){
      if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl="";}
      preview.replaceChildren();
      if(src){
        const image=make("img");image.alt="Предпросмотр логотипа";image.src=src;preview.append(image);
      }else preview.append(make("span","AP","admin-logo-fallback"));
    }
    setPreview("");
    fileInput.addEventListener("change",()=>{
      const file=fileInput.files?.[0];
      if(!file)return;
      if(!["image/png","image/jpeg","image/webp"].includes(file.type)||file.size>5_000_000){
        fileInput.value="";error("Выберите PNG, JPG или WebP размером до 5 МБ.");return;
      }
      pendingFile=file;removeLogo=false;error("");
      const src=URL.createObjectURL(file);
      setPreview(src);previewUrl=src;
    });
    removeImage.addEventListener("click",()=>{
      pendingFile=null;removeLogo=true;fileInput.value="";setPreview("");
    });
    async function encodeLogo(file){
      const image=await createImageBitmap(file);
      try{
        const scale=Math.min(1,960/Math.max(image.width,image.height));
        const canvas=document.createElement("canvas");
        canvas.width=Math.max(1,Math.round(image.width*scale));
        canvas.height=Math.max(1,Math.round(image.height*scale));
        canvas.getContext("2d").drawImage(image,0,0,canvas.width,canvas.height);
        const data=canvas.toDataURL("image/webp",.78);
        if(!data.startsWith("data:image/webp;base64,")||data.length>1_350_000)
          throw new Error("Логотип слишком большой после сжатия. Выберите другое изображение.");
        return data;
      }finally{image.close();}
    }
    const stagesSection=make("fieldset",undefined,"admin-offer-stages");
    stagesSection.append(make("legend","Этапы для лида"));
    stagesSection.append(make("p","Укажите, какие этапы должны отображаться в условиях оффера. Изменение статусов самим лидом — следующий этап."));
    const stageGrid=make("div",undefined,"admin-offer-stage-grid");
    const stageInputs={};let stagesCustomized=false;
    for(const [key,label] of Object.entries(leadStageOptions)){
      const item=make("label",undefined,"admin-offer-stage-option");
      const checkbox=make("input");checkbox.type="checkbox";checkbox.value=key;
      checkbox.addEventListener("change",()=>{stagesCustomized=true;});
      stageInputs[key]=checkbox;item.append(checkbox,make("span",label));stageGrid.append(item);
    }
    function setStages(stages){
      for(const [key,control] of Object.entries(stageInputs))control.checked=stages.includes(key);
    }
    const resetStages=make("button","По категории","btn ghost admin-stage-reset");
    resetStages.type="button";resetStages.addEventListener("click",()=>{
      stagesCustomized=false;setStages(defaultLeadStages(inputs.category.value));
    });
    inputs.category.addEventListener("input",()=>{
      if(!stagesCustomized)setStages(defaultLeadStages(inputs.category.value));
    });
    stagesSection.append(stageGrid,resetStages);form.append(stagesSection);
    setStages(defaultLeadStages(""));
    const active=make("input");active.type="checkbox";active.checked=true;active.id="admin-catalog-active";
    const activeLabel=make("label",undefined,"admin-catalog-availability");
    activeLabel.htmlFor=active.id;
    const activeCopy=make("span",undefined,"admin-catalog-availability-copy");
    activeCopy.append(make("strong","Доступен для назначений"),make("small","Оффер можно назначать участникам"));
    const toggle=make("span",undefined,"admin-catalog-switch");toggle.setAttribute("aria-hidden","true");
    activeLabel.append(activeCopy,active,toggle);form.append(activeLabel);
    const actions=make("div",undefined,"admin-catalog-form-actions");
    const save=make("button","Сохранить оффер","btn primary");save.type="submit";
    const cancel=make("button","Отменить редактирование","btn ghost");cancel.type="button";cancel.hidden=true;
    function loadEditor(offer){
      editingId=offer.id;heading.textContent="Редактировать оффер";
      for(const [key] of fields)inputs[key].value=offer[key]??"";
      active.checked=!!offer.active;
      pendingFile=null;removeLogo=false;fileInput.value="";setPreview(offerLogoUrl(offer));
      stagesCustomized=true;
      setStages(Array.isArray(offer.lead_stages)?offer.lead_stages:defaultLeadStages(offer.category));
      cancel.hidden=false;save.textContent="Сохранить изменения";
    }
    function resetEditor(){
      editingId=null;heading.textContent="Добавить оффер";form.reset();
      inputs.payout_rub.value="0";inputs.hold_days.value="0";active.checked=true;
      pendingFile=null;removeLogo=false;fileInput.value="";setPreview("");
      stagesCustomized=false;setStages(defaultLeadStages(""));
      cancel.hidden=true;save.textContent="Сохранить оффер";
    }
    cancel.addEventListener("click",resetEditor);
    actions.append(save,cancel);form.append(actions);
    form.addEventListener("submit",async e=>{e.preventDefault();save.disabled=true;try{
      const payload={};for(const [key] of fields)payload[key]=inputs[key].value.trim();
      payload.payout_rub=Number(payload.payout_rub);payload.hold_days=Number(payload.hold_days);payload.active=active.checked;
      payload.lead_stages=Object.entries(stageInputs).filter(([,input])=>input.checked).map(([key])=>key);
      if(!payload.lead_stages.length)throw new Error("Выберите хотя бы один этап оформления.");
      if(pendingFile)payload.logo_data=await encodeLogo(pendingFile);
      else if(removeLogo)payload.remove_logo=true;
      if(editingId)payload.offer_id=editingId;
      await api("/admin/mvp/offer",payload);resetEditor();await reload();
      if(state.section==="offers")await renderOffersView();
      notice("Оффер сохранён");
    }catch(err){error(err.message);}finally{save.disabled=false;}});
    const canEdit=state.role==="owner";
    if(canEdit)dialog.insertBefore(form,list);
    else dialog.append(make("p","Для вашей роли доступен просмотр каталога. Изменение общего каталога выполняет владелец.","message"));
    async function reload(){
      list.replaceChildren(make("p","Загрузка…"));
      const data=await api("/admin/mvp/catalog");list.replaceChildren();
      const offers=Array.isArray(data.offers)?data.offers:[];
      if(!offers.length){list.append(make("p","Офферы пока не добавлены.","empty"));return offers;}
      for(const offer of offers){
        const item=make("article",undefined,"admin-catalog-card");
        const meta=make("div",undefined,"admin-catalog-card-heading");
        const name=make("div");name.append(make("span",offer.category||"Банковский оффер","section-kicker"),make("h3",offer.name));
        const availability=make("span",offer.active?"Доступен":"Отключён","pill");
        availability.dataset.status=offer.active?"active":"blocked";meta.append(name,availability);
        item.append(meta);attachOfferLogo(item,offer);
        const terms=make("div",undefined,"admin-catalog-terms");
        for(const [key,value] of [["СТАВКА",number(offer.payout_rub)+" ₽"],["ХОЛД",(offer.hold_days??"—")+" дн."],["ЦЕЛЕВОЕ ДЕЙСТВИЕ",offer.target_action||"—"]]){
          const row=make("div");row.append(make("span",key),make("strong",value));terms.append(row);
        }
        item.append(terms);
        if(canEdit)item.append(action("Редактировать",()=>{loadEditor(offer);form.scrollIntoView({behavior:"smooth",block:"start"});}));
        list.append(item);
      }
      return offers;
    }
    dialog.showModal();
    const offers=await reload();
    if(canEdit && focusOfferId){
      const offer=offers.find(item=>String(item.id)===String(focusOfferId));
      if(offer){
        loadEditor(offer);
        form.scrollIntoView({behavior:"instant",block:"start"});
      }
    }
  }
  const sections={
    overview:{name:"Обзор",description:"Главные показатели и быстрые действия.",number:"01"},
    offers:{name:"Офферы",description:"Каталог предложений, условия и ставки.",number:"02"},
    assignments:{name:"Назначения",description:"Ручная выдача и контроль назначенных офферов.",number:"03"},
    people:{name:"Пользователи",description:"Регистрации, профили и права участников.",number:"04"},
    more:{name:"Ещё",description:"Приглашения, история действий и другие инструменты.",number:"05"}
  };
  const subtabSection={pending:"people",users:"people",offer_reviews:"people",finance:"people",invitations:"more",audit:"more"};
  const defaultSubtab={people:"pending",more:"invitations"};
  function canManageOffers(){return state.role==="owner" || state.role==="admin";}
  async function renderOffersView(){
    if(!canManageOffers())return;
    const root=$("admin-offers-list");
    root.replaceChildren(make("p","Загружаем офферы…","muted"));
    try{
      const data=await api("/admin/mvp/catalog");
      if(state.section!=="offers")return;
      const offers=Array.isArray(data.offers)?data.offers:[];
      root.replaceChildren();
      if(!offers.length){root.append(make("p","Офферы пока не добавлены. Откройте управление каталогом.","empty"));return;}
      for(const offer of offers){
        const card=make("article",undefined,"admin-catalog-card");
        const head=make("div",undefined,"admin-catalog-card-heading");
        const identity=make("div");
        identity.append(make("span",offer.category||"Банковский оффер","section-kicker"),make("h3",offer.name));
        const status=make("span",offer.active?"Активен":"Отключён","pill");
        status.dataset.status=offer.active?"active":"blocked";
        head.append(identity,status);
        const terms=make("div",undefined,"admin-catalog-terms");
        for(const [label,value] of [["СТАВКА",number(offer.payout_rub)+" ₽"],["ХОЛД",(offer.hold_days??"—")+" дн."],["ЦЕЛЬ",offer.target_action||"—"]]){
          const cell=make("div");cell.append(make("span",label),make("strong",value));terms.append(cell);
        }
        card.append(head,terms);attachOfferLogo(card,offer);
        card.append(action(state.role==="owner"?"Редактировать":"Подробнее",
          ()=>openOfferCatalog(state.role==="owner"?offer.id:null)));
        root.append(card);
      }
    }catch(e){root.replaceChildren(make("p",e.message,"message error"));}
  }
  const assignmentUI={
    mode:"offer_to_leads",catalog:[],offerId:"",lead:null,
    chosenUsers:new Map(),chosenOffers:new Set(),people:[],page:1,total:0,
    previewPayload:null,loading:false
  };
  function assignmentMessage(message,isError=false){
    const node=$("admin-assignment-result");node.textContent=message;
    node.hidden=!message;node.classList.toggle("error",isError);
  }
  function filteredAssignmentOffers(){
    const query=$("admin-assignment-offer-search").value.trim().toLocaleLowerCase("ru");
    const category=$("admin-assignment-category-filter").value;
    return assignmentUI.catalog.filter(offer=>offer.active &&
      (!category || offer.category===category) &&
      (!query || (offer.name+" "+offer.category).toLocaleLowerCase("ru").includes(query)));
  }
  function renderAssignmentCatalog(){
    const categories=[...new Set(assignmentUI.catalog.filter(offer=>offer.active).map(offer=>offer.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"ru"));
    const categoryFilter=$("admin-assignment-category-filter");
    const selectedCategory=categoryFilter.value;
    categoryFilter.replaceChildren(new Option("Все категории",""));
    for(const category of categories)categoryFilter.add(new Option(category,category));
    categoryFilter.value=categories.includes(selectedCategory)?selectedCategory:"";
    const offers=filteredAssignmentOffers();
    const target=$("admin-assignment-offer");
    target.replaceChildren(new Option("Выберите предложение",""));
    for(const offer of offers)target.add(new Option(offer.name+" · "+number(offer.payout_rub)+" ₽",offer.id));
    if(!offers.some(offer=>offer.id===assignmentUI.offerId)) {
      assignmentUI.offerId="";
      assignmentUI.chosenUsers.clear();
    }
    target.value=assignmentUI.offerId;
    const list=$("admin-assignment-offers");
    list.replaceChildren();
    if(!offers.length)list.append(make("p","Нет доступных офферов по этим фильтрам.","muted"));
    for(const offer of offers){
      const label=make("label",undefined,"admin-assignment-choice");
      const control=make("input");control.type="checkbox";control.value=offer.id;
      control.disabled=!assignmentUI.lead;
      control.checked=assignmentUI.chosenOffers.has(offer.id);
      control.addEventListener("change",()=>{
        if(control.checked){
          if(assignmentUI.chosenOffers.size>=200){
            control.checked=false;assignmentMessage("За одну операцию можно выбрать не больше 200 офферов.",true);return;
          }
          assignmentUI.chosenOffers.add(offer.id);
        }else assignmentUI.chosenOffers.delete(offer.id);
        assignmentMessage("");updateAssignmentSummary();
      });
      const text=make("span",undefined,"admin-assignment-choice-copy");
      text.append(make("strong",offer.name),make("small",(offer.category||"Оффер")+" · "+number(offer.payout_rub)+" ₽"));
      label.append(control,text);list.append(label);
    }
    updateAssignmentSummary();
  }
  function updateAssignmentSummary(){
    const inOfferMode=assignmentUI.mode==="offer_to_leads";
    const selected=inOfferMode?assignmentUI.chosenUsers.size:assignmentUI.chosenOffers.size;
    const targetReady=inOfferMode?Boolean(assignmentUI.offerId):Boolean(assignmentUI.lead);
    $("admin-assignment-selected-count").textContent=selected
      ?"Выбрано: "+selected+(inOfferMode?" участников":" офферов")
      :"Пока ничего не выбрано";
    $("admin-assignment-review").disabled=!selected||!targetReady||assignmentUI.loading;
    $("admin-assignment-select-all").disabled=!targetReady||assignmentUI.loading;
    $("admin-assignment-clear").disabled=!selected||assignmentUI.loading;
  }
  function renderAssignmentPeople(){
    const root=$("admin-assignment-users");
    const single=assignmentUI.mode==="lead_to_offers";
    root.replaceChildren();
    if(!assignmentUI.people.length)root.append(make("p","Подходящих активных участников не найдено.","muted"));
    for(const person of assignmentUI.people){
      const id=Number(person.id);
      const row=make("label",undefined,"admin-assignment-user admin-assignment-choice");
      const input=make("input");input.type=single?"radio":"checkbox";input.name="assignment-user-choice";
      input.value=String(id);
      input.checked=single?assignmentUI.lead?.id===id:assignmentUI.chosenUsers.has(id);
      input.setAttribute("aria-label",(single?"Выбрать лида ":"Назначить оффер участнику ")+personName(person));
      input.addEventListener("change",()=>{
        if(single){
          if(assignmentUI.lead?.id!==id)assignmentUI.chosenOffers.clear();
          assignmentUI.lead={...person,id};
          $("admin-assignment-selected-lead").textContent="Выбран: "+personName(person)+" · ID "+(person.internal_id??"—");
          $("admin-assignment-selected-lead").hidden=false;
          renderAssignmentCatalog();
          renderAssignmentPeople();
        }else{
          if(input.checked){
            if(assignmentUI.chosenUsers.size>=200){
              input.checked=false;assignmentMessage("За одну операцию можно выбрать не больше 200 участников.",true);return;
            }
            assignmentUI.chosenUsers.set(id,person);
          }else assignmentUI.chosenUsers.delete(id);
        }
        assignmentMessage("");updateAssignmentSummary();
      });
      const copy=make("span",undefined,"admin-assignment-choice-copy");
      copy.append(make("strong",personName(person)),make("small",
        "ID "+(person.internal_id??"—")+" · "+(person.username?"@"+person.username+" · ":"")+(roles[roleOf(person)]||roleOf(person))));
      row.append(input,copy);
      root.append(row);
    }
    const pages=$("admin-assignment-pagination");pages.replaceChildren();
    pages.append(make("span","Страница "+assignmentUI.page+" · всего "+number(assignmentUI.total)));
    const previous=action("Назад",()=>loadAssignmentPeople(assignmentUI.page-1));
    previous.disabled=assignmentUI.page<=1;
    const next=action("Далее",()=>loadAssignmentPeople(assignmentUI.page+1));
    next.disabled=assignmentUI.page*50>=assignmentUI.total;
    pages.append(previous,next);
    updateAssignmentSummary();
  }
  async function loadAssignmentPeople(page=1){
    if(!canManageOffers() || state.section!=="assignments")return;
    const requestId=++state.requests.assignments;
    $("admin-assignment-users").replaceChildren(make("p","Загружаем участников…","muted"));
    $("admin-assignment-pagination").replaceChildren();
    try{
      const result=await api("/admin/mvp/assignment-candidates",{
        page,query:$("admin-assignment-search").value.trim(),
        role_filter:$("admin-assignment-role-filter").value
      });
      if(requestId!==state.requests.assignments || state.section!=="assignments")return;
      assignmentUI.page=page;assignmentUI.total=Number(result.total)||0;
      assignmentUI.people=Array.isArray(result.users)?result.users:[];
      renderAssignmentPeople();
    }catch(e){
      if(requestId===state.requests.assignments){
        $("admin-assignment-users").replaceChildren(make("p",e.message,"message error"));
        assignmentMessage(e.message,true);
      }
    }
  }
  function changeAssignmentMode(mode){
    if(!["offer_to_leads","lead_to_offers"].includes(mode))return;
    assignmentUI.mode=mode;assignmentMessage("");
    const single=mode==="lead_to_offers";
    document.querySelectorAll("[data-assign-mode]").forEach(button=>
      button.setAttribute("aria-pressed",String(button.dataset.assignMode===mode)));
    $("admin-assignment-offer-heading").textContent=single?"Фильтры предложений":"Выберите оффер";
    $("admin-assignment-lead-heading").textContent=single?"Выберите одного лида":"Выберите лидов";
    $("admin-assignment-offer-target").hidden=single;
    $("admin-assignment-offers-panel").hidden=!single;
    $("admin-assignment-selected-lead").hidden=!single||!assignmentUI.lead;
    if(single && assignmentUI.lead){
      $("admin-assignment-selected-lead").textContent="Выбран: "+personName(assignmentUI.lead)+" · ID "+(assignmentUI.lead.internal_id??"—");
    }
    renderAssignmentCatalog();
    renderAssignmentPeople();
  }
  async function renderAssignmentsView(){
    if(!canManageOffers())return;
    assignmentMessage("");
    try{
      const data=await api("/admin/mvp/catalog");
      if(state.section!=="assignments")return;
      assignmentUI.catalog=Array.isArray(data.offers)?data.offers:[];
      changeAssignmentMode(assignmentUI.mode);
      await loadAssignmentPeople(1);
    }catch(e){assignmentMessage(e.message,true);}
  }
  function assignmentSelectionPayload(){
    if(assignmentUI.mode==="offer_to_leads"){
      return {mode:"offer_to_leads",offer_id:assignmentUI.offerId,
        user_ids:[...assignmentUI.chosenUsers.keys()]};
    }
    return {mode:"lead_to_offers",user_id:assignmentUI.lead?.id,
      offer_ids:[...assignmentUI.chosenOffers]};
  }
  async function reviewAssignments(){
    if(assignmentUI.loading)return;
    const payload=assignmentSelectionPayload();
    const selected=payload.user_ids||payload.offer_ids;
    if(!selected?.length || (payload.mode==="offer_to_leads"?!payload.offer_id:!payload.user_id)){
      assignmentMessage("Сначала выберите основной оффер или лида и участников назначения.",true);return;
    }
    assignmentUI.loading=true;updateAssignmentSummary();assignmentMessage("");
    try{
      const result=await api("/admin/mvp/bulk-assignment",{...payload,preview:true});
      assignmentUI.previewPayload=payload;
      const dialog=$("admin-bulk-confirm");
      $("admin-bulk-summary").textContent=payload.mode==="offer_to_leads"
        ?"Один оффер для "+result.requested+" участников."
        :result.requested+" офферов для "+personName(assignmentUI.lead)+".";
      const stats=$("admin-bulk-preview-stats");stats.replaceChildren();
      for(const [name,value] of [["Выбрано",result.requested],["Новых",result.to_create],["Уже назначено",result.already_assigned]]){
        const item=make("div",undefined,"admin-bulk-stat");
        item.append(make("span",name),make("strong",number(value)));stats.append(item);
      }
      $("admin-bulk-commit").disabled=result.to_create===0;
      $("admin-bulk-commit").textContent=result.to_create?"Назначить "+result.to_create:"Новых назначений нет";
      if(!dialog.open)dialog.showModal();
    }catch(e){assignmentMessage(e.message,true);}
    finally{assignmentUI.loading=false;updateAssignmentSummary();}
  }
  async function commitAssignments(){
    if(assignmentUI.loading || !assignmentUI.previewPayload)return;
    assignmentUI.loading=true;$("admin-bulk-commit").disabled=true;
    try{
      const result=await api("/admin/mvp/bulk-assignment",assignmentUI.previewPayload);
      $("admin-bulk-confirm").close();assignmentUI.previewPayload=null;
      assignmentUI.chosenUsers.clear();assignmentUI.chosenOffers.clear();
      assignmentMessage("Добавлено: "+result.created+". Уже было назначено: "+result.already_assigned+".");
      notice("Ручные назначения сохранены: "+result.created);
      updateAssignmentSummary();
    }catch(e){assignmentMessage(e.message,true);$("admin-bulk-commit").disabled=false;}
    finally{assignmentUI.loading=false;updateAssignmentSummary();}
  }
  function setSubtab(tab){
    if(!Object.hasOwn(subtabSection,tab))return;
    state.tab=tab;
    document.querySelectorAll("[data-subtab]").forEach(button=>{
      button.setAttribute("aria-pressed",String(button.dataset.subtab===tab));
    });
    document.querySelectorAll("[data-panel]").forEach(panel=>{
      panel.hidden=panel.dataset.panel!==tab;
    });
    if(tab==="audit")loadAudit();
    if(tab==="offer_reviews")loadOfferReviewQueue();
    if(tab==="finance")loadFinanceQueue();
  }
  async function loadFinanceQueue(){
    const root=$("admin-finance-list");
    root.replaceChildren(make("p","Загружаем заявки на вывод…","muted"));
    try{
      const response=await api("/admin/finance/withdrawals",{status:$("admin-finance-filter").value});
      if(state.tab!=="finance")return;
      root.replaceChildren();
      if(!response.withdrawals?.length){
        root.append(make("p","Заявок с таким статусом нет.","muted"));return;
      }
      const statusNames={pending:"На рассмотрении",confirmed:"Подтверждена",
        rejected:"Отклонена",paid:"Выплачена"};
      for(const payout of response.withdrawals){
        const card=make("article",undefined,"admin-offer-event-card");
        card.append(make("span",payout.display_id+" · "+payout.id.slice(-8),"section-kicker"));
        card.append(make("h3",number(payout.amount_rub)+" ₽"));
        card.append(make("p",statusNames[payout.status]||payout.status));
        if(payout.review_note)card.append(make("p","Комментарий: "+payout.review_note,"muted"));
        if(payout.status==="pending"||payout.status==="confirmed"){
          const note=make("textarea");note.maxLength=300;note.rows=2;
          note.placeholder="Причина отказа или комментарий";
          note.setAttribute("aria-label","Комментарий заявки "+payout.display_id);
          card.append(note);
          const actions=make("div",undefined,"admin-offer-event-actions");
          if(canManageOffers()){
            if(payout.status==="pending")actions.append(action("Подтвердить",async()=>{
              if(!window.confirm("Подтвердить заявку на "+number(payout.amount_rub)+" ₽? Сумма останется в резерве."))return;
              await api("/admin/finance/decision",{withdrawal_id:payout.id,decision:"confirm",note:note.value});
              notice("Заявка подтверждена");await loadFinanceQueue();
            },"primary"));
            if(payout.status==="confirmed")actions.append(action("Выплачена",async()=>{
              const payment=window.prompt("Уникальный ID реально отправленного платежа:");
              if(payment===null)return;
              if(!/^[A-Za-z0-9][A-Za-z0-9._:/-]{3,119}$/.test(payment.trim()))
                throw new Error("Нужен уникальный номер операции (4–120 символов).");
              if(!window.confirm("Отметить как фактически выплаченную сумму "+number(payout.amount_rub)+" ₽?"))return;
              await api("/admin/finance/decision",{withdrawal_id:payout.id,decision:"paid",
                payment_reference:payment.trim(),note:note.value});
              notice("Фактический платёж учтён");await loadFinanceQueue();
            },"primary"));
            actions.append(action("Отклонить",async()=>{
              if(!note.value.trim())throw new Error("Укажите причину отказа.");
              if(!window.confirm("Отклонить заявку? Зарезервированные средства вернутся в доступный баланс."))return;
              await api("/admin/finance/decision",{withdrawal_id:payout.id,decision:"reject",note:note.value});
              notice("Заявка отклонена, резерв возвращён");await loadFinanceQueue();
            }));
          }
          card.append(actions);
        }
        root.append(card);
      }
    }catch(err){root.replaceChildren(make("p",err.message,"message error"));error(err.message);}
  }
  $("admin-finance-filter").addEventListener("change",loadFinanceQueue);
  $("admin-finance-reload").addEventListener("click",loadFinanceQueue);
  async function loadOfferReviewQueue(){
    const root=$("admin-offer-event-list");
    root.replaceChildren(make("p","Загружаем заявки…","muted"));
    try{
      const response=await api("/admin/mvp/events",{status:$("admin-offer-event-filter").value});
      if(state.tab!=="offer_reviews")return;
      root.replaceChildren();
      if(!response.events?.length){
        root.append(make("p","Заявок по офферам с этим статусом нет.","muted"));return;
      }
      const statuses={pending:"На рассмотрении",approved:"Подтверждено",rejected:"Отклонено"};
      for(const event of response.events){
        const card=make("article",undefined,"admin-offer-event-card");
        card.append(make("span",event.display_id+" · "+(event.kind==="mfo_request"?"Запрос МФО":"Отчёт по этапу"),"section-kicker"));
        card.append(make("h3",event.offer_name||"Оффер"));
        const summary=make("p",(event.kind==="mfo_request"?"Запросить оффер":
          leadStageOptions[event.lead_stage]||event.lead_stage)+" · "+
          (statuses[event.review_status]||event.review_status));
        card.append(summary);
        if(event.proof_url){
          const link=make("a","Открыть ссылку подтверждения ↗","btn ghost");
          link.href=event.proof_url;link.target="_blank";link.rel="noopener noreferrer";
          link.referrerPolicy="no-referrer";card.append(link);
        }
        if(event.has_screenshot)card.append(action("Посмотреть скриншот",async()=>{
          const result=await api("/admin/mvp/evidence",{event_id:event.id});
          if(result.mime!=="image/webp"||typeof result.data!=="string")throw new Error("Неверный формат файла");
          const bytes=Uint8Array.from(atob(result.data),character=>character.charCodeAt(0));
          const blob=new Blob([bytes],{type:"image/webp"});
          const objectUrl=URL.createObjectURL(blob);
          const preview=make("dialog");preview.className="admin-offer-evidence-dialog";
          const image=make("img");image.alt="Скриншот, присланный участником";image.src=objectUrl;
          const close=make("button","Закрыть","btn ghost");close.type="button";
          close.addEventListener("click",()=>preview.close());
          preview.append(close,image);document.body.append(preview);
          preview.addEventListener("close",()=>{URL.revokeObjectURL(objectUrl);preview.remove();},{once:true});
          preview.showModal();
        }));
        if(event.review_status==="pending"){
          const note=make("textarea");note.rows=2;note.maxLength=300;
          note.placeholder="Комментарий (обязателен при отказе)";
          note.setAttribute("aria-label","Комментарий решения для "+event.display_id);
          const actions=make("div",undefined,"admin-offer-event-actions");
          actions.append(action("Подтвердить",async()=>{
            if(!window.confirm("Подтвердить результат? Это не подтверждение банковского начисления."))return;
            await api("/admin/mvp/review-event",{event_id:event.id,decision:"approve",note:note.value});
            notice("Отчёт подтверждён менеджером");await loadOfferReviewQueue();
          },"primary"),action("Отклонить",async()=>{
            if(!note.value.trim()){error("Укажите причину отклонения.");return;}
            await api("/admin/mvp/review-event",{event_id:event.id,decision:"reject",note:note.value});
            notice("Заявка отклонена");await loadOfferReviewQueue();
          }));
          card.append(note,actions);
        }else if(event.review_note)card.append(make("p","Комментарий: "+event.review_note,"muted"));
        root.append(card);
      }
    }catch(err){root.replaceChildren(make("p",err.message,"message error"));error(err.message);}
  }
  $("admin-offer-event-filter").addEventListener("change",loadOfferReviewQueue);
  $("admin-offer-event-reload").addEventListener("click",loadOfferReviewQueue);
  function navigateSection(section,{subtab,addHistory=false}={}){
    if(!Object.hasOwn(sections,section))return;
    if(!canManageOffers() && ["offers","assignments"].includes(section))return;
    const tab=subtab && subtabSection[subtab]===section?subtab:
      (subtabSection[state.tab]===section?state.tab:defaultSubtab[section]);
    if(addHistory && (section!==state.section || (tab && tab!==state.tab))){
      history.pushState({...history.state,adminSection:section,...(tab?{adminTab:tab}:{})},"",location.href);
    }
    state.section=section;
    document.querySelectorAll("[data-section]").forEach(button=>{
      if(button.dataset.section===section)button.setAttribute("aria-current","page");
      else button.removeAttribute("aria-current");
    });
    document.querySelectorAll("[data-workspace]").forEach(workspace=>{
      workspace.hidden=workspace.dataset.workspace!==section;
    });
    if(tab)setSubtab(tab);
    const overview=section==="overview";
    document.querySelector(".admin-hero").hidden=!overview;
    const intro=$("admin-screen-intro");intro.hidden=overview;
    const screen=sections[section];
    document.querySelector(".admin-topline-index").textContent="— "+screen.number;
    if(!overview){
      $("admin-screen-crumb").textContent="CONTROL CENTER / "+screen.name.toUpperCase();
      $("admin-screen-index").textContent=screen.number+" / 05";
      $("admin-screen-heading").textContent=screen.name+".";
      $("admin-screen-description").textContent=screen.description;
      $("admin-screen-symbol").textContent=screen.number;
    }
    document.title="The Affiliates — "+screen.name;
    window.scrollTo({top:0,behavior:"instant"});
    if(section==="offers")renderOffersView();
    if(section==="assignments")renderAssignmentsView();
  }
  function navigateTab(tab,addHistory=false){
    if(!Object.hasOwn(subtabSection,tab))return;
    navigateSection(subtabSection[tab],{subtab:tab,addHistory});
  }
  $("invite-form").addEventListener("submit",async e=>{
    e.preventDefault();error("");const submit=$("invite-submit");submit.disabled=true;
    try {
      const id=$("assignee").value.trim();
      if(id && (!/^[1-9][0-9]*$/.test(id) || !Number.isSafeInteger(Number(id))))throw new Error("Укажите корректный Telegram ID ответственного.");
      const candidateLabel=$("candidate-label").value.trim();
      const data=await api("/admin/invitations",{...(id?{assignee_id:Number(id)}:{}),candidate_label:candidateLabel});
      const code=data.invite_code || data.code;
      const url=data.link || data.url || (typeof code==="string" && /^ag_[a-zA-Z0-9_-]{8,48}$/.test(code) ? "https://t.me/affialite_partners_bot?start="+encodeURIComponent(code) : "");
      const result=$("invite-result");result.replaceChildren();
      result.append(make("strong",code ? "Код: "+code : "Приглашение создано"));
      if(url && /^https:\/\//.test(url)){const input=make("input");input.value=url;input.readOnly=true;input.setAttribute("aria-label","Ссылка приглашения");result.append(input);}
      show("invite-result",true);notice("Приглашение создано.");await loadDashboard();
    }catch(err){error(err.message);}finally{submit.disabled=false;}
  });
  document.querySelectorAll("[data-section]").forEach(button=>
    button.addEventListener("click",()=>navigateSection(button.dataset.section,{addHistory:true})));
  document.querySelectorAll("[data-subtab]").forEach(button=>
    button.addEventListener("click",()=>navigateTab(button.dataset.subtab,true)));
  document.querySelectorAll("[data-go-section]").forEach(button=>
    button.addEventListener("click",()=>navigateSection(button.dataset.goSection,
      {subtab:button.dataset.goSubtab,addHistory:true})));
  window.addEventListener("popstate",event=>{
    const tab=event.state?.adminTab;
    const section=event.state?.adminSection || subtabSection[tab] || "overview";
    navigateSection(section,{subtab:tab});
  });
  let searchDelay;
  $("user-query").addEventListener("input",()=>{
    clearTimeout(searchDelay);
    ++state.requests.users;
    $("users-list").replaceChildren(make("p","Поиск…","muted"));
    searchDelay=setTimeout(()=>loadUsersPage("users",1),220);
  });
  $("user-filter").addEventListener("change",()=>loadUsersPage("users",1));
  $("role-filter").addEventListener("change",()=>loadUsersPage("users",1));
  document.querySelectorAll("[data-assign-mode]").forEach(button=>
    button.addEventListener("click",()=>changeAssignmentMode(button.dataset.assignMode)));
  $("admin-assignment-offer").addEventListener("change",event=>{
    if(assignmentUI.offerId!==event.target.value)assignmentUI.chosenUsers.clear();
    assignmentUI.offerId=event.target.value;assignmentMessage("");updateAssignmentSummary();
    renderAssignmentPeople();
  });
  let assignmentSearchDelay;
  $("admin-assignment-search").addEventListener("input",()=>{
    clearTimeout(assignmentSearchDelay);
    ++state.requests.assignments;
    assignmentSearchDelay=setTimeout(()=>loadAssignmentPeople(1),220);
  });
  $("admin-assignment-role-filter").addEventListener("change",()=>loadAssignmentPeople(1));
  $("admin-assignment-offer-search").addEventListener("input",()=>renderAssignmentCatalog());
  $("admin-assignment-category-filter").addEventListener("change",()=>renderAssignmentCatalog());
  $("admin-assignment-select-all").addEventListener("click",()=>{
    if(assignmentUI.mode==="offer_to_leads"){
      const next=new Map(assignmentUI.chosenUsers);
      for(const person of assignmentUI.people)next.set(Number(person.id),person);
      if(next.size>200){assignmentMessage("За одну операцию можно выбрать не больше 200 участников.",true);return;}
      assignmentUI.chosenUsers=next;renderAssignmentPeople();
    }else{
      const next=new Set(assignmentUI.chosenOffers);
      for(const offer of filteredAssignmentOffers())next.add(offer.id);
      if(next.size>200){assignmentMessage("За одну операцию можно выбрать не больше 200 офферов.",true);return;}
      assignmentUI.chosenOffers=next;renderAssignmentCatalog();
    }
    assignmentMessage("");updateAssignmentSummary();
  });
  $("admin-assignment-clear").addEventListener("click",()=>{
    if(assignmentUI.mode==="offer_to_leads"){
      assignmentUI.chosenUsers.clear();renderAssignmentPeople();
    }else{
      assignmentUI.chosenOffers.clear();renderAssignmentCatalog();
    }
    assignmentMessage("");updateAssignmentSummary();
  });
  $("admin-assignment-review").addEventListener("click",reviewAssignments);
  $("admin-bulk-cancel").addEventListener("click",()=>$("admin-bulk-confirm").close());
  $("admin-bulk-confirm").addEventListener("close",()=>{assignmentUI.previewPayload=null;});
  $("admin-bulk-commit").addEventListener("click",commitAssignments);
  $("reload").addEventListener("click",async()=>{error("");try{await loadDashboard();if(state.tab==="audit")await loadAudit();notice("Данные обновлены.");}catch(e){error(e.message);}});
  const catalogButton=$("mvp-catalog-anchor");
  catalogButton.id="mvp-catalog-open";
  catalogButton.addEventListener("click",()=>{error("");openOfferCatalog().catch(e=>error(e.message));});
  $("admin-primary-action").addEventListener("click",()=>navigateTab("pending",true));
  async function start(){
    try{tg?.ready();tg?.expand();tg?.setHeaderColor?.("#080909");}catch{}
    if(!initData()){show("no-access",true);$("no-access-message").textContent="Откройте панель через Telegram Mini App.";return;}
    try {
      const session=await api("/session");
      const role=session.role || session.user?.role;
      state.role=role;
      state.actorId=Number(session.user?.id);
      const managerAccess=canManageOffers();
      document.querySelectorAll("[data-owner-admin]").forEach(el=>el.hidden=!managerAccess);
      catalogButton.hidden=!managerAccess;
      const status=session.status || session.user?.status;
      if(!["owner","admin","staff"].includes(role) || (status && !["active","approved"].includes(status))){
        show("no-access",true);return;
      }
      await loadDashboard();show("admin-app",true);document.body.classList.add("admin-authenticated");
      const tab=history.state?.adminTab;
      navigateSection(history.state?.adminSection||subtabSection[tab]||"overview",{subtab:tab});
    }catch(e){show("no-access",true);$("no-access-message").textContent=e.message;}
  }
  start();
})();
