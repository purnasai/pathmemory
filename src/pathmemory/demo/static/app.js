const $ = s => document.querySelector(s);
const api = p => fetch(p).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail)));
let G, cy, EXPS = [], runSeq = 0;

function short(k) { return k.length > 34 ? k.slice(0, 33) + '…' : k; }

const MEM = () => $('#mem').value;
async function loadGraph() {
  G = await api('/api/graph?memory=' + MEM());
  if (cy) cy.destroy();
  $('#chips').innerHTML = `<span class="chip">graph <b>${G.graph}</b> · ${G.fingerprint}</span><span class="chip"><b>${G.stats.states}</b> pages</span><span class="chip"><b>${G.stats.edges}</b> verified steps</span><span class="chip"><b>${G.stats.tasks}</b> tasks learned</span>`;
  const maxS = Math.max(1, ...G.edges.map(e => e.successes));
  const els = [
    ...G.nodes.map(n => ({ data: { id: n.key, label: short(n.key), work: n.goals.length ? 1 : 0, title: n.title } })),
    ...G.edges.map(e => ({ data: { id: e.eid, source: e.src, target: e.dst, label: e.name, w: 1.5 + 3 * e.successes / maxS, fails: e.failures } })),
  ];
  cy = cytoscape({
    container: $('#cy'), elements: els, wheelSensitivity: 0.2,
    layout: { name: 'breadthfirst', directed: true, roots: ['/'], spacingFactor: 1.15, padding: 30 },
    style: [
      { selector: 'node', style: { 'background-color': '#2a333f', 'border-width': 1, 'border-color': '#56606e', label: 'data(label)', color: '#e6edf3', 'font-size': 10, 'text-valign': 'bottom', 'text-margin-y': 5, width: 18, height: 18, 'text-background-color': '#0f1216', 'text-background-opacity': .8, 'text-background-padding': 2 } },
      { selector: 'node[work = 1]', style: { shape: 'round-rectangle', 'background-color': '#33404f' } },
      { selector: 'edge', style: { width: 'data(w)', 'line-color': '#56606e', 'target-arrow-color': '#56606e', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', label: 'data(label)', 'font-size': 9, color: '#8b98a8', 'text-rotation': 'autorotate', 'text-background-color': '#0f1216', 'text-background-opacity': .85, 'text-background-padding': 1 } },
      { selector: '.used', style: { 'line-color': '#2fbf71', 'target-arrow-color': '#2fbf71', color: '#a9f0c6', 'z-index': 9 } },
      { selector: '.learned', style: { 'line-color': '#f2b84b', 'target-arrow-color': '#f2b84b', color: '#f7d58f', width: 4, 'z-index': 11 } },
      { selector: 'node.learned', style: { 'border-color': '#f2b84b', 'border-width': 3 } },
      { selector: '.failed', style: { 'line-color': '#ff5c5c', 'target-arrow-color': '#ff5c5c', 'line-style': 'dashed', color: '#ffb3b3', 'z-index': 10 } },
      { selector: 'node.visited', style: { 'background-color': '#1f5134', 'border-color': '#2fbf71' } },
      { selector: 'node.cur', style: { 'border-color': '#4f8cff', 'border-width': 4, width: 24, height: 24 } },
      { selector: '.dim', style: { opacity: .3 } },
      { selector: 'edge.flat', style: { 'curve-style': 'unbundled-bezier', 'control-point-distances': [-55], 'control-point-weights': [0.5] } },
    ],
  });
  // edges between nodes on the same row would run straight through the nodes in between: bend them
  cy.edges().forEach(e => { if (Math.abs(e.source().position('y') - e.target().position('y')) < 5) e.addClass('flat'); });
  cy.on('tap', 'edge', e => showEdge(G.edges.find(x => x.eid === e.target.id())));
  cy.on('tap', e => { if (e.target === cy) $('#edgeinfo').style.display = 'none'; });
  cy.on('tap', 'node', e => { $('#qsrc').value = '/'; $('#qdst').value = e.target.id(); showTab('query'); runQuery(); });
  const opts = G.nodes.map(n => `<option>${n.key}</option>`).join('');
  $('#qsrc').innerHTML = opts; $('#qdst').innerHTML = opts;
  $('#qsrc').value = '/'; $('#qdst').value = G.nodes.find(n => n.key.endsWith('collaboration'))?.key || G.nodes[0].key;
  $('#avoid').innerHTML = G.edges.map(e => `<label><input type="checkbox" value="${e.eid}"> <span class="muted">${e.src}</span> → <b>${e.name}</b> → <span class="muted">${e.dst}</span> <span class="muted">(${e.successes}✓ ${e.failures}✗)</span></label>`).join('');
}

const EP = id => (id || '').split('_on_pathmemory.')[1]?.replace(/_0$/, '') || id;  // run dir -> task id
const srcBadges = (srcs, essential) => (srcs || []).map(x => `<span class="src ${srcs.length === 1 && essential ? 'ess' : ''}" title="${esc(x)}">${esc(EP(x))}</span>`).join('');
function showEdge(e) {
  if (!e) return;
  $('#edgeinfo').style.display = 'block';
  $('#edgeinfo').innerHTML = `<b>${esc(e.role)} '${esc(e.name)}'</b> <span class="muted">[${esc(e.scope || '')}]</span><br>
    <span class="muted">${esc(e.src)} → ${esc(e.dst)}</span><br>${e.successes}✓ ${e.failures}✗ · eid ${e.eid}<br>
    learned from: ${e.sources.length ? srcBadges(e.sources) : '<span class="muted">no provenance recorded (v1 memory)</span>'}`;
}
function markRoute(keys, cls) {
  for (let i = 0; i + 1 < keys.length; i++)
    cy.edges().filter(e => e.source().id() === keys[i] && e.target().id() === keys[i + 1]).addClass(cls);
  keys.forEach(k => cy.getElementById(k).addClass('visited'));
}

function clearMarks() { cy.elements().removeClass('used failed visited cur dim learned'); }

function markRun(run, upto) {
  clearMarks();
  const steps = upto == null ? run.steps : run.steps.slice(0, upto + 1);
  steps.forEach(s => cy.getElementById(s.page).addClass('visited'));
  const ev = run.events || [];
  // the route actually followed = the last route event (after any recovery)
  const routes = ev.filter(e => e.event === 'route');
  const last = routes[routes.length - 1];
  if (last) for (let i = 0; i + 1 < last.keys.length; i++)
    cy.edges().filter(e => e.source().id() === last.keys[i] && e.target().id() === last.keys[i + 1]).addClass('used');
  ev.filter(e => e.event === 'edge_failed' && e.eid).forEach(e => cy.getElementById(e.eid).removeClass('used').addClass('failed'));
  if (upto != null && run.steps[upto]) cy.getElementById(run.steps[upto].page).addClass('cur');
}

async function loadExperiments() {
  EXPS = await api('/api/experiments');
  if (!EXPS.length) {
    $('#runview').textContent = 'No experiment summaries found. Run scripts/reproduce_v2.sh from the checkout.';
    $('#results').textContent = 'No experiment summaries found.';
    return;
  }
  $('#exp').innerHTML = EXPS.map((e, i) => `<option value="${i}">${e.title}</option>`).join('');
  $('#exp').onchange = fillTasks; $('#task').onchange = fillModes; $('#mode').onchange = openRun;
  // Start with the current composition case.
  const broken = EXPS.findIndex(e => e.file.includes('v2-broken/') || e.file.endsWith('/broken.jsonl'));
  $('#exp').value = String(Math.max(0, broken)); fillTasks();
  if ([...$('#mode').options].some(o => o.value === 'graph')) { $('#mode').value = 'graph'; }
  openRun();
  renderResults();
}

function fillTasks() {
  const e = EXPS[$('#exp').value];
  $('#task').innerHTML = Object.keys(e.tasks).map(t => `<option>${t}</option>`).join('');
  fillModes();
}
function fillModes() {
  const t = EXPS[$('#exp').value].tasks[$('#task').value];
  $('#mode').innerHTML = Object.entries(t).map(([m, r]) => `<option value="${m}">${m} ${r.success ? '✓' : '✗'}${r.available ? '' : ' (summary only)'}</option>`).join('');
  openRun();
}

async function openRun(dir) {
  const seq = ++runSeq;
  if (typeof dir !== 'string') {
    const t = EXPS[$('#exp').value]?.tasks[$('#task').value];
    const r = t && t[$('#mode').value];
    if (!r) return;
    if (!r.available) {
      $('#runview').textContent = 'This checkout has the result summary. Screenshots and step traces are available after a local run.';
      return;
    }
    dir = r.exp_dir;
  }
  const run = await api('/api/run?dir=' + encodeURIComponent(dir));
  if (seq !== runSeq) return;  // a newer selection was made while this one loaded
  // show the run on the memory it actually used
  const want = run.dir.startsWith('v2-ablation') ? 'v2-ablated' : run.dir.startsWith('v2') ? 'v2' : 'v1';
  if (MEM() !== want) { $('#mem').value = want; await loadGraph(); }
  const ev = run.events || [];
  const evHtml = ev.filter(e => e.event !== 'replay').map(e => {
    if (e.event === 'choose') return `<span class="ev">target page: <b>${e.target || 'none'}</b></span>`;
    if (e.event === 'route') return `<span class="ev">route: ${e.keys.join(' → ')}</span>`;
    if (e.event === 'edge_failed') return `<span class="ev fail">step failed: ${e.why}</span>`;
    if (e.event === 'recovered') return `<span class="ev rec">rerouted via ${e.via.join(' → ')}</span>`;
    if (e.event === 'no_route') return `<span class="ev fail">no route from ${e.from}</span>`;
    if (e.event === 'retry') return `<span class="ev">retried '${esc(e.target)}' (page was still moving)</span>`;
    if (e.event === 'verified') return `<span class="ev ver">✓ verified ${e.page} ${Object.entries(e.entities || {}).map(([k, v]) => k + '=' + esc(v)).join(' ')}</span>`;
    return `<span class="ev">${e.event}</span>`;
  }).join('');
  const nGraph = run.steps.filter(s => s.source === 'graph').length;
  $('#runview').innerHTML = `
    <div class="goal"><span class="rec">RECORDED</span><span class="muted" style="font-size:12px">${esc(run.dir)}</span><br>${run.goal.replace(/When you are done.*$/, '')}
      <div class="meta"><span class="${run.success ? 'ok' : 'bad'}">${run.success ? 'success' : 'failed'}</span> ·
      ${run.steps.length} steps · <span style="color:var(--graph)">${nGraph} replayed from memory (no LLM call)</span> ·
      ${run.tokens.toLocaleString()} input tokens</div></div>
    <div class="events">${evHtml}</div>
    <div class="steps">${run.steps.map((s, i) => `
      <div class="step" data-i="${i}">
        <div class="n">#${s.n}</div>
        <div class="badge ${s.source}">${s.source === 'graph' ? 'REPLAY' : 'LLM'}</div>
        <div><div class="page">${s.page}</div><div class="act">${esc(s.action)}</div>
          ${s.think && s.source !== 'graph' ? `<div class="think">${esc(s.think.slice(0, 220))}</div>` : ''}
          ${s.error ? `<div class="err">${esc(s.error.slice(0, 160))}</div>` : ''}</div>
      </div>`).join('')}</div>
    <div class="shot" id="shot"></div>`;
  const pick = i => {
    document.querySelectorAll('.step').forEach(x => x.classList.toggle('sel', +x.dataset.i === i));
    const s = run.steps[i];
    $('#shot').innerHTML = s.screenshot ? `<img alt="screenshot before step ${s.n}" src="/api/screenshot?dir=${encodeURIComponent(run.dir)}&n=${s.n}">` : '';
    markRun(run, i);
  };
  document.querySelectorAll('.step').forEach(x => x.onclick = () => pick(+x.dataset.i));
  markRun(run, null);
  if (run.steps.length) pick(0);
}

function esc(s) { return s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]); }

