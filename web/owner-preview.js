(() => {
  'use strict';
  const samples = [
    { name: 'Дебетовая карта · пример А', stage: 'В работе', className: 'working', note: 'Участник изучает условия и инструкцию' },
    { name: 'Банковская карта · пример Б', stage: 'Заявка отправлена', className: 'working', note: 'Ожидается подтверждение банка в CRM' },
    { name: 'Счёт · пример В', stage: 'Выполнено · пример', className: 'done', note: 'Демонстрация завершённого задания, не банковское подтверждение' },
    { name: 'Карта · пример Г', stage: 'Выполнено · пример', className: 'done', note: 'Демонстрация истории; не создаёт выплату' }
  ];
  const make = (tag, className, value) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value) el.textContent = value;
    return el;
  };
  window.renderOwnerLeadPreview = (session) => {
    const target = document.getElementById('owner-preview');
    if (!target) return;
    const isOwner = session?.role === 'owner' || session?.user?.role === 'owner';
    target.hidden = !isOwner;
    target.replaceChildren();
    if (!isOwner) return;
    const heading = make('div', 'owner-preview-heading');
    heading.append(make('span', 'section-kicker', 'ДЕМО • ТОЛЬКО ДЛЯ ВЛАДЕЛЬЦА'), make('h2', '', 'Пример заполненного кабинета'));
    target.append(heading, make('p', 'muted', 'Вымышленные задания и статусы для оценки дизайна. Не связаны с CRM, банками, начислениями или реальными офферами.'));
    const stats = make('div', 'owner-preview-stats');
    for (const [label, number] of [['Всего заданий', '4'], ['В работе', '2'], ['Выполнено в демо', '2']]) {
      const stat = make('div', 'metric');
      stat.append(make('span', '', label), make('strong', '', number));
      stats.append(stat);
    }
    target.append(stats);
    const cards = make('div', 'owner-preview-grid');
    for (const example of samples) {
      const card = make('article', 'owner-preview-card');
      card.append(make('span', `owner-preview-status ${example.className}`, example.stage), make('h3', '', example.name), make('p', 'muted', example.note));
      cards.append(card);
    }
    target.append(cards);
  };
})();
