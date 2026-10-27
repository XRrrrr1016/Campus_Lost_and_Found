/* Campus Lost & Found: framework-free UI, no network or model dependencies. */
'use strict';
const state = {user:null, csrf:'', view:'square', kind:'', items:[], categories:[], currentRun:null, rules:[], loading:false};
const $ = (selector, root=document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const names = {square:'失物招领广场',mine:'我的发布',claims:'认领与交接',matching:'智能匹配',admin:'规则与审计'};
const statuses = {open:'待认领',reserved:'待交接',resolved:'已结案',pending:'待核验',approved:'已通过',rejected:'已驳回',completed:'已交接'};
const confidences = {high:'高相似',medium:'中等相似',low:'低相似',insufficient:'信息不足'};
const symbols = {'证件':'▣','雨伞':'☂','电子产品':'♬','钥匙':'⚿','包袋':'▱','书籍':'▥','衣物':'♧','其他':'◇'};
let toastTimer, renderSequence = 0;

async function api(path, {method='GET', data}={}) {
  const options = {method, headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf}};
  if (data !== undefined) options.body = JSON.stringify(data);
  const response = await fetch(`/api${path}`, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || '请求失败，请稍后再试');
  return result.data;
}
function toast(message, error=false) {
  const el = $('#toast'); clearTimeout(toastTimer); el.textContent = message;
  el.className = error ? 'show error':'show'; toastTimer = setTimeout(() => el.className='', 3800);
}
function badge(status) {return `<span class="pill ${esc(status)}">${esc(statuses[status] || status)}</span>`;}
function options(values, label='全部类别') {return `<option value="">${label}</option>`+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');}
function dateText(value) {return value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '';}
function heading(title, subtitle, action=true) {
  return `<div class="page-heading"><div><div class="eyebrow">CAMPUS LOST & FOUND</div><h1>${title}</h1><p class="subtext">${subtitle}</p></div>${action?'<button class="button primary" data-action="publish"><span>＋</span> 发布信息</button>':''}</div>`;
}
function empty(title, text, action='') {return `<div class="empty"><span>⌕</span><strong>${title}</strong><p>${text}</p>${action}</div>`;}
function art(item, extra='') {
  const palette = {'雨伞':'blue','电子产品':'blue','证件':'sand','包袋':'rose','衣物':'rose'};
  return `<div class="item-art ${palette[item.category] || ''} ${extra}">${item.image ? `<img src="${esc(item.image)}" alt="${esc(item.title)}">`:`<span class="art-object" aria-hidden="true">${symbols[item.category] || '◇'}</span>`}</div>`;
}
function card(item) {
  return `<button class="item-card" data-action="detail" data-id="${item.id}" aria-label="查看${esc(item.title)}">${art(item)}<span class="item-badge ${item.kind}">${item.kind==='lost'?'寻物启事':'拾物招领'}</span><div class="item-content"><h3 class="item-title">${esc(item.title)}</h3><div class="item-detail"><span>⌖</span>${esc(item.location)}</div><div class="item-detail"><span>◷</span>${esc(item.date_from)}${item.date_from!==item.date_to?' ~ '+esc(item.date_to):''}</div><div class="item-bottom status-${item.status}"><span><i class="status-dot"></i>${statuses[item.status]}</span><span>${esc(item.owner_name)} <span class="item-arrow">↗</span></span></div></div></button>`;
}
function updateAccount() {
  const user=state.user;
  $('#account').innerHTML = `<span class="avatar">${user?esc(user.name[0]):'访'}</span><div><strong>${user?esc(user.name):'访客浏览'}</strong><small>${user?(user.role==='admin'?'管理员':'校园用户'):'登录后发布与认领'}</small></div>${user?'<button class="account-exit" data-action="logout" aria-label="退出登录">↪</button>':''}`;
  $('#account-button').textContent = user ? '切换账号':'登录账号';
  document.querySelectorAll('.admin-only').forEach(el => el.hidden=user?.role!=='admin');
}
function modal(title, content) {
  $('#modal-body').innerHTML=`<div class="modal-head"><h2>${title}</h2><button class="modal-close" data-action="close-modal" aria-label="关闭">×</button></div><div class="modal-content">${content}</div>`;
  if (!$('#modal').open) $('#modal').showModal();
}
function loginModal() {
  modal('选择一个演示身份', `<div class="notice">所有账号均为本地虚构样例，可切换体验完整流程。</div><div class="login-options">${[
    ['alice','林同学','失主视角 · 发布失物、寻找与认领'],['bob','陈同学','拾获者视角 · 发布招领、核验交接'],['admin','校园管理员','管理视角 · 规则版本、审计与核验']
  ].map(([id,name,desc])=>`<button class="login-option" data-action="login" data-username="${id}"><span class="avatar">${name[0]}</span><span><strong>${name}</strong><small>${desc}</small></span><span class="arrow">→</span></button>`).join('')}</div><p class="login-help">普通账号密码：demo1234 · 管理员：admin1234。此处仅用于本地演示。</p>`);
}
async function render(view=state.view, filters={}) {
  state.view=view; const sequence=++renderSequence;
  $('#page-name').textContent=names[view];
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.view===view));
  $('#main').innerHTML='<div class="loading">正在整理校园信息…</div>';
  try {
    if (view==='square'||view==='mine') {
      if(view==='mine'&&!state.user) { $('#main').innerHTML=heading('我的发布','管理自己的失物与招领信息',false)+empty('登录后查看你的发布','选择演示身份，开始体验校园拾光。','<button class="button primary" data-action="login-modal">选择身份</button>'); return; }
      const query=new URLSearchParams({...filters,...(view==='mine'?{mine:'1'}:{})});
      if(state.kind) query.set('kind',state.kind);
      const [items,all]=await Promise.all([api('/items?'+query),api('/items')]);
      if(sequence!==renderSequence) return;
      state.items=items;
      const hero=view==='square'?`<section class="hero"><div class="hero-copy"><div class="hero-label">LOST SOMETHING? FIND A LITTLE HOPE.</div><h2>让遗失的美好，重新相遇。</h2><p>也许你正在寻找的，正被另一个人好好保管。<br>发布一条信息，让校园里的善意连接起来。</p><button class="hero-link" data-view="matching">试试智能匹配 <span>↗</span></button></div><div class="hero-art" aria-hidden="true"><div class="art-disc"></div><div class="art-card"></div><div class="art-tag">好好保管 · 等你来领</div><span class="art-spark">✧</span></div></section>`:'';
      $('#main').innerHTML=heading(view==='square'?'失物招领广场':'我的发布',view==='square'?'一份小小的善意，连接每一次失而复得。':'追踪发布状态，为你的物品寻找另一半线索。')+hero+
        `<div class="stats"><div class="stat"><div><span class="stat-label">正在寻找主人</span><strong class="stat-value">${all.filter(i=>i.kind==='found'&&i.status==='open').length.toString().padStart(2,'0')}</strong><span class="stat-caption">每一件拾物，都在等一次重逢</span></div><span class="stat-icon">▱</span></div><div class="stat"><div><span class="stat-label">待寻找的失物</span><strong class="stat-value">${all.filter(i=>i.kind==='lost'&&i.status==='open').length.toString().padStart(2,'0')}</strong><span class="stat-caption">多一条线索，就多一份希望</span></div><span class="stat-icon">⌕</span></div><div class="stat"><div><span class="stat-label">已完成交接</span><strong class="stat-value">${all.filter(i=>i.kind==='found'&&i.status==='resolved').length.toString().padStart(2,'0')}</strong><span class="stat-caption">感谢每一位温暖的拾获者</span></div><span class="stat-icon">✓</span></div></div>`+
        `<div class="section-toolbar"><div class="tabs">${[['','全部信息'],['lost','寻物启事'],['found','拾物招领']].map(([id,label])=>`<button class="tab ${state.kind===id?'active':''}" data-action="kind" data-kind="${id}">${label}</button>`).join('')}</div><span class="list-hint">共 ${items.length} 条信息 · 最近发布优先</span></div>`+
        `<form id="filter-form" class="filters"><input class="input" type="search" name="q" placeholder="⌕  搜索物品名称、描述或地点" aria-label="关键词" value="${esc(filters.q||'')}"><select name="category" aria-label="物品类别">${options(state.categories)}</select><input class="input" name="location" placeholder="地点" aria-label="地点" value="${esc(filters.location||'')}"><select name="status" aria-label="状态">${options(['open','reserved','resolved'],'全部状态').replace('>open<','>待认领<').replace('>reserved<','>待交接<').replace('>resolved<','>已结案<')}</select><input class="input" name="date_from" type="date" aria-label="开始日期" value="${esc(filters.date_from||'')}"><span class="date-divider">—</span><input class="input" name="date_to" type="date" aria-label="结束日期" value="${esc(filters.date_to||'')}"><button class="button" type="submit">筛选</button><button class="button" type="button" data-action="reset-filters">重置</button></form><div class="cards">${items.length?items.map(card).join(''):empty('暂时没有找到相关信息','试试其他关键词，或发布一条新的信息。')}</div>`;
      const form=$('#filter-form'); form.elements.category.value=filters.category||''; form.elements.status.value=filters.status||'';
    } else if(view==='claims') await renderClaims(sequence);
    else if(view==='matching') await renderMatching(sequence);
    else if(view==='admin') await renderAdmin(sequence);
  } catch(error) {if(sequence===renderSequence) $('#main').innerHTML=heading(names[view],'',false)+empty('暂时无法加载',esc(error.message),'<button class="button" data-action="retry">重试</button>');}
}