function renderResults() {
  const sections = EXPS.map((e, ei) => {
    const s = e.summary;
    const current = e.selection === 'all';
    const head = current
      ? '<tr><th>mode</th><th>checker passed</th><th>replay reached page</th><th>model calls</th><th>input tokens</th><th>browser actions</th><th>est. USD</th></tr>'
      : '<tr><th>mode</th><th>checker passed</th><th>avg steps</th><th>LLM-chosen steps</th><th>replayed</th><th>input tokens</th><th>seconds</th></tr>';
    const rows = Object.entries(s).map(([m, v]) => current
      ? `<tr><td>${m}</td><td>${v.success}/${v.tasks}</td><td>${v.replay_reached_goal}/${v.tasks}</td><td>${v.model_calls}</td><td>${v.input_tokens.toLocaleString()}</td><td>${v.steps}</td><td>${v.est_cost_usd.toFixed(4)}</td></tr>`
      : `<tr><td>${m}</td><td>${v.success}/${v.tasks}</td><td>${v.steps}</td><td>${v.llm_steps}</td><td>${v.replayed}</td><td>${v.input_tokens.toLocaleString()}</td><td>${v.seconds}</td></tr>`).join('');
    const modes = Object.keys(s);
    const per = Object.entries(e.tasks).map(([t, r]) => `<tr><td>${t}</td>${modes.map(m => r[m] ? `<td class="cell" data-e="${ei}" data-t="${t}" data-m="${m}"><span class="${r[m].success ? 'ok' : 'bad'}">${r[m].success ? '✓' : '✗'}</span> ${r[m].steps} st · ${(r[m].input_tokens / 1000).toFixed(1)}k</td>` : '<td>–</td>').join('')}</tr>`).join('');
    const rep = current ? `<p class="muted">All ${e.observations} trials included. Values are means; checker and replay counts include every trial. Source: ${esc(e.file)}.</p>` : e.repeated.length ? `<p class="muted">${e.observations} runs; ${e.repeated.length} task/mode pairs were run more than once (${e.repeated.map(d => d.task + '/' + d.mode).join(', ')}). Showing the ${e.selection} attempt; <code>python -m pathmemory.report --select both</code> shows all.</p>` : '';
    return `<h3>${e.title}</h3>${rep}<table>${head}${rows}</table>
      <table><tr><th>task</th>${modes.map(m => `<th>${m}</th>`).join('')}</tr>${per}</table>`;
  });
  const current = sections.filter((_, i) => EXPS[i].selection === 'all').join('');
  const historical = sections.filter((_, i) => EXPS[i].selection !== 'all').join('');
  $('#results').innerHTML = current + `<details><summary class="muted">Historical v1 experiments (see correction notes)</summary>${historical}</details>`
    + '<p class="muted">Same agent, model, prompts and 15-step budget in every mode; only the memory differs. Click a cell to inspect a trial. Screenshots require local run files.</p>';
  document.querySelectorAll('td.cell').forEach(td => td.onclick = () => {
    $('#exp').value = td.dataset.e; fillTasks(); $('#task').value = td.dataset.t; fillModes(); $('#mode').value = td.dataset.m; openRun(); showTab('run');
  });
}

