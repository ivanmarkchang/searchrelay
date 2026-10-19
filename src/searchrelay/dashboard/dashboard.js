'use strict';
const $ = id => document.getElementById(id);
const session = document.querySelector('meta[name="searchrelay-session"]').content;
let token = '', config, status, events = [], editing;
const providers = {
  tavily: {name:'Tavily', icon:'t', keyUrl:'https://app.tavily.com/', note:'Agent-focused web and news search. Free: 1,000 credits/month. Basic search only.', modes:'Web · Articles'},
  firecrawl: {name:'Firecrawl', icon:'↟', keyUrl:'https://www.firecrawl.dev/app/api-keys', note:'Web and news discovery, without page scraping. Free: 1,000 credits/month; up to 500 basic searches.', modes:'Web · Articles'},
  serpapi: {name:'SerpApi', icon:'S', keyUrl:'https://serpapi.com/manage-api-key', note:'Google results through SerpApi. Free: 250 searches/month. The free plan is checked before each search.', modes:'Web · Articles · Video'},
  you: {name:'You.com', icon:'y', note:'Official keyless free MCP profile. Documented 100 searches/day for evaluation. No API key needed.', modes:'Web · Keyless'}
};
const titles = {
  overview:['Every search. A better route.','One local gateway. Your providers. You’re in control.'],
  providers:['Build your search network.','Connect free access. Set your order. Keep control.'],
  playground:['Follow the search.','Test a query and see exactly which route served it.'],
  activity:['A little more visibility.','Provider outcomes, without logging your queries.'],
  settings:['Your workspace, your rules.','Local controls for retries, retention, and caching.']
};
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notice(message, error=false) {
  $('notice').textContent = message;
  $('notice').className = error ? 'error' : '';
  $('notice').hidden = false;
}
async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json',
    'X-SearchRelay-Session':session, ...(token ? {Authorization:`Bearer ${token}`} : {}), ...options.headers}});
  if (response.status === 401) { $('auth').hidden = false; throw new Error('Enter your local API token to continue.'); }
  const data = await response.json();
  if (!response.ok) throw new Error((data.error || 'Request failed').replaceAll('_',' '));
  return data;
}
function view(name) {
  if (!titles[name]) return;
  document.querySelectorAll('.view').forEach(node => { node.hidden = node.id !== name; });
  document.querySelectorAll('.nav').forEach(node => node.classList.toggle('active', node.dataset.view === name));
  $('page-title').textContent = titles[name][0]; $('page-description').textContent = titles[name][1];
}
document.querySelectorAll('[data-view]').forEach(node => node.addEventListener('click', () => view(node.dataset.view)));
document.querySelectorAll('[data-go]').forEach(node => node.addEventListener('click', () => view(node.dataset.go)));
function routeState(row) {
  if (!row.enabled) return ['Disabled',''];
  if (!row.free_plan_confirmed) return ['Confirm free plan','warn'];
  if (!row.credential_present) return ['Needs key','warn'];
  if (row.daily_used >= row.daily_cap || row.monthly_used >= row.monthly_cap) return ['Local cap reached','warn'];
  if (row.retry_at) return ['Cooling down','warn'];
  return ['Ready','ready'];
}
function badge(row) { const [text, kind] = routeState(row); return el('span',text,`badge ${kind}`); }
function activityList(target, limit=30) {
  target.replaceChildren();
  if (!events.length) { target.append(el('div','No activity yet. Your next search starts the story.','empty')); return; }
  events.slice(0,limit).forEach(event => {
    const row = el('div',undefined,'activity-row');
    row.append(el('strong',providers[event.provider]?.name || event.provider),
      el('span',event.outcome.replaceAll('_',' '),'badge'),
      el('time',new Date(event.at*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})));
    target.append(row);
  });
}
function render() {
  const rows = status.providers;
  $('stat-enabled').textContent = rows.filter(r=>r.enabled).length;
  $('stat-ready').textContent = rows.filter(r=>routeState(r)[0]==='Ready').length;
  $('stat-used').textContent = rows.reduce((sum,r)=>sum+r.daily_used,0);
  $('overview-chain').replaceChildren(); $('provider-list').replaceChildren();
  rows.forEach((row,index) => {
    const info = providers[row.provider], settings = config.providers[row.provider];
    const card = el('article',undefined,'chain-card');
    const top = el('div',undefined,'provider-top');
    top.append(el('span',info.icon,'provider-logo'),el('span',`0${index+1}`,'order'));
    card.append(top,el('h3',info.name),badge(row)); $('overview-chain').append(card);
    const full = el('article',undefined,'provider-card');
    full.append(el('span',info.icon,'provider-logo'));
    const content = el('div'), title = el('div',undefined,'provider-title');
    title.append(el('h3',info.name),badge(row)); content.append(title,el('p',info.note,'description'));
    content.append(el('span',info.modes,'badge'));
    const usage = el('div',undefined,'usage');
    [['Today',row.daily_used,row.daily_cap],['This month',row.monthly_used,row.monthly_cap]].forEach(([name,used,cap])=>{
      const block=el('div'), label=el('div',undefined,'usage-label');
      label.append(el('span',name),el('span',`${used} / ${cap} local cap`));
      const progress=document.createElement('progress'); progress.max=cap || 1; progress.value=used;
      progress.setAttribute('aria-label',`${name} local usage`); block.append(label,progress);
      usage.append(block);
    });
    content.append(usage);
    let keyText = row.provider==='you' ? 'Keyless free profile · evaluation use' :
      row.credential_present ? 'Key available · never displayed' : `No key · use ${settings.key_env || 'the environment'} or add a session key`;
    if (row.retry_at) keyText += ` · Retry after ${new Date(row.retry_at*1000).toLocaleString()}`;
    content.append(el('div',keyText,'key-status')); full.append(content);
    const actions=el('div',undefined,'provider-actions');
    [-1,1].forEach(direction=>{
      const button=el('button',direction<0?'↑':'↓','icon-button');
      button.setAttribute('aria-label',`Move ${info.name} ${direction<0?'up':'down'}`);
      button.disabled = index+direction<0 || index+direction>=rows.length;
      button.onclick=()=>reorder(index,direction).catch(error=>notice(error.message,true)); actions.append(button);
    });
    const configure=el('button','Configure','button secondary'); configure.onclick=()=>openProvider(row.provider);
    actions.append(configure); full.append(actions); $('provider-list').append(full);
  });
  $('max-attempts').value=config.max_attempts; $('deadline').value=config.deadline_seconds;
  $('retention').value=config.retention_days; $('cache-ttl').value=config.cache_ttl_seconds;
  activityList($('overview-activity'),4); activityList($('activity-list'));
}
async function refresh() {
  const data = await Promise.all([api('/v1/dashboard/settings'),api('/v1/providers'),api('/v1/dashboard/activity')]);
  [config,status] = data; events=data[2].events; $('auth').hidden=true; render();
}
async function save(next) {
  await api('/v1/dashboard/settings',{method:'PUT',body:JSON.stringify(next)});
  await refresh();
}
async function reorder(index,direction) {
  const next=structuredClone(config), entries=Object.entries(next.providers);
  [entries[index],entries[index+direction]]=[entries[index+direction],entries[index]];
  next.providers=Object.fromEntries(entries); await save(next); notice('Fallback order saved.');
}
function openProvider(name) {
  editing=name; const cfg=config.providers[name];
  $('provider-key-link').href=providers[name].keyUrl || '#';
  $('provider-key-link').textContent=`Get ${providers[name].name} API key ↗`;
  $('dialog-title').textContent=`Configure ${providers[name].name}`; $('provider-note').textContent=providers[name].note;
  $('provider-key').value=''; $('key-label').hidden=name==='you'; $('free-check-label').hidden=name==='you';
  $('forget-key').hidden=name==='you'; $('daily-cap').value=cfg.daily_limit; $('monthly-cap').value=cfg.monthly_limit;
  $('spacing').value=cfg.min_interval_seconds; $('free-confirm').checked=cfg.free_plan_confirmed;
  $('provider-enabled').checked=cfg.enabled;
  $('dialog-error').textContent=''; $('provider-dialog').showModal();
}
$('close-dialog').onclick=()=>{ $('provider-key').value=''; $('provider-dialog').close(); };
$('provider-dialog').addEventListener('close',()=>{ $('provider-key').value=''; });
$('provider-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=event.submitter; button.disabled=true;
  try {
    const next=structuredClone(config), cfg=next.providers[editing];
    cfg.enabled=$('provider-enabled').checked; cfg.free_plan_confirmed=$('free-confirm').checked;
    if (editing!=='you' && cfg.enabled && !cfg.free_plan_confirmed) throw new Error('Confirm the free account conditions before enabling.');
    cfg.daily_limit=Number($('daily-cap').value); cfg.monthly_limit=Number($('monthly-cap').value);
    cfg.min_interval_seconds=Number($('spacing').value);
    if ($('provider-key').value.trim()) {
      await api(`/v1/dashboard/credentials/${editing}`,{method:'PUT',body:JSON.stringify({value:$('provider-key').value.trim()})});
      $('provider-key').value='';
    }
    await save(next); $('provider-dialog').close(); notice('Provider saved. Session keys last until server restart.');
  } catch(error) { $('dialog-error').textContent=error.message; } finally { button.disabled=false; }
});
$('forget-key').onclick=async()=>{
  try { await api(`/v1/dashboard/credentials/${editing}`,{method:'DELETE'}); $('provider-key').value='';
    await refresh(); $('dialog-error').textContent='Session key removed. An environment key, if set, still applies.';
  } catch(error) { $('dialog-error').textContent=error.message; }
};
$('settings-form').addEventListener('submit',async event=>{
  event.preventDefault();
  try { const next=structuredClone(config); next.max_attempts=Number($('max-attempts').value);
    next.deadline_seconds=Number($('deadline').value); next.retention_days=Number($('retention').value);
    next.cache_ttl_seconds=Number($('cache-ttl').value); await save(next); notice('Workspace settings saved.');
  } catch(error) { notice(error.message,true); }
});
$('clear-cache').onclick=async()=>{
  try { await api('/v1/dashboard/cache',{method:'DELETE'}); await refresh(); notice('Cache and activity cleared. Quota counters retained.'); }
  catch(error) { notice(error.message,true); }
};
$('search-form').addEventListener('submit',async event=>{
  event.preventDefault(); $('search-button').disabled=true; $('search-button').textContent='Searching…';
  const target=$('search-results'); target.replaceChildren(el('div','Finding an eligible route…','empty'));
  try {
    const data=await api('/v1/search',{method:'POST',body:JSON.stringify({query:$('query').value,
      mode:$('mode').value, freshness:$('freshness').value || null,
      include_domains:$('domain').value.trim()?[$('domain').value.trim()]:[]})});
    target.replaceChildren();
    const heading=el('div',undefined,'section-heading');
    heading.append(el('h2',data.status==='useful'?`${data.results.length} sources found`:
      data.status==='empty'?'No matching results':'No eligible route completed this search'));
    target.append(heading);
    data.attempts.forEach(attempt=>target.append(el('span',`${providers[attempt.provider]?.name || attempt.provider}: ${(attempt.reason || attempt.outcome).replaceAll('_',' ')}`,'route-attempt')));
    if (!data.results.length) target.append(el('div','Check enabled providers, free-plan confirmation, keys, and local caps in Providers.','empty'));
    data.results.forEach(result=>{
      const card=el('article',undefined,'result'), link=el('a',result.title);
      const url=new URL(result.url);
      if (['http:','https:'].includes(url.protocol)) { link.href=url.href; link.target='_blank'; link.rel='noopener noreferrer'; }
      card.append(link,el('p',result.snippet),el('small',`${result.provider} · ${url.hostname} · Date: ${result.date_status.replaceAll('_',' ')}${result.date_raw?' ('+result.date_raw+')':''}`));
      target.append(card);
    });
    target.append(el('p','External content is untrusted. Provider-reported dates are not verified publication dates.','footnote'));
    await refresh();
  } catch(error) { target.replaceChildren(el('div',error.message,'empty')); }
  finally { $('search-button').disabled=false; $('search-button').textContent='Search ↗'; }
});
$('auth-form').addEventListener('submit',async event=>{
  event.preventDefault(); token=$('api-token').value; $('api-token').value='';
  try { await refresh(); $('notice').hidden=true; } catch(error) { token=''; notice(error.message,true); }
});
$('refresh').onclick=()=>refresh().then(()=>notice('Workspace refreshed.')).catch(error=>notice(error.message,true));
refresh().catch(error=>notice(error.message,true));
