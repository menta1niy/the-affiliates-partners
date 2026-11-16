(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const tg = window.Telegram?.WebApp;
  const state = {users:[],pending:[],invites:[],tab:"pending",role:"",actorId:null,
    pages:{users:1,pending:1},requests:{users:0,pending:0}};
  let participantRequestId = 0;
  const roles = {owner:"Владелец",admin:"Администратор",staff:"Сотрудник",referrer:"Реферер",lead:"Участник",manager:"Менеджер"};
  const statuses = {pending:"Ожидает",active:"Активен",approved:"Подтверждён",rejected:"Отклонён",blocked:"Заблокирован"};
  const manualStages={assigned:"Назначено",in_progress:"В работе",submitted:"На проверке",completed:"Завершено",rejected:"Отклонено"};
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
  async function openOfferCatalog(){
    let dialog=$("mvp-catalog-dialog");
    if(!dialog){dialog=make("dialog");dialog.id="mvp-catalog-dialog";dialog.className="panel admin-catalog-dialog";document.body.append(dialog);}
    dialog.replaceChildren();
    const top=make("div",undefined,"admin-dialog-toolbar");
    top.append(make("span","КАТАЛОГ / CONTROL","section-kicker"),action("Закрыть",()=>dialog.close()));
    dialog.append(top,make("h2","Каталог офферов"));
    dialog.append(make("p","Параметры и условия банковских предложений. Указанная ставка не является подтверждённым начислением.","muted"));
    const list=make("div",undefined,"admin-catalog-list");dialog.append(list);
    const fields=[["name","Название","text"],["category","Категория","text"],["target_action","Целевое действие","text"],["payout_rub","Оплата, ₽","number"],["hold_days","Холд, дней","number"],["instructions","Инструкция","text"],["referral_url","HTTPS-ссылка","url"]];
    const form=make("form");form.className="form-grid";
    const inputs={};let editingId=null;
    const heading=make("h3","Добавить оффер");form.append(heading);
    for(const [key,label,type] of fields){const wrap=make("label",label);const input=make("input");input.type=type;input.name=key;input.maxLength=key==="instructions"?2000:2048;if(type==="number"){input.min="0";input.step="1";}if(key==="payout_rub"||key==="hold_days")input.value="0";inputs[key]=input;wrap.append(input);form.append(wrap);}
    const active=make("input");active.type="checkbox";active.checked=true;const activeLabel=make("label"," Доступен для назначений");activeLabel.prepend(active);form.append(activeLabel);
    const save=make("button","Сохранить оффер","btn primary");save.type="submit";form.append(save);
    form.addEventListener("submit",async e=>{e.preventDefault();save.disabled=true;try{
      const payload={};for(const [key] of fields)payload[key]=inputs[key].value.trim();
      payload.payout_rub=Number(payload.payout_rub);payload.hold_days=Number(payload.hold_days);payload.active=active.checked;
      if(editingId)payload.offer_id=editingId;
      await api("/admin/mvp/offer",payload);editingId=null;heading.textContent="Добавить оффер";form.reset();inputs.payout_rub.value="0";inputs.hold_days.value="0";await reload();notice("Оффер сохранён");
    }catch(err){error(err.message);}finally{save.disabled=false;}});
    const canEdit=state.role==="owner";
    if(canEdit){form.classList.add("admin-catalog-form");dialog.append(form);}
    else dialog.append(make("p","Для вашей роли доступен просмотр каталога. Изменение общего каталога выполняет владелец.","message"));
    async function reload(){
      list.replaceChildren(make("p","Загрузка…"));
      const data=await api("/admin/mvp/catalog");list.replaceChildren();
      const offers=Array.isArray(data.offers)?data.offers:[];
      if(!offers.length){list.append(make("p","Офферы пока не добавлены.","empty"));return;}
      for(const offer of offers){
        const item=make("article",undefined,"admin-catalog-card");
        const meta=make("div",undefined,"admin-catalog-card-heading");
        const name=make("div");name.append(make("span",offer.category||"Банковский оффер","section-kicker"),make("h3",offer.name));
        const availability=make("span",offer.active?"Доступен":"Отключён","pill");
        availability.dataset.status=offer.active?"active":"blocked";meta.append(name,availability);
        item.append(meta);
        const terms=make("div",undefined,"admin-catalog-terms");
        for(const [key,value] of [["СТАВКА",number(offer.payout_rub)+" ₽"],["ХОЛД",(offer.hold_days??"—")+" дн."],["ЦЕЛЕВОЕ ДЕЙСТВИЕ",offer.target_action||"—"]]){
          const row=make("div");row.append(make("span",key),make("strong",value));terms.append(row);
        }
        item.append(terms);
        if(canEdit)item.append(action("Редактировать",()=>{editingId=offer.id;heading.textContent="Редактировать оффер";for(const [key] of fields)inputs[key].value=offer[key]??"";active.checked=!!offer.active;form.scrollIntoView({behavior:"smooth"});}));
        list.append(item);
      }
    }
    dialog.showModal();await reload();
  }
  function switchTab(tab){
    state.tab=tab;
    document.querySelectorAll("[data-tab]").forEach(button=>button.setAttribute("aria-selected",String(button.dataset.tab===tab)));
    document.querySelectorAll("[data-panel]").forEach(panel=>panel.hidden=panel.dataset.panel!==tab);
    if(tab==="audit")loadAudit();
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
  document.querySelectorAll("[data-tab]").forEach(button=>button.addEventListener("click",()=>switchTab(button.dataset.tab)));
  let searchDelay;
  $("user-query").addEventListener("input",()=>{
    clearTimeout(searchDelay);
    ++state.requests.users;
    $("users-list").replaceChildren(make("p","Поиск…","muted"));
    searchDelay=setTimeout(()=>loadUsersPage("users",1),220);
  });
  $("user-filter").addEventListener("change",()=>loadUsersPage("users",1));
  $("role-filter").addEventListener("change",()=>loadUsersPage("users",1));
  $("reload").addEventListener("click",async()=>{error("");try{await loadDashboard();if(state.tab==="audit")await loadAudit();notice("Данные обновлены.");}catch(e){error(e.message);}});
  const catalogButton=$("mvp-catalog-anchor");
  catalogButton.id="mvp-catalog-open";
  catalogButton.addEventListener("click",()=>{error("");openOfferCatalog().catch(e=>error(e.message));});
  $("admin-primary-action").addEventListener("click",()=>{switchTab("pending");document.querySelector('[data-panel="pending"]').scrollIntoView({behavior:"smooth",block:"start"});});
  async function start(){
    try{tg?.ready();tg?.expand();tg?.setHeaderColor?.("#080909");}catch{}
    if(!initData()){show("no-access",true);$("no-access-message").textContent="Откройте панель через Telegram Mini App.";return;}
    try {
      const session=await api("/session");
      const role=session.role || session.user?.role;
      state.role=role;
      state.actorId=Number(session.user?.id);
      catalogButton.hidden=!(["owner","admin"].includes(role));
      const status=session.status || session.user?.status;
      if(!["owner","admin","staff"].includes(role) || (status && !["active","approved"].includes(status))){
        show("no-access",true);return;
      }
      await loadDashboard();show("admin-app",true);document.body.classList.add("admin-authenticated");
    }catch(e){show("no-access",true);$("no-access-message").textContent=e.message;}
  }
  start();
})();