async function runQuery() {
  const avoid = [...document.querySelectorAll('#avoid input:checked')].map(i => i.value);
  const qs = new URLSearchParams({ src: $('#qsrc').value, dst: $('#qdst').value });
  avoid.forEach(a => qs.append('avoid', a));
  try {
    qs.append('memory', MEM());
    const r = await api('/api/route?' + qs);
    $('#qcypher').textContent = r.cypher;
    clearMarks();
    avoid.forEach(a => cy.getElementById(a).addClass('failed'));
    if (!r.routes.length) { $('#qroutes').innerHTML = '<div class="r bad">No verified route.</div>'; return; }
    const draw = route => {
      cy.edges().removeClass('used');
      route.edges.forEach(e => cy.getElementById(e.eid).addClass('used'));
      route.keys.forEach(k => cy.getElementById(k).addClass('visited'));
    };
    $('#qroutes').innerHTML = r.routes.map((ro, i) => `<div class="r" data-i="${i}"><b>${ro.edges.length} clicks:</b> ${ro.edges.map(e => esc(e.name)).join(' → ') || '(already there)'}<div class="muted" style="font-size:12px">${ro.keys.join(' → ')}</div></div>`).join('');
    document.querySelectorAll('#qroutes .r').forEach(x => x.onclick = () => draw(r.routes[+x.dataset.i]));
    draw(r.routes[0]);
  } catch (e) { $('#qroutes').innerHTML = `<div class="r bad">${e}</div>`; }
}

