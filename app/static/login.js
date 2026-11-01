(() => {
  'use strict';
  try { sessionStorage.removeItem('relay-crm-token'); localStorage.removeItem('relay-crm-token'); } catch { /* Storage can be disabled. */ }
  try { Object.keys(sessionStorage).filter(key => key.startsWith('relay-crm-chat:')).forEach(key => sessionStorage.removeItem(key)); } catch { /* Storage can be disabled. */ }
  window.addEventListener('pageshow', () => { document.querySelector('#login-token').value = ''; });
})();
