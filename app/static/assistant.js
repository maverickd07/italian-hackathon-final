(() => {
  'use strict';
  const crm = window.RelayCRM;
  if (!crm) return;
  const surfaces = [...document.querySelectorAll('[data-chat-surface]')];
  const drawer = document.querySelector('#assistant-drawer');
  const companion = document.querySelector('#companion-toggle');
  const historyKey = 'relay-crm-chat:' + crm.config.user;
  let history = [], busy = false, attachment = null;
  try {
    const saved = JSON.parse(sessionStorage.getItem(historyKey) || '[]');
    if (Array.isArray(saved) && saved.every(m => m && ['user','assistant'].includes(m.role) && typeof m.content === 'string' && (m.attachments === undefined || (Array.isArray(m.attachments) && m.attachments.every(file => file && typeof file.name === 'string' && typeof file.content === 'string'))))) history = saved;
  } catch { /* Keep the conversation in memory when storage is unavailable. */ }
  const save = () => { try { sessionStorage.setItem(historyKey, JSON.stringify(history)); } catch { /* Retain the full history in memory. */ } };
  const status = message => surfaces.forEach(s => { s.querySelector('.chat-status').textContent = message; });
  const setBusy = value => {
    busy = value;
    surfaces.forEach(s => {
      s.querySelector('.chat-send').disabled = value || !crm.config.user;
      s.querySelector('.chat-file').disabled = value;
      s.querySelector('.chat-reset').disabled = value;
      s.querySelectorAll('[data-confirm]').forEach(button => { button.disabled = value; });
    });
  };
  const draw = () => {
    const last = history[history.length-1];
    const confirm = last?.role === 'assistant' && /confermi|conferma(?:re)?[?.]|vuoi che|sei sicur|posso (?:procedere|eseguire)|procedo\?|attendo (?:la|una) conferma|in attesa (?:di|della) conferma|bisogno.*conferma|confirm.*\?/i.test(last.content);
    surfaces.forEach(surface => {
      const log = surface.querySelector('.chat-messages');
      if (history.length) log.replaceChildren();
      history.forEach(message => {
        const node = document.createElement('article'); node.className = 'chat-message ' + message.role;
        const author = document.createElement('small'); author.textContent = message.role === 'user' ? 'You' : 'Relay Assistant';
        const text = document.createElement('p'); text.textContent = message.content;
        node.append(author, text);
        (message.attachments || []).forEach(file => { const label = document.createElement('small'); label.textContent = 'CSV · ' + file.name; node.append(label); });
        log.append(node);
      });
      log.scrollTop = log.scrollHeight;
      surface.querySelector('.chat-confirm').hidden = !confirm;
      const file = surface.querySelector('.chat-attachment');
      file.hidden = !attachment; file.replaceChildren();
      if (attachment) {
        const label = document.createElement('span'); label.textContent = 'CSV · ' + attachment.name;
        const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'text-button'; remove.textContent = 'Remove';
        remove.onclick = () => { attachment = null; surfaces.forEach(s => { s.querySelector('.chat-file').value = ''; }); draw(); };
        file.append(label, remove);
      }
    });
  };
  const open = () => { if (!drawer || !companion) return; drawer.hidden = false; companion.closest('.companion-wrap').hidden = true; companion.setAttribute('aria-expanded','true'); draw(); drawer.querySelector('.chat-input').focus(); };
  const close = () => { if (!drawer || !companion) return; drawer.hidden = true; companion.closest('.companion-wrap').hidden = false; companion.setAttribute('aria-expanded','false'); companion.focus(); };
  if (companion) companion.onclick = () => drawer.hidden ? open() : close();
  document.querySelector('.companion-hint')?.addEventListener('click', open);
  document.querySelectorAll('.chat-close').forEach(button => { button.onclick = close; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && drawer && !drawer.hidden) close(); });
  async function send(text, files = []) {
    if (busy || !text.trim()) return;
    if (!crm.config.user) { status('Choose an active CRM user first.'); return; }
    setBusy(true); status('Relay is thinking…');
    history.push({role:'user',content:text.trim(),attachments:files}); save();
    surfaces.forEach(s => { s.querySelector('.chat-input').value = ''; s.querySelector('.chat-file').value = ''; });
    attachment = null; draw();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 65000);
    try {
      const reply = await window.RelayChatClient.request({csrf:crm.config.csrf,user:crm.config.user,history,signal:controller.signal});
      history.push({role:'assistant',content:reply}); save(); status('');
    } catch (error) {
      if (error.message === 'SESSION_EXPIRED') { crm.expire(); }
      else if (error.message === 'ASSISTANT_DISABLED') status('AI chat is disabled in this test environment. No model call was made and no records were changed.');
      else status('Assistant offline. The request could not be completed. Check your CRM before retrying.');
    } finally { clearTimeout(timeout); setBusy(false); draw(); }
  }
  surfaces.forEach(surface => {
    surface.querySelector('.chat-form').onsubmit = event => { event.preventDefault(); send(surface.querySelector('.chat-input').value, attachment ? [attachment] : []); };
    const input = surface.querySelector('.chat-input');
    let composing = false;
    input.addEventListener('compositionstart', () => { composing = true; });
    input.addEventListener('compositionend', () => { composing = false; });
    input.addEventListener('keydown', event => {
      if (event.key !== 'Enter' || event.shiftKey || event.isComposing || composing || event.keyCode === 229) return;
      event.preventDefault();
      if (!event.repeat && !busy) surface.querySelector('.chat-form').requestSubmit();
    });
    surface.querySelectorAll('[data-suggestion]').forEach(button => { button.onclick = () => { const input = surface.querySelector('.chat-input'); input.value = button.dataset.suggestion; input.focus(); }; });
    surface.querySelectorAll('[data-confirm]').forEach(button => { button.onclick = () => send(button.dataset.confirm); });
    surface.querySelector('.chat-reset').onclick = () => {
      history = []; attachment = null; save(); status('');
      surfaces.forEach(s => { s.querySelector('.chat-messages').replaceChildren(); s.querySelector('.chat-input').value = crm.config.record ? 'Parliamo di ' + crm.config.record + '. ' : ''; });
      draw();
    };
    surface.querySelector('.chat-file').onchange = async event => {
      const file = event.target.files[0]; if (!file) return;
      if (!/\.csv$/i.test(file.name) || file.size > 2 * 1024 * 1024) { status('Choose a CSV file smaller than 2 MB.'); event.target.value = ''; return; }
      setBusy(true);
      try {
        const bytes = await file.arrayBuffer();
        let content = new TextDecoder('utf-8').decode(bytes);
        if (content.includes('\uFFFD')) content = new TextDecoder('windows-1252').decode(bytes);
        attachment = {name:file.name,content_type:'text/csv',content}; status('CSV attached. It will be sent with your next message.');
      } catch { status('Could not read this CSV file.'); }
      finally { setBusy(false); draw(); }
    };
  });
  if (!crm.config.user) status('No active CRM users are available.');
  setBusy(false); draw();
  // Keep normal navigation immediate; animate the real pet on the next page.
  const pet = document.querySelector('.chat-pet-arrival');
  const returnKey = 'relay-crm-pet-return';
  let reducedMotion = true;
  try { reducedMotion = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : true; } catch { /* Unsupported media queries use a static pet. */ }
  if (pet) {
    document.addEventListener('click', event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || reducedMotion) return;
      const link = event.target.closest?.('a[href]');
      if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
      try {
        const destination = new URL(link.href, window.location.href);
        if (destination.origin !== window.location.origin || destination.pathname === '/assistant' || destination.hash) return;
        const box = pet.getBoundingClientRect();
        sessionStorage.setItem(returnKey, JSON.stringify({
          x: (box.left + box.width / 2) / window.innerWidth,
          y: (box.top + box.height / 2) / window.innerHeight,
          path: destination.pathname, at: Date.now()
        }));
      } catch { /* Navigation remains independent of storage and animation. */ }
    });
  }
  let returning = null;
  try {
    const saved = sessionStorage.getItem(returnKey);
    sessionStorage.removeItem(returnKey);
    if (saved) {
      const value = JSON.parse(saved);
      if (value.path === window.location.pathname && Date.now() - value.at < 10000 && Date.now() >= value.at && Number.isFinite(value.x) && Number.isFinite(value.y)) returning = value;
    }
  } catch { /* A static companion is the fallback. */ }
  const animatedPet = pet || (returning ? companion : null);
  if (animatedPet && !reducedMotion && typeof animatedPet.animate === 'function') {
    try {
      const box = animatedPet.getBoundingClientRect();
      const startX = returning ? returning.x * window.innerWidth : window.innerWidth - 66;
      const startY = returning ? returning.y * window.innerHeight : window.innerHeight - 66;
      const x = startX - (box.left + box.width / 2);
      const y = startY - (box.top + box.height / 2);
      animatedPet.animate([
        {transform: `translate(${x}px, ${y}px) rotate(-10deg)`},
        {transform: `translate(${x * .45}px, ${y * .45}px) rotate(8deg)`, offset: .55},
        {transform: 'translate(0, 0) rotate(0deg)'}
      ], {duration: 650, easing: 'cubic-bezier(.2,.7,.2,1)'});
    } catch { /* Unsupported animation must never affect chat initialization. */ }
  }
})();