// --- live run --------------------------------------------------------------------------------
let liveTimer = null;
async function initLive() {
  const tasks = await api('/api/tasks');
  $('#ltask').innerHTML = tasks.map(t => `<option value="${t.id}">${t.id} — ${esc(t.goal.slice(0, 60))}</option>`).join('');
  $('#ltask').value = 'issues-2';
  $('#lgo').onclick = startLive;
  $('#lmem').onchange = () => { $('#llearn').disabled = $('#lmem').value !== 'v1'; if ($('#llearn').disabled) $('#llearn').checked = false; };
  $('#lmem').onchange();
  $('#lreset').onclick = resetMemory;
  const cur = await api('/api/live');
  if (cur.status === 'running' || cur.status === 'starting') { $('#lgo').disabled = true; pollLive(); }
  else if (cur.status === 'done' || cur.status === 'error') renderLive(cur);  // page reloaded after a run
}
function startDemo(memory) {  // from the v2 tab: same live run, preset to the composition case
  $('#ltask').value = 'issues-2'; $('#lmode').value = 'graph'; $('#lbreak').checked = true; $('#lmem').value = memory; $('#lmem').onchange();
  if (MEM() !== memory) { $('#mem').value = memory; loadGraph(); }
  showTab('live'); startLive();
}
async function startLive() {
  $('#lgo').disabled = true;
  try {
    await fetch('/api/live', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: $('#ltask').value, mode: $('#lmode').value, break_ui: $('#lbreak').checked,
                             learn: $('#lmem').value === 'v1' && $('#llearn').checked, memory: $('#lmem').value }) })
      .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail)));
    $('#lview').innerHTML = ''; pollLive();
  } catch (e) { $('#lstatus').textContent = e; $('#lgo').disabled = false; }
}
function pollLive() {
  clearInterval(liveTimer);
  liveTimer = setInterval(async () => {
    const r = await api('/api/live');
    renderLive(r);
    if (r.status === 'done' || r.status === 'error' || r.status === 'idle') { clearInterval(liveTimer); $('#lgo').disabled = false; }
  }, 700);
}
// same rule as compare.replay_reached_goal: the last route was replayed to its end with no failed check after it
function replayReachedGoal(ev) {
  const idx = ev.map((e, i) => e.event === 'route' ? i : -1).filter(i => i >= 0);
  if (!idx.length) return false;
  const last = idx[idx.length - 1], after = ev.slice(last + 1);
  return !after.some(e => e.event === 'edge_failed' || e.event === 'no_route')
    && after.filter(e => e.event === 'replay').length >= ev[last].keys.length - 1;
}
function renderLive(r) {
  const nGraph = (r.steps || []).filter(s => s.source === 'graph').length;
  if (r.status === 'starting') $('#lstatus').innerHTML = `<span class="pulse"></span>${r.note || 'starting'}…`;
  else if (r.status === 'running') $('#lstatus').innerHTML = `<span class="pulse"></span>running · step ${r.steps.length} · ${nGraph} replayed from memory`;
  const started = (r.dir || '').match(/^live-(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)/);
  const when = started ? `run live at ${started[1]}-${started[2]}-${started[3]} ${started[4]}:${started[5]}:${started[6]} · ` : '';
  if (r.status === 'done') $('#lstatus').innerHTML = `<span class="live">LIVE</span>${when}<span class="${r.success ? 'ok' : 'bad'}">checker: ${r.success ? 'passed' : 'failed'}</span> ·
    ${replayReachedGoal(r.events || []) ? '<b class="ok">memory replay reached the goal page</b>' : '<b class="bad">memory replay did not reach the goal page</b>' + (r.success ? ' (LLM-fallback success)' : '')} · ${r.steps.length} steps · ${nGraph} replayed · ${r.model_calls ?? '?'} model calls · ${(r.tokens || 0).toLocaleString()} input tokens · ${r.seconds}s
    ${r.final_url ? `· ended on <code>${esc(r.final_url.replace(/^https?:\/\/[^/]+/, ''))}</code>` : ''}
    ${r.frozen ? `· memory ${esc(r.frozen.snapshot)} ${r.frozen.unchanged ? '<span class="ok">unchanged ✓</span>' : '<span class="bad">CHANGED</span>'} (${r.frozen.fingerprint_after})` : ''}
    · <a href="#" id="lreplay" style="color:var(--accent)">open with screenshots</a>`;
  else if (r.status === 'error') $('#lstatus').innerHTML = `<span class="bad">error</span> ${esc(r.note || '')}`;
  const ev = (r.events || []).filter(e => e.event !== 'replay').map(e => {
    if (e.event === 'choose') return `<span class="ev">target page: <b>${e.target || 'none'}</b></span>`;
    if (e.event === 'route') return `<span class="ev">route: ${e.keys.join(' → ')}</span>`;
    if (e.event === 'edge_failed') return `<span class="ev fail">step failed: ${esc(e.why)}</span>`;
    if (e.event === 'recovered') return `<span class="ev rec">rerouted via ${e.via.join(' → ')}</span>`;
    if (e.event === 'no_route') return `<span class="ev fail">no route from ${e.from}</span>`;
    if (e.event === 'retry') return `<span class="ev">retried '${esc(e.target)}' (page was still moving)</span>`;
    if (e.event === 'verified') return `<span class="ev ver">✓ verified ${e.page} ${Object.entries(e.entities || {}).map(([k, v]) => k + '=' + esc(v)).join(' ')}</span>`;
    return '';
  }).join('');
  $('#lview').innerHTML = `${memHtml(r.memory)}<div class="events">${ev}</div><div class="steps">${(r.steps || []).map(s => `
    <div class="step"><div class="n">#${s.n}</div><div class="badge ${s.source}">${s.source === 'graph' ? 'REPLAY' : 'LLM'}</div>
      <div><div class="page">${s.page}</div><div class="act">${esc(s.action)}</div>
      ${s.think && s.source !== 'graph' ? `<div class="think">${esc(s.think.slice(0, 220))}</div>` : ''}</div></div>`).join('')}</div>`;
  if (r.steps && r.steps.length) markRun(r, r.steps.length - 1); else if (r.events && r.events.length) markRun({ steps: [], events: r.events }, null);
  if (r.status === 'done' && r.memory && r.dir !== shownWrite) {  // memory changed: redraw the graph once and show the write
    shownWrite = r.dir;
    loadGraph().then(() => { markRun(r, null); showWrite(r.memory); });
  }
  const link = $('#lreplay');
  if (link) link.onclick = ev2 => { ev2.preventDefault(); showTab('run'); openRun(r.dir); };
}