async function renderClaims(sequence) {
  if(!state.user) {$('#main').innerHTML=heading('认领与交接','从一条线索，到一次安心的交接。',false)+empty('登录后追踪认领进度','拾获者可在这里核验申请。','<button class="button primary" data-action="login-modal">选择身份</button>');return;}
  const claims=await api('/claims'); if(sequence!==renderSequence)return;
  $('#main').innerHTML=heading('认领与交接','未公开特征核验通过后，才会向双方开放联系方式。',false)+`<div class="notice">流程：提交认领 → 拾获者核验 → 联系交接 → 确认结案。匹配分数不会自动确认归属。</div>`+
    (claims.length?claims.map(c=>{const manage=c.owner_id===state.user.id||state.user.role==='admin';return `<section class="panel"><div class="panel-head"><h3>${esc(c.title)}</h3>${badge(c.status)}</div><div class="meta-row"><span>申请 #${c.id}</span><span>申请人：${esc(c.applicant_name)}</span><span>拾获者：${esc(c.owner_name)}</span><span>${dateText(c.created_at)}</span></div>${c.note?`<p>申请备注：${esc(c.note)}</p>`:''}${manage?`<div class="verification ${c.feature_matches?'':'bad'}">私密特征核验：${c.feature_matches?'✓ 回答与预设特征一致':'× 回答与预设特征不符'}<br><small>核验问题：${esc(c.secret_question)}</small></div>`:''}${c.review_note?`<p>处理说明：${esc(c.review_note)}</p>`:''}${c.finder_contact?`<div class="contact">拾获者联系方式：${esc(c.finder_contact)}${c.applicant_contact?'<br>失主联系方式：'+esc(c.applicant_contact):''}</div>`:''}${manage&&c.status==='pending'?`<div class="actions">${c.feature_matches?`<button class="button primary small" data-action="approve" data-id="${c.id}">核验通过</button>`:''}<button class="button danger small" data-action="reject" data-id="${c.id}">驳回申请</button></div>`:''}${manage&&c.status==='approved'?`<div class="actions"><button class="button primary small" data-action="complete" data-id="${c.id}">已交接，确认结案</button></div>`:''}</section>`;}).join(''):empty('还没有认领申请','到广场寻找线索，或等待失主认领你的拾物。','<button class="button" data-view="square">前往广场</button>'));
}

