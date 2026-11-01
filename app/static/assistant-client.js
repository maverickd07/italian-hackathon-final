/* Session-protected UI adapter; no browser token or official API calls. */
(function(root) {
  'use strict';
  function offsetNow(date = new Date()) {
    const pad = number => String(number).padStart(2, '0');
    const offset = -date.getTimezoneOffset();
    return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${offset < 0 ? '-' : '+'}${pad(Math.floor(Math.abs(offset)/60))}:${pad(Math.abs(offset)%60)}`;
  }
  async function request({csrf, user, history, now = offsetNow(), transport = fetch, signal}) {
    if (!csrf) throw new Error('SESSION_EXPIRED');
    if (!user) throw new Error('USER_REQUIRED');
    const response = await transport('/ui-api/assistant', {
      method: 'POST', signal, credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify({context: {now, user}, messages: history})
    });
    if (!response.ok) throw new Error(response.status === 401 ? 'SESSION_EXPIRED' : 'ASSISTANT_OFFLINE');
    const body = await response.json();
    if (typeof body.reply !== 'string' || !body.reply.trim()) throw new Error('ASSISTANT_OFFLINE');
    if (/non è ancora abilitato/i.test(body.reply)) throw new Error('ASSISTANT_DISABLED');
    if (/servizio temporaneamente non disponibile|Tempo disponibile esaurito/i.test(body.reply)) throw new Error('ASSISTANT_OFFLINE');
    return body.reply;
  }
  root.RelayChatClient = {request, offsetNow};
})(typeof window === 'undefined' ? globalThis : window);