let shownWrite = null;
function memHtml(m) {
  if (!m) return '';
  const step = e => `<li><span class="k">${esc(e.src)}</span> → <b>${esc(e.name)}</b> → <span class="k">${esc(e.dst)}</span>${e.by ? ` <span class="muted">(${e.successes ?? e.failures} total)</span>` : ''}</li>`;
  const list = (title, xs) => xs.length ? `<div>${title}</div><ul>${xs.map(step).join('')}</ul>` : '';
  const head = m.learned ? 'Written to FalkorDB from this run' : 'Run failed: nothing learned (only successful runs become memory)';
  return `<div class="mem"><h4>${head}</h4>
    ${list(`<b>${m.new_steps.length}</b> new verified step${m.new_steps.length === 1 ? '' : 's'}`, m.new_steps)}
    ${list(`<b>${m.reinforced.length}</b> known step${m.reinforced.length === 1 ? '' : 's'} confirmed again (success count +1)`, m.reinforced)}
    ${list(`<b>${m.failures.length}</b> step${m.failures.length === 1 ? '' : 's'} marked failed during the run`, m.failures)}
    ${m.new_pages.length ? `<div><b>${m.new_pages.length}</b> new page${m.new_pages.length === 1 ? '' : 's'}: <span class="k">${m.new_pages.map(esc).join(', ')}</span></div>` : ''}
    ${m.new_tasks.length ? `<div>new task worksite: <span class="k">${m.new_tasks.map(esc).join(', ')}</span></div>` : ''}
    <div class="muted" style="margin-top:6px">Memory now: ${m.stats.states} pages · ${m.stats.edges} verified steps · ${m.stats.tasks} tasks</div>
    <details><summary class="muted">Cypher used for each step</summary><pre>MATCH (a:State {key:$src}), (b:State {key:$dst})
MERGE (a)-[r:ACT {eid:$eid}]->(b)
ON CREATE SET r.kind=$kind, r.role=$role, r.name=$name, r.successes=0, r.failures=0
SET r.successes = r.successes + 1</pre></details></div>`;
}
function showWrite(m) {
  m.new_steps.concat(m.reinforced).forEach(e => cy.getElementById(e.eid).removeClass('used').addClass('learned'));
  m.new_pages.forEach(k => cy.getElementById(k).addClass('learned'));
}
async function resetMemory() {
  try {
    const s = await fetch('/api/memory/restore', { method: 'POST' }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(e.detail)));
    $('#lstatus').textContent = `memory reset to v1: ${s.states} pages · ${s.edges} steps · ${s.tasks} tasks`;
    shownWrite = null; await loadGraph();
  } catch (e) { $('#lstatus').textContent = e; }
}