function runResults(run) {
  if(!run)return '';
  return `<section class="panel"><div class="panel-head"><h3>候选匹配结果</h3><span class="pill">规则 v${run.rule_version} · 批次 #${run.id}</span></div><p>离线文本模拟 · ${esc(run.engine_version)}${run.identical!==undefined?' · '+(run.identical?'✓ 与历史结果完全一致':'结果存在差异'):''}</p>${run.results.length?run.results.map(r=>`<div class="match-result"><div class="score-box"><strong class="match-score">${r.score}</strong><small>${confidences[r.confidence]}</small></div><div class="match-result-content"><h3>${esc(r.title)}</h3><p>${esc(r.explanation)}</p><button class="text-button" data-action="detail" data-id="${r.candidate_id}" data-lost-id="${run.source_id}">查看记录与核验问题 →</button></div></div>`).join(''):empty('暂时没有异类候选','发布更多信息后可重新匹配。')}</section>`;
}
async function renderMatching(sequence) {
  if(!state.user){$('#main').innerHTML=heading('智能匹配','让零散的线索，指向同一个答案。',false)+empty('登录后匹配你的物品','推荐需要关联你发布的记录。','<button class="button primary" data-action="login-modal">选择身份</button>');return;}
  const [items,history]=await Promise.all([api('/items?mine=1&status=open'),api('/recommendations')]);
  if(sequence!==renderSequence)return;
  $('#main').innerHTML=heading('智能匹配','让零散的线索，指向同一个答案。',false)+`<div class="notice">AI 演示模式：基于文本相似度与字段权重，无需密钥、不会发送数据到外部。分数用于筛选候选；信息不足时拒绝判断。</div><section class="panel"><h3>为我的记录寻找线索</h3>${items.length?`<form id="match-form" class="filters"><select name="item_id" class="input" required aria-label="选择要匹配的记录">${items.map(i=>`<option value="${i.id}">${i.kind==='lost'?'失物':'招领'} · ${esc(i.title)}</option>`).join('')}</select><button class="button primary" type="submit">✧ 开始智能匹配</button></form>`:`<p>还没有开放的发布记录。</p><button class="button" data-action="publish">发布一条信息</button>`}</section><div id="run-results">${runResults(state.currentRun)}</div><section class="panel"><h3>推荐历史与复算</h3><p>每次匹配冻结输入及规则版本，原记录删除或新规则发布后，历史批次仍可复算。</p>${history.length?history.map(h=>`<div class="history-row"><span>#${h.id} ${esc(h.title)}<br><small>规则 v${h.rule_version} · ${dateText(h.created_at)}</small></span><button class="button small" data-action="recompute" data-id="${h.id}">复算历史</button></div>`).join(''):'<p>暂无推荐记录。</p>'}</section>`;
}

