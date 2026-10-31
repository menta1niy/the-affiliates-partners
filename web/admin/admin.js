(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const tg = window.Telegram?.WebApp;
  const state = {users:[],pending:[],invites:[],tab:"pending",role:"",actorId:null};
  const roles = {owner:"Владелец",admin:"Администратор",staff:"Сотрудник",referrer:"Реферер",lead:"Участник",manager:"Менеджер"};
  const statuses = {pending:"Ожидает",active:"Активен",approved:"Подтверждён",rejected:"Отклонён",blocked:"Заблокирован"};
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
  function action(label,fn){const button=make("button",label,"btn ghost");button.type="button";button.addEventListener("click",async()=>{button.disabled=true;error("");try{await fn();}catch(e){error(e.message);}finally{button.disabled=false;}});return button;}
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
      const actions=make("td");const group=make("div",undefined,"actions");
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
      actions.append(group);row.append(actions);body.append(row);
    });
    table.append(body);container.append(table);
  }
  function renderUsers(){
    const query=$("user-query").value.trim().toLowerCase();
    const filter=$("user-filter").value;
    const roleFilter=$("role-filter").value;
    const users=state.users.filter(user=>{
      const haystack=[user.internal_id,user.id,user.user_id,user.first_name,user.last_name,user.username,user.name,user.role,user.manager_id,user.agency_id,user.referrer_id,user.introduced_by_id,user.source].join(" ").toLowerCase();
      return (!filter || statusOf(user)===filter) && (!roleFilter || roleOf(user)===roleFilter) && (!query || haystack.includes(query));
    });
    renderTable($("users-list"),users,"users");
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
        const link="https://t.me/affiliates_partners_bot?start="+encodeURIComponent(invite.code);
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
    renderTable($("pending-list"),pending,"pending");renderUsers();
    renderInvites();
  }
  async function loadDashboard(){const data=await api("/admin/dashboard");renderDashboard(data);}
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
      const url=data.link || data.url || (typeof code==="string" && /^ag_[a-zA-Z0-9_-]{8,48}$/.test(code) ? "https://t.me/affiliates_partners_bot?start="+encodeURIComponent(code) : "");
      const result=$("invite-result");result.replaceChildren();
      result.append(make("strong",code ? "Код: "+code : "Приглашение создано"));
      if(url && /^https:\/\//.test(url)){const input=make("input");input.value=url;input.readOnly=true;input.setAttribute("aria-label","Ссылка приглашения");result.append(input);}
      show("invite-result",true);notice("Приглашение создано.");await loadDashboard();
    }catch(err){error(err.message);}finally{submit.disabled=false;}
  });
  document.querySelectorAll("[data-tab]").forEach(button=>button.addEventListener("click",()=>switchTab(button.dataset.tab)));
  $("user-query").addEventListener("input",renderUsers);$("user-filter").addEventListener("change",renderUsers);$("role-filter").addEventListener("change",renderUsers);
  $("reload").addEventListener("click",async()=>{error("");try{await loadDashboard();if(state.tab==="audit")await loadAudit();notice("Данные обновлены.");}catch(e){error(e.message);}});
  async function start(){
    try{tg?.ready();tg?.expand();tg?.setHeaderColor?.("#111310");}catch{}
    if(!initData()){show("no-access",true);$("no-access-message").textContent="Откройте панель через Telegram Mini App.";return;}
    try {
      const session=await api("/session");
      const role=session.role || session.user?.role;
      state.role=role;
      state.actorId=Number(session.user?.id);
      const status=session.status || session.user?.status;
      if(!["owner","admin","staff"].includes(role) || (status && !["active","approved"].includes(status))){
        show("no-access",true);return;
      }
      await loadDashboard();show("admin-app",true);
    }catch(e){show("no-access",true);$("no-access-message").textContent=e.message;}
  }
  start();
})();