async function renderV2() {
  const d = await api('/api/v2/demo');
  const normal = d.normal.routes[0], alternative = d.broken.routes[0];
  const recording = d.recorded.find(r => r.condition === 'broken' && r.mode === 'graph' && r.available);
  const route = r => `<div class="route-line">${r.edges.map(e => `<span>${esc(e.name)}</span>`).join('<i>→</i>')}</div>`;
  const hopRows = alternative.edges.map((edge, i) => `<tr><td>${i + 1}</td>
    <td>${esc(edge.name)}<small>${esc(alternative.keys[i])} → ${esc(alternative.keys[i + 1])}</small></td>
    <td>${srcBadges(edge.sources, true)}</td></tr>`).join('');
  const cont = Object.entries(d.containment).map(([ep, c]) => `<tr><td>${esc(EP(ep))}</td><td>${c.steps_of_route_present.length} / ${d.composed.eids.length}</td><td>${c.contiguous || c.all_steps_somewhere ? 'yes' : 'no'}</td></tr>`).join('');
  const rec = d.recorded.map(r => `<tr><td>${esc(r.condition)}</td><td>${esc(r.mode)}</td><td>${r.success ? 'passed' : 'failed'}</td>
    <td>${r.available ? `<a href="#" data-dir="${esc(r.dir)}" class="recl">Open run</a>` : '<span class="muted">summary only</span>'}</td></tr>`).join('');
  $('#v2view').innerHTML = `
    <div class="walk-intro"><span class="eyebrow">A browser agent with memory · FalkorDB</span>
      <h2>Find another route when a link disappears.</h2>
      <p>Create an issue in <b>primer/design</b> and assign it to <b>carol</b>.
      The usual repository link disappears. Can the agent reach the issue form using steps it learned before?</p>
      <span class="chip">Local Gitea demo · synthetic data · no API key for this walkthrough</span></div>
    <nav class="walk-nav" aria-label="Walkthrough steps">
      <button type="button" data-walk="0"><b>1</b> Learn</button>
      <button type="button" data-walk="1"><b>2</b> Lose a link</button>
      <button type="button" data-walk="2"><b>3</b> Watch replay</button>
    </nav>
    <section class="walk-panel" data-panel="0">
      <h3>Remember steps, then reuse them</h3>
      <p>One training run learned how to find a repository through <b>Explore</b>.
      Another learned how to reach its <b>New Issue</b> form. FalkorDB stores each navigation step
      with the runs that taught it.</p>
      <div class="training-pair">
        <div class="card"><span class="src">explore-3</span><h4>Find a repository</h4><p>Explore → repository</p></div>
        <div class="card"><span class="src">issues-1</span><h4>Reach the issue form</h4><p>Repository → Issues → New Issue</p></div>
      </div>
      <div class="card"><h4>When the usual dashboard link is available</h4>${route(normal)}
        <p class="muted">This route can be replayed from one past run.</p>
        <button class="plain" id="v2n">Highlight the usual route</button></div>
      <button class="go" data-next="1">Hide the usual link →</button>
    </section>
    <section class="walk-panel" data-panel="1" hidden>
      <h3>The link is gone. The steps still connect.</h3>
      <p>This query excludes the dashboard's repository link, as if it were unavailable.
      FalkorDB joins steps from different training runs into an alternative:</p>
      <div class="card"><h4>The composed route <span class="live">LIVE QUERY</span></h4>${route(alternative)}
        <p class="muted">Computed by FalkorDB at ${esc(d.computed_at)}. This is a route query; browser execution is shown in step 3.</p>
        <button class="plain" id="v2b">Highlight the alternative</button></div>
      <h4>Why this route?</h4>
      <p>Every hop has a source. Gold labels mark steps supplied by just one training run.</p>
      <table class="provenance"><tr><th>Hop</th><th>Remembered click</th><th>Learned from</th></tr>${hopRows}</table>
      <p class="${d.no_single_episode_contains_route ? 'ok' : 'bad'}">${d.no_single_episode_contains_route ? 'No single training run contains this whole route.' : 'A training run contains this route.'}</p>
      <button class="go" data-next="2">See the browser replay →</button>
    </section>
    <section class="walk-panel" data-panel="2" hidden>
      <h3>Follow the route in a real browser</h3>
      <p>Replay checks the landing page and chosen repository after each navigation.
      The model then fills and submits the issue form.</p>
      <div class="card"><h4><span class="rec">RECORDED</span>Browser execution</h4>
        <video controls preload="none" poster="/static/demo-poster.jpg" aria-label="Three-minute PathMemory demo with narration and captions">
          <source src="/demo-video" type="video/mp4">
          <a href="/demo-video">Download the three-minute demo</a>
        </video>
        <p class="muted">Three-minute narrated demo. The browser observations are recorded; captions are included in the picture.</p>
        <p><a href="/demo-video" download="pathmemory-demo.mp4">Download the MP4</a></p>
        ${recording ? '<p>Open the saved run and select each step to inspect its browser screenshot. REPLAY marks navigation from memory; LLM marks model actions.</p>' : ''}
        ${recording ? '<button class="go" id="v2watch">Inspect the saved browser steps</button>' : '<p class="muted">Individual browser steps are not saved in this checkout. The video above shows the recorded execution.</p>'}</div>
      <div class="card"><h4>Test the explanation: remove the bridge</h4>
        <p>In a prepared copy, remove <b>Explore → repository</b>. With the dashboard link excluded too,
        the same query ${d.ablation && !d.ablation.broken_ui_routes.length ? '<b class="bad">finds no memory route</b>' : 'finds a route'}.
        The base browser agent can still navigate using the model.</p>
        <button class="plain" id="v2a">Show the graph without the bridge</button>
        <span id="bridge-status" class="muted" role="status"></span></div>
      <p class="muted">Across five recorded trials per mode, graph replay reached the target page 5/5;
      single-trajectory replay and the graph without the bridge reached it through replay 0/5.
      Every mode completed the task. One task and one site; no demonstrated task-success or latency advantage.</p>
      <button class="plain" id="v2results">Inspect all results</button>
    </section>
    <details class="walk-details"><summary>Inspect the training data and query</summary>
      <p>Memory fingerprint: <code>${esc(d.graph_fingerprint)}</code>
      <span class="${d.matches_manifest ? 'ok' : 'bad'}">${d.matches_manifest ? 'matches the training manifest' : 'does not match the training manifest'}</span>.</p>
      <table><tr><th>Task</th><th>Goal</th><th>Steps</th></tr>
        ${d.episodes.map(e => `<tr><td>${esc(e.task)}</td><td>${esc(e.goal)}</td><td>${e.steps}</td></tr>`).join('')}</table>
      <h4>Does any single run contain the composed route?</h4>
      <table><tr><th>Training run</th><th>Route steps present</th><th>Whole route</th></tr>${cont}</table>
      <p>Single-trajectory replay finds ${d.flat_replay.broken_ui.length} route(s) with the dashboard link excluded.</p>
      <pre>${esc(d.cypher)}</pre></details>
    <details class="walk-details"><summary>Run a fresh browser task · API key required</summary>
      <p>Opens Chromium on this machine and calls the model. The Gitea fixture resets first;
      navigation uses a copy of the selected memory. Requires the local setup and API key described in the README.</p>
      <div class="row"><button class="go" id="v2run">Run with graph memory</button>
        <button class="plain" id="v2abl">Run without the bridge</button></div></details>
    <details class="walk-details"><summary>Browse recorded runs</summary>
      <p class="muted">Trial 1 of 5 from the evaluation on 2026-10-18. All trials appear in Results.</p>
      <table class="provenance"><tr><th>Condition</th><th>Mode</th><th>Checker</th><th></th></tr>${rec}</table></details>`;
  const show = async (mem, keys, failed = []) => {
    if (MEM() !== mem) { $('#mem').value = mem; await loadGraph(); }
    clearMarks(); markRoute(keys, 'used');
    failed.forEach(eid => cy.getElementById(eid).removeClass('used').addClass('failed'));
  };
  let walkSequence = 0;
  const selectStep = async index => {
    const sequence = ++walkSequence;
    document.querySelectorAll('[data-walk]').forEach(b => {
      const selected = Number(b.dataset.walk) === index;
      b.classList.toggle('on', selected);
      if (selected) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
    });
    document.querySelectorAll('[data-panel]').forEach(p => { p.hidden = Number(p.dataset.panel) !== index; });
    $('#bridge-status').textContent = '';
    // Return to the training graph after inspecting the bridge-removal copy.
    if (MEM() !== 'v2') { $('#mem').value = 'v2'; await loadGraph(); }
    if (sequence !== walkSequence) return;
    await show('v2', index === 0 ? normal.keys : alternative.keys, index === 0 ? [] : d.broken.banned);
  };
  document.querySelectorAll('[data-walk]').forEach(b => { b.onclick = () => selectStep(Number(b.dataset.walk)); });
  document.querySelectorAll('[data-next]').forEach(b => { b.onclick = () => selectStep(Number(b.dataset.next)); });
  $('#v2n').onclick = () => show('v2', normal.keys);
  $('#v2b').onclick = () => show('v2', alternative.keys, d.broken.banned);
  $('#v2a').onclick = async () => {
    await show('v2-ablated', [], d.broken.banned);
    $('#bridge-status').textContent = d.ablation && !d.ablation.broken_ui_routes.length ? 'No memory route remains.' : 'A memory route remains.';
  };
  if (recording) $('#v2watch').onclick = () => { showTab('run'); openRun(recording.dir); };
  $('#v2results').onclick = () => showTab('results');
  $('#v2run').onclick = () => startDemo('v2');
  $('#v2abl').onclick = () => startDemo('v2-ablated');
  document.querySelectorAll('.recl').forEach(a => { a.onclick = ev => { ev.preventDefault(); showTab('run'); openRun(a.dataset.dir); }; });
  await selectStep(0);
}

function showTab(t) {
  document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === t));
  if (t === 'query') runQuery();
}
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
$('#qsrc').onchange = runQuery; $('#qdst').onchange = runQuery; $('#avoid').onchange = runQuery;

$('#mem').onchange = () => loadGraph();
loadGraph().then(loadExperiments).then(initLive).then(renderV2).catch(error => {
  console.error('Could not load PathMemory:', error);
  $('#v2view').innerHTML = `<div class="card"><h2>Could not load the local demo</h2>
    <p>From the source checkout, run <code>scripts/reproduce_v2.sh</code>, then reload this page.
    If setup has already completed, check that FalkorDB is running and inspect the server terminal for details.</p>
    <p><a href="/demo-video">Watch the three-minute demo video</a></p></div>`;
});
