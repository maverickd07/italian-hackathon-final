(() => {
  'use strict';
  try { sessionStorage.removeItem('relay-crm-token'); localStorage.removeItem('relay-crm-token'); } catch { /* Optional browser storage. */ }
  const config = JSON.parse(document.querySelector('#relay-ui-context').textContent);
  const identityKey = 'relay-crm-user';
  const identitySelect = document.querySelector('#who-am-i');
  const locationUrl = new URL(window.location.href);
  try {
    const saved = localStorage.getItem(identityKey);
    if (!locationUrl.searchParams.has('user') && saved && saved !== config.user) {
      locationUrl.searchParams.set('user', saved);
      window.location.replace(locationUrl.toString());
      return;
    }
    if (config.user) localStorage.setItem(identityKey, config.user);
  } catch { /* Read-only browsing still works without persistent storage. */ }
  identitySelect.addEventListener('change', () => {
    try { localStorage.setItem(identityKey, identitySelect.value); } catch { /* Optional persistence. */ }
    const url = new URL(window.location.href);
    url.searchParams.set('user', identitySelect.value);
    ['team', 'after', 'before', 'callbacks_after', 'kickoffs_after', 'dormant_after'].forEach(key => url.searchParams.delete(key));
    window.location.assign(url.toString());
  });
  document.querySelectorAll('a[href]').forEach(link => {
    const url = new URL(link.href, window.location.href);
    if (url.origin === window.location.origin && !url.pathname.startsWith('/ui-static/')) {
      if (config.user) url.searchParams.set('user', config.user);
      if (config.team && !url.searchParams.has('team')) url.searchParams.set('team', '1');
      link.href = url.toString();
    }
  });
  document.querySelectorAll('form[method="get"], form.filters').forEach(form => {
    if (!form.querySelector('[name="user"]')) {
      const field = document.createElement('input'); field.type = 'hidden'; field.name = 'user'; field.value = config.user; form.append(field);
    }
    if (config.team && !form.querySelector('[name="team"]')) {
      const field = document.createElement('input'); field.type = 'hidden'; field.name = 'team'; field.value = '1'; form.append(field);
    }
  });
  // Remove credentials left by older versions; never store a new token in the browser.
  const toast = message => { const node = document.querySelector('#toast'); node.textContent = message; node.hidden = false; setTimeout(() => { node.hidden = true; }, 6000); };
  const clearPrivateHistory = () => {
    try { Object.keys(sessionStorage).filter(key => key.startsWith('relay-crm-chat:')).forEach(key => sessionStorage.removeItem(key)); } catch { /* Storage can be disabled. */ }
  };
  const expire = () => {
    clearPrivateHistory();
    const next = window.location.pathname + window.location.search;
    window.location.assign('/login?expired=1&next=' + encodeURIComponent(next));
  };
  async function uiFetch(path, options = {}) {
    const response = await fetch(path, {...options, credentials:'same-origin', headers:{...options.headers, 'X-CSRF-Token':config.csrf}});
    if (response.status === 401) { expire(); throw new Error('SESSION_EXPIRED'); }
    return response;
  }
  document.querySelector('#logout').onclick = async event => {
    const button = event.currentTarget; button.disabled = true;
    try {
      const response = await uiFetch('/ui-api/logout', {method:'POST'});
      if (!response.ok) throw new Error('Could not sign out. Reload the page and try again.');
      clearPrivateHistory(); window.location.assign('/login');
    } catch (error) { if (error.message !== 'SESSION_EXPIRED') toast(error.message); button.disabled = false; }
  };
  document.querySelectorAll('.move-deal').forEach(select => {
    select.disabled = false;
    select.addEventListener('change', async () => {
      const oldStage = select.closest('.column').dataset.stage;
      select.disabled = true;
      try {
        const response = await uiFetch('/ui-api/deals/' + encodeURIComponent(select.closest('.deal-card').dataset.id), {
          method: 'PATCH', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({properties:{dealstage:select.value}})
        });
        if (!response.ok) {
          const body = await response.json();
          throw new Error(body.message || 'Could not move this deal.');
        }
        window.location.reload();
      } catch (error) { select.value = oldStage; select.disabled = false; if (error.message !== 'SESSION_EXPIRED') toast(error.message); }
    });
  });
  window.RelayCRM = {config, uiFetch, expire, toast};
  const remaining = Date.parse(config.expiresAt) - Date.now();
  if (Number.isFinite(remaining)) setTimeout(expire, Math.max(0, Math.min(remaining, 2147483647)));
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
})();