async function renderAdmin(sequence) {
  if(state.user?.role!=='admin'){ $('#main').innerHTML=heading('规则与审计','',false)+empty('需要管理员身份','切换为管理员后查看此页面。','<button class="button" data-action="login-modal">切换账号</button>');return;}
  const [rules,audits]=await Promise.all([api('/rules'),api('/audits')]);if(sequence!==renderSequence)return;state.rules=rules;
  const fields={category:'类别',location:'地点',color:'颜色',time:'时间',text:'文本描述'};
  $('#main').innerHTML=heading('规则与审计','每一次调整有版本，每一次操作有记录。',false)+`<section class="panel"><div class="panel-head"><h3>发布匹配规则</h3><span class="pill">当前 v${rules[0].id}</span></div><p>权重会自动归一化；设为 0 即关闭该字段。至少三项有效可比字段才给出置信等级。</p><form id="rule-form"><label class="field">版本说明<input class="input" name="name" maxlength="100" required placeholder="例如：更重视地点与文字描述"></label><div class="rule-grid">${Object.entries(fields).map(([key,label])=>`<label>${label}权重<input class="input" name="${key}" type="number" min="0" max="100" step="1" value="${Math.round(rules[0].weights[key]*100)}" required></label>`).join('')}</div><div class="form-footer"><button class="button primary" type="submit">发布新版本</button></div></form></section><section class="panel"><h3>规则版本</h3><div class="table-wrap"><table><thead><tr><th>版本</th><th>说明</th><th>字段权重</th><th>发布时间</th></tr></thead><tbody>${rules.map(r=>`<tr><td>v${r.id}</td><td>${esc(r.name)}</td><td>${Object.entries(r.weights).map(([key,v])=>`${fields[key]} ${Math.round(v*100)}%`).join(' · ')}</td><td>${dateText(r.created_at)}</td></tr>`).join('')}</tbody></table></div></section><section class="panel"><h3>关键操作审计</h3><p>最近 500 条记录；删除、核验、驳回、结案与规则发布均留痕。</p><div class="table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>对象</th><th>详情</th></tr></thead><tbody>${audits.map(a=>`<tr><td>${dateText(a.created_at)}</td><td>${esc(a.actor_name||'系统')}</td><td><code>${esc(a.action)}</code></td><td>${esc(a.entity_type)} #${a.entity_id||'—'}</td><td>${esc(JSON.stringify(a.detail))}</td></tr>`).join('')}</tbody></table></div></section>`;
}

