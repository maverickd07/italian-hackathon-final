/* Execute against the actual frontend scripts with a fake DOM/transport; no network. */
async function runRelayPetStress(sources) {
  let assertions = 0, cycles = 0;
  const check = (condition, message) => { assertions++; if (!condition) throw new Error(message); };
  class Node {
    constructor() { this.handlers = {}; this.hidden = false; this.disabled = false; this.value = ''; this.children = []; this.files = []; }
    addEventListener(name, fn) { this.handlers[name] = fn; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    setAttribute(name, value) { this[name] = value; }
    focus() { this.focused = true; }
  }
  const storage = new Map();
  function boot(options = {}) {
    const state = {calls: [], animations: [], expired: 0, timers: [], prevented: 0};
    const names = ['.chat-input','.chat-form','.chat-send','.chat-file','.chat-reset','.chat-status','.chat-confirm','.chat-attachment','.chat-messages'];
    const nodes = Object.fromEntries(names.map(name => [name, new Node()]));
    const confirms = [new Node(),new Node()]; confirms[0].dataset={confirm:'Sì, procedi'}; confirms[1].dataset={confirm:'No'};
    const suggestions = [new Node()]; suggestions[0].dataset={suggestion:'Quali sono i miei clienti dormienti?'};
    const surface = {querySelector:name=>nodes[name], querySelectorAll:name=>name==='[data-confirm]'?confirms:suggestions};
    nodes['.chat-form'].requestSubmit = () => nodes['.chat-form'].onsubmit({preventDefault(){state.prevented++;}});
    const wrap = new Node(), companion = new Node(), close = new Node(), drawer = new Node(); drawer.hidden=true;
    drawer.querySelector = name => nodes[name]; companion.closest=()=>wrap;
    const box = options.page ? {left:400,top:200,width:78,height:86} : {left:900,top:700,width:78,height:89};
    const pet = new Node();
    for (const node of [pet,companion]) {
      node.getBoundingClientRect=()=>box;
      if (!options.noAnimate) node.animate=(frames,timing)=>{
        if (options.animationThrows) throw Error('animation unavailable');
        state.animations.push({frames,timing}); return {};
      };
    }
    const document = {
      handlers:{}, addEventListener(name,fn){this.handlers[name]=fn;}, createElement:()=>new Node(),
      querySelectorAll:name=>name==='[data-chat-surface]'?[surface]:name==='.chat-close'&&!options.page?[close]:[],
      querySelector:name=>name==='#assistant-drawer'?(!options.page?drawer:null):name==='#companion-toggle'?(!options.page?companion:null):name==='.chat-pet-arrival'?(options.page?pet:null):null
    };
    const window = {RelayCRM:{config:{user:options.noUser?'':'fake@example.it',csrf:'fake-csrf',record:'Synthetic company'},expire:()=>{state.expired++;}},
      innerWidth:1000,innerHeight:800,location:{href:'http://local.test'+(options.path||'/'),origin:'http://local.test',pathname:options.path||'/'},
      handlers:{},addEventListener(name,fn){this.handlers[name]=fn;},
      matchMedia: options.noMatchMedia ? undefined : ()=>{if(options.mediaThrows)throw Error('media unavailable');return {matches:!!options.reduced};}
    };
    const sessionStorage = {
      getItem:key=>{if(options.storageReadThrows)throw Error('storage blocked');return storage.get(key)||null;},
      setItem:(key,value)=>{if(options.storageWriteThrows)throw Error('quota exceeded');storage.set(key,value);},
      removeItem:key=>{if(options.storageWriteThrows)throw Error('storage blocked');storage.delete(key);}
    };
    class Controller {constructor(){this.signal={aborted:false, handlers:[],addEventListener:(_,fn)=>this.signal.handlers.push(fn)};}abort(){this.signal.aborted=true;this.signal.handlers.forEach(fn=>fn());}}
    window.RelayChatClient={request: async payload => {
      state.calls.push(JSON.parse(JSON.stringify({user:payload.user,history:payload.history,csrf:payload.csrf})));
      if(options.error)throw Error(options.error);
      if(options.deferred)await new Promise((resolve,reject)=>{state.resolve=resolve;payload.signal.addEventListener('abort',()=>reject(Error('aborted')));});
      return options.reply||'Risposta di prova. Nessuna modifica eseguita.';
    }};
    new Function('window','document','sessionStorage','URL','setTimeout','clearTimeout','AbortController','TextDecoder',sources['assistant.js'])(window,document,sessionStorage,URL,fn=>{state.timers.push(fn);return fn;},()=>{},Controller,TextDecoder);
    state.nodes=nodes;state.window=window;state.document=document;state.wrap=wrap;state.drawer=drawer;state.companion=companion;state.close=close;state.confirms=confirms;
    state.key = props => nodes['.chat-input'].handlers.keydown({key:'Enter',preventDefault(){state.prevented++;},...props});
    return state;
  }
  const flush=async()=>{for(let i=0;i<6;i++)await Promise.resolve();};
  const navigate=(state,path,extra={})=>state.document.handlers.click({button:0,target:{closest:()=>({href:'http://local.test'+path,target:'',hasAttribute:()=>false})},...extra});
  // Rapid page transitions and drawer cycles must never cause a request.
  for(let i=0;i<500;i++){
    storage.clear();const page=boot({page:true,path:'/assistant'});check(page.animations.length===1,'arrival absent');
    navigate(page,'/companies');const next=boot({path:'/companies'});check(next.animations.length===1,'return absent');
    check(!storage.has('relay-crm-pet-return'),'return marker reused');
    for(let j=0;j<10;j++){
      next.companion.onclick();check(!next.drawer.hidden&&next.wrap.hidden,'two visible chat entry points');
      next.close.onclick();check(next.drawer.hidden&&!next.wrap.hidden,'pet not restored');cycles++;
    }
    check(page.calls.length+next.calls.length===0,'navigation triggered assistant');
  }
  for(const options of [{reduced:true},{noAnimate:true},{animationThrows:true},{storageReadThrows:true},{storageWriteThrows:true},{noMatchMedia:true},{mediaThrows:true}]){
    storage.clear();const state=boot({page:true,path:'/assistant',...options});
    state.nodes['.chat-input'].value='Synthetic question';state.key({});await flush();
    check(state.calls.length===1,'decorative failure broke chat');check(!state.nodes['.chat-send'].disabled,'chat stuck busy');
  }
  for(const marker of ['{','null','{}',JSON.stringify({path:'/companies',at:Date.now()-20000,x:.5,y:.5}),JSON.stringify({path:'/other',at:Date.now(),x:.5,y:.5})]){
    storage.clear();storage.set('relay-crm-pet-return',marker);const state=boot({path:'/companies'});
    check(state.animations.length===0,'invalid marker animated');check(state.calls.length===0,'invalid marker triggered request');
  }
  for(const modifier of [{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{button:1},{defaultPrevented:true}]){
    storage.clear();const state=boot({page:true,path:'/assistant'});navigate(state,'/contacts',modifier);
    check(!storage.has('relay-crm-pet-return'),'new-tab or cancelled navigation left marker');
  }
  storage.clear();let state=boot({deferred:true});state.companion.onclick();state.nodes['.chat-input'].value='One request';state.key({});
  for(let i=0;i<300;i++){state.key({});state.key({repeat:true});state.close.onclick();state.companion.onclick();}
  check(state.calls.length===1,'rapid keys or drawer changes duplicated request');check(state.nodes['.chat-send'].disabled,'busy button enabled');
  state.resolve();await flush();check(!state.nodes['.chat-send'].disabled,'busy never cleared');
  state.nodes['.chat-input'].value='New line';state.key({shiftKey:true});state.key({isComposing:true});state.key({keyCode:229});
  state.nodes['.chat-input'].handlers.compositionstart();state.key({});state.nodes['.chat-input'].handlers.compositionend();
  check(state.calls.length===1,'IME or Shift+Enter sent');state.key({});await flush();check(state.calls.length===2,'IME did not recover');
  storage.clear();state=boot({deferred:true});state.nodes['.chat-input'].value='Timeout';state.key({});state.timers[0]();await flush();
  check(!state.nodes['.chat-send'].disabled&&state.nodes['.chat-status'].textContent.includes('offline'),'timeout stuck chat');
  for(const error of ['SESSION_EXPIRED','ASSISTANT_DISABLED','ASSISTANT_OFFLINE']){
    storage.clear();state=boot({error});state.nodes['.chat-input'].value='Test';state.key({});await flush();
    check(state.calls.length===1&&!state.nodes['.chat-send'].disabled,'failure repeated or froze');
    check(error!=='SESSION_EXPIRED'||state.expired===1,'expired session not handled');
  }
  storage.clear();state=boot({noUser:true});state.nodes['.chat-input'].value='No identity';state.key({});await flush();check(state.calls.length===0,'request without identity');
  for(const history of ['{','null','{}','[{"role":"user","content":"x","attachments":"invalid"}]','[{"role":"user","content":"x","attachments":[null]}]']){
    storage.clear();storage.set('relay-crm-chat:fake@example.it',history);state=boot();state.nodes['.chat-input'].value='Recover';state.key({});await flush();check(state.calls.length===1,'corrupt history broke chat');
  }
  storage.clear();state=boot({reply:'Confermi?'});state.nodes['.chat-input'].value='Test';state.key({});await flush();
  check(!state.nodes['.chat-confirm'].hidden,'confirmation absent');state.confirms[1].onclick();await flush();check(state.calls[1].history.at(-1).content==='No','confirmation payload lost');
  const root={};new Function('window',sources['assistant-client.js'])(root);let transports=0;
  const history=[{role:'user',content:'CSV',attachments:[{name:'test.csv',content_type:'text/csv',content:'sku;name\nX;Synthetic'}]},{role:'assistant',content:'Confermi?'},{role:'user',content:'No'}];
  await root.RelayChatClient.request({csrf:'fake-csrf',user:'fake@example.it',history,now:'2026-12-02T10:00:00+01:00',transport:async(path,options)=>{
    transports++;check(path==='/ui-api/assistant','wrong endpoint');check(!options.headers.Authorization,'browser bearer leaked');check(JSON.stringify(JSON.parse(options.body).messages)===JSON.stringify(history),'full history or CSV changed');return {ok:true,json:async()=>({reply:'Va bene.'})};
  }});
  check(transports===1,'transport duplicated');
  return {assertions, page_transitions:500, drawer_cycles:cycles, rapid_keys:600, paid_model_calls:0, result:'passed'};
}

// Optional standalone runner; no browser, network, credentials or npm build required.
if (typeof module !== 'undefined') {
  module.exports = runRelayPetStress;
  if (require.main === module) {
    const fs = require('node:fs'), path = require('node:path');
    const sources = Object.fromEntries(['assistant.js','assistant-client.js'].map(name => [name,fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8')]));
    runRelayPetStress(sources).then(result => console.log(JSON.stringify(result,null,2))).catch(error => { console.error(error.message); process.exitCode=1; });
  }
}