async function detail(id, linkedLostId) {
  const item=await api('/items/'+id);
  const manage=state.user&&(item.owner_id===state.user.id||state.user.role==='admin');
  modal('物品详情', `${art(item,'detail-art')}<div class="panel-head"><h2>${esc(item.title)}</h2>${badge(item.status)}</div><div class="detail-data"><div><small>发布类型</small>${item.kind==='lost'?'寻物启事':'拾物招领'}</div><div><small>类别 / 颜色</small>${esc(item.category)} / ${esc(item.color)}</div><div><small>地点</small>${esc(item.location)}</div><div><small>时间范围</small>${esc(item.date_from)} ~ ${esc(item.date_to)}</div></div><p class="detail-description">${esc(item.description)}</p>${item.contact?`<div class="contact">联系方式：${esc(item.contact)}</div>`:'<div class="notice">联系方式已保护，私密特征核验通过后可见。</div>'}${item.secret_question?`<p class="subtext">认领核验问题：${esc(item.secret_question)}</p>`:''}<div class="form-footer">${manage&&item.status==='open'?`<button class="button danger" data-action="delete" data-id="${item.id}">删除记录</button><button class="button" data-action="match-item" data-id="${item.id}">智能匹配</button>`:''}${item.kind==='found'&&item.status==='open'&&item.owner_id!==state.user?.id?`<button class="button primary" data-action="claim" data-id="${item.id}" data-lost-id="${linkedLostId||''}">这是我的，申请认领</button>`:''}<button class="button" data-action="close-modal">关闭</button></div>`);
}

function publishModal() {
  if(!state.user){loginModal();return;}
  const today=new Date().toLocaleDateString('en-CA');
  modal('发布一条校园信息', `<form id="publish-form" class="form-grid"><label class="field">信息类型<select name="kind"><option value="lost">我丢失了物品</option><option value="found">我捡到了物品</option></select></label><label class="field">物品类别<select name="category" required>${options(state.categories,'请选择类别')}</select></label><label class="field full">标题<input class="input" name="title" maxlength="80" required placeholder="例如：在图书馆遗失黑色卡包"></label><label class="field">开始日期<input class="input" name="date_from" type="date" required value="${today}"></label><label class="field">结束日期<input class="input" name="date_to" type="date" required value="${today}"></label><label class="field">地点<input class="input" name="location" maxlength="100" required placeholder="尽可能具体"></label><label class="field">颜色<input class="input" name="color" maxlength="30" required placeholder="例如：黑色 / 不详"></label><label class="field full">公开描述<textarea name="description" maxlength="2000" required placeholder="描述公共外观，请保留至少一个细节用于私密核验"></textarea></label><label class="field full">联系方式（核验前受保护）<input class="input" name="contact" maxlength="150" required placeholder="例如：校园邮箱或微信"></label><div class="field full" id="secret-fields" hidden><label class="field">未公开特征的核验问题<input class="input" name="secret_question" maxlength="200" placeholder="例如：内侧手写的两个字是什么？"></label><label class="field">私密答案<input class="input" name="secret_answer" maxlength="100" placeholder="不要在公开描述或图片中展示" autocomplete="off"></label><small>答案会进行带盐哈希保存。请勿把敏感细节写进公开信息。</small></div><label class="field full">可选图片<input name="photo" type="file" accept="image/png,image/jpeg,image/webp"><small>支持 PNG/JPEG/WebP，最大 500KB；请确认照片未暴露私密核验答案。</small></label><p class="form-error field full" id="form-error" role="alert" hidden></p><div class="form-footer field full"><button class="button" type="button" data-action="close-modal">取消</button><button class="button primary" type="submit">发布信息</button></div></form>`);
  $('#publish-form select[name=kind]').addEventListener('change',event=>{
    const found=event.target.value==='found';$('#secret-fields').hidden=!found;
    for(const key of ['secret_question','secret_answer']) $('#publish-form').elements[key].required=found;
  });
}
async function claimModal(id, lostId) {
  if(!state.user){loginModal();return;}
  const [item,lost]=await Promise.all([api('/items/'+id),api('/items?mine=1&kind=lost&status=open')]);
  modal('申请认领', `<div class="notice">${esc(item.title)}<br>请回答只有失主知道的未公开特征，等待拾获者核验。</div><form id="claim-form" data-id="${id}" class="form-grid"><label class="field full">${esc(item.secret_question)}<input class="input" name="answer" required maxlength="100" autocomplete="off" placeholder="填写私密特征答案"></label><label class="field full">关联我的失物记录（可选）<select name="lost_item_id"><option value="">不关联失物记录</option>${lost.map(i=>`<option value="${i.id}">${esc(i.title)}</option>`).join('')}</select></label><label class="field full">补充说明<textarea name="note" maxlength="500" placeholder="可以说明认领经过，请勿填写无关隐私"></textarea></label><p class="form-error field full" id="form-error" hidden role="alert"></p><div class="form-footer field full"><button class="button" type="button" data-action="close-modal">取消</button><button class="button primary" type="submit">提交核验申请</button></div></form>`);
  $('#claim-form > label').insertAdjacentHTML('afterend', '<label class="field full">我的联系方式（核验通过后向双方开放）<input class="input" name="contact" maxlength="150" required placeholder="邮箱或微信；核验前受保护"></label>');
  if(lostId && lost.some(i=>i.id===Number(lostId))) $('#claim-form').elements.lost_item_id.value=lostId;
}
function confirmation(title, description, action, id, needsReason=false) {
  modal(title,`<p class="detail-description">${description}</p><form id="confirm-form" data-operation="${action}" data-id="${id}">${needsReason?'<label class="field">处理原因<textarea name="reason" required maxlength="300" placeholder="请填写原因，操作将记录在审计中"></textarea></label>':''}<p class="form-error" id="form-error" hidden role="alert"></p><div class="form-footer"><button class="button" type="button" data-action="close-modal">取消</button><button class="button primary" type="submit">确认操作</button></div></form>`);
}

document.addEventListener('click',async event=>{
  const el=event.target.closest('[data-action],[data-view]');if(!el)return;
  if(el.dataset.view){await render(el.dataset.view);return;}
  const action=el.dataset.action,id=el.dataset.id;
  try {
    if(action==='close-modal')$('#modal').close();
    else if(action==='login-modal')loginModal();
    else if(action==='login'){
      el.disabled=true;const username=el.dataset.username;
      const result=await api('/login',{method:'POST',data:{username,password:username==='admin'?'admin1234':'demo1234'}});
      state.user=result.user;state.csrf=result.csrf;state.currentRun=null;$('#modal').close();updateAccount();
      await render(state.view==='admin'&&state.user.role!=='admin'?'square':state.view);toast('已切换为'+state.user.name);
    } else if(action==='logout') {
      await api('/logout',{method:'POST',data:{}});state.user=null;state.csrf='';state.currentRun=null;updateAccount();await render('square');toast('已退出登录');
    } else if(action==='publish')publishModal();
    else if(action==='detail')await detail(id,el.dataset.lostId);
    else if(action==='claim')await claimModal(id,el.dataset.lostId);
    else if(action==='kind'){state.kind=el.dataset.kind;await render();}
    else if(action==='reset-filters'){state.kind='';await render();}
    else if(action==='retry')await render();
    else if(action==='approve')confirmation('核验通过','确认私密特征一致并安排交接？通过后双方可见联系方式，该物品的其他待审申请将被驳回。','approve',id);
    else if(action==='reject')confirmation('驳回认领申请','请记录特征不符或其他驳回原因。','reject',id,true);
    else if(action==='complete')confirmation('确认交接与结案','请确认物品已经交还失主。关联的失物记录也会同时结案。','complete',id);
    else if(action==='delete')confirmation('删除发布记录','记录将从广场移除，相关待审申请将被驳回，审计记录保留。','delete',id,true);
    else if(action==='match-item'){
      state.currentRun=await api(`/items/${id}/matches`,{method:'POST',data:{}});$('#modal').close();await render('matching');
    } else if(action==='recompute'){
      el.disabled=true;state.currentRun=await api(`/recommendations/${id}/recompute`,{method:'POST',data:{}});await render('matching');toast(state.currentRun.identical?'复算完成，与原结果完全一致':'复算完成，结果存在差异');
    }
  } catch(error){toast(error.message,true);el.disabled=false;}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!(form instanceof HTMLFormElement))return;event.preventDefault();
  const submit=form.querySelector('button[type=submit]');if(submit)submit.disabled=true;
  const values=Object.fromEntries(new FormData(form));
  try {
    if(form.id==='filter-form'){await render(state.view,values);return;}
    if(form.id==='publish-form'){
      delete values.photo;
      const file=form.elements.photo.files[0];
      if(file){
        if(file.size>500000)throw new Error('图片不得超过 500KB');
        values.image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('图片读取失败'));reader.readAsDataURL(file);});
      }
      await api('/items',{method:'POST',data:values});$('#modal').close();state.kind='';await render('mine');toast('发布成功，新的线索已加入广场');
    } else if(form.id==='claim-form'){
      values.lost_item_id=values.lost_item_id?Number(values.lost_item_id):null;
      await api(`/items/${form.dataset.id}/claims`,{method:'POST',data:values});$('#modal').close();await render('claims');toast('认领申请已提交，请等待核验');
    } else if(form.id==='match-form'){
      state.currentRun=await api(`/items/${values.item_id}/matches`,{method:'POST',data:{}});await render('matching');toast('匹配完成，请结合私密特征核验');
    } else if(form.id==='rule-form'){
      const weights={};for(const key of ['category','location','color','time','text'])weights[key]=Number(values[key]);
      await api('/rules',{method:'POST',data:{name:values.name,weights}});await render('admin');toast('新规则版本已发布，历史版本已保留');
    } else if(form.id==='confirm-form'){
      const operation=form.dataset.operation,id=form.dataset.id;
      if(operation==='delete')await api('/items/'+id,{method:'DELETE',data:{reason:values.reason}});
      else if(operation==='complete')await api(`/claims/${id}/complete`,{method:'POST',data:{}});
      else await api(`/claims/${id}/review`,{method:'POST',data:{decision:operation==='approve'?'approve':'reject',note:values.reason||'私密特征一致，安排交接'}});
      $('#modal').close();await render();toast('操作已完成并记录审计');
    }
  } catch(error){const message=$('#form-error',form);if(message){message.hidden=false;message.textContent=error.message;}else toast(error.message,true);}
  finally{if(submit)submit.disabled=false;}
});
$('#account-button').addEventListener('click',loginModal);
$('.brand').addEventListener('click',event=>{event.preventDefault();state.kind='';render('square');});
$('#modal').addEventListener('click',event=>{if(event.target===$('#modal')){const r=$('#modal').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('#modal').close();}});
(async()=>{try{const [session,meta]=await Promise.all([api('/session'),api('/meta')]);state.user=session.user;state.csrf=session.csrf;state.categories=meta.categories;updateAccount();await render();}catch(error){$('#main').innerHTML=empty('服务暂时不可用',esc(error.message));}})();
