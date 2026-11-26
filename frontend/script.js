/* Static Agent Team interaction prototype. It uses local in-memory examples and does not call the Python API. */
const agents = [
  { id: 'image', name: '小T', role: '图片理解、生成与编辑', icon: 'T', color: '#fae7dd', ink: '#c28464', tools: ['文件读取', '图像生成'], model: 'DeepSeek Chat', approval: true },
  { id: 'video', name: '小V', role: '视频理解、生成与编辑', icon: 'V', color: '#dcebea', ink: '#4e9c91', tools: ['文件读取', '视频生成'], model: 'DeepSeek Chat', approval: true }
];
const groups = [
  { id: 'multimedia', name: '媒体群', role: '小未、小T、小V', icon: '媒', color: '#e4ede7', ink: '#398769' }
];
const activity = [
  { id: 'multimedia', kind: 'group', text: '小未：图片与视频方案等待你确认。', time: '刚刚', status: '待审批', approval: true, unread: true },
  { id: 'image', kind: 'agent', text: '小T：主视觉草图已经准备好。', time: '5 分钟前', status: '有新消息', unread: true },
  { id: 'video', kind: 'agent', text: '小V：视频方案已整理完成。', time: '12 分钟前', status: '有新消息', unread: true }
];
const conversations = {
  image: [{ from: 'them', text: '主视觉草图已经准备好。' }],
  video: [{ from: 'them', text: '视频方案已整理完成。' }],
  multimedia: [{ from: 'them', speaker: '小未', text: '图片与视频方案等待你确认。', approval: true }, { from: 'them', speaker: '小T', text: '主视觉方向已经整理好。' }]
};
const assistantMessages = [];
const toolOptions = ['网页搜索', '文件读取', '代码执行', '图像生成', '日历访问', '外部发送'];
let selected = 'assistant';
let expanded = false;
let approvalOnly = false;
let settingsAgent = null;
let toastTimer;
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const avatar = (item, extra = '') => `<span class="avatar ${extra}" style="background:${item.color};color:${item.ink}">${escapeHtml(item.icon)}</span>`;
const itemById = (id) => [...agents, ...groups].find((item) => item.id === id);

function renderContacts() {
  $('#agentCount').textContent = String(agents.length).padStart(2, '0');
  $('#teamCount').textContent = `${agents.length + 1} 位 Agent 正在协作`;
  $('#agentList').innerHTML = agents.map((agent) => `<button class="contact-row ${selected === agent.id ? 'selected' : ''}" data-contact="${agent.id}">${avatar(agent)}<span class="contact-copy"><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.role)}</small></span><span class="tiny-dot"></span></button>`).join('');
  $('#groupList').innerHTML = groups.map((group) => `<button class="contact-row ${selected === group.id ? 'selected' : ''}" data-contact="${group.id}">${avatar(group)}<span class="contact-copy"><strong>${escapeHtml(group.name)}</strong><small>${escapeHtml(group.role)}</small></span></button>`).join('');
  document.querySelectorAll('[data-contact]').forEach((button) => button.addEventListener('click', () => selectConversation(button.dataset.contact)));
}

function renderChat() {
  const assistant = selected === 'assistant';
  const item = itemById(selected);
  $('#chatAvatar').outerHTML = assistant ? '<div class="avatar assistant-avatar" id="chatAvatar">✦</div>' : `<div class="avatar" id="chatAvatar" style="background:${item.color};color:${item.ink}">${escapeHtml(item.icon)}</div>`;
  $('#chatTitle').innerHTML = assistant ? '小未 <span class="assistant-label">个人助理</span>' : `${escapeHtml(item.name)} <span class="assistant-label">${agents.includes(item) ? 'Agent 好友' : '协作群聊'}</span>`;
  $('#chatSubtitle').textContent = assistant ? '在线 · 随时为你协调团队' : item.role;
  $('#agentSettings').hidden = assistant || !agents.includes(item);
  $('#messageInput').placeholder = assistant ? '给小未发消息，或直接安排一个任务…' : `给${item.name}发消息…`;
  $('#suggestions').hidden = !assistant;
  const welcome = assistant ? `<div class="day-marker">今天 · 你的团队已准备就绪</div><div class="welcome"><div class="avatar assistant-avatar">✦</div><div class="bubble"><p><strong>你好，我是小未。✦</strong></p><p>默认好友有小T和小V，媒体群由我协调。告诉我你想完成什么，我会拆解任务并找到合适的伙伴。</p><p>需要新能力时，我也能为你创建新的 Agent 好友。</p><div class="task-card"><span class="task-card-label">当前协作群聊</span><h4>媒体群</h4><div class="task-people"><span class="mini-avatar" style="background:#fae7dd;color:#c28464">T</span><span class="mini-avatar" style="background:#dcebea;color:#4e9c91">V</span> 小未、小T、小V</div><button id="openMultimedia">查看协作群聊</button></div></div></div>` : '<div class="day-marker">今天 · 对话已连接</div>';
  const messages = assistant ? assistantMessages : (conversations[selected] || []);
  $('#chatBody').innerHTML = welcome + messages.map((message) => `<div class="message-row ${message.from === 'me' ? 'mine' : ''}">${message.from === 'me' ? '' : `<div class="avatar ${assistant ? 'assistant-avatar' : ''}" style="${assistant ? '' : `background:${item.color};color:${item.ink}`}" >${assistant ? '✦' : escapeHtml(item.icon)}</div>`}<div><div class="message-meta">${message.from === 'me' ? '你' : escapeHtml(message.speaker || (assistant ? '小未' : item.name))} · 刚刚</div><div class="bubble">${escapeHtml(message.text)}${message.approval && !message.resolved ? `<div class="task-card"><span class="task-card-label">等待你的决定</span><h4>批准这项操作？</h4><button class="approve-action" data-id="${selected}">批准执行</button><button class="reject-action" data-id="${selected}" style="margin-left:15px;color:#a08373">暂不批准</button></div>` : ''}</div></div></div>`).join('');
  $('#openMultimedia')?.addEventListener('click', () => selectConversation('multimedia'));
  document.querySelectorAll('.approve-action,.reject-action').forEach((button) => button.addEventListener('click', () => resolveApproval(button.dataset.id, button.classList.contains('approve-action'))));
  $('#chatBody').scrollTop = $('#chatBody').scrollHeight;
}

function renderActivity() {
  const visible = approvalOnly ? activity.filter((entry) => entry.approval) : expanded ? activity : activity.slice(0, 6);
  $('#activityTitle').innerHTML = `${approvalOnly ? '待我审批' : '最近动态'} <span class="activity-count" id="activityCount">${String(visible.length).padStart(2, '0')}</span>`;
  $('#activityIntro').textContent = approvalOnly ? '所有需要你做决定的对话，都汇集在这里。' : expanded ? '所有 Agent 好友和群聊的消息，一屏查看。' : '团队正在处理的事，随时一眼掌握。';
  $('#activityList').innerHTML = visible.length ? visible.map((entry) => { const item = itemById(entry.id); return `<button class="activity-card" data-activity="${entry.id}"><div class="card-top">${avatar(item)}<span class="card-title"><strong>${escapeHtml(item.name)}${entry.unread ? '<span class="unread-dot"></span>' : ''}</strong><small>${entry.kind === 'group' ? '协作群聊' : item.role}</small></span><span class="card-time">${entry.time}</span></div><p>${escapeHtml(entry.text)}</p><div class="card-footer"><span>${entry.kind === 'group' ? item.role : 'Agent 好友'}</span><span class="${entry.approval ? 'approval-status' : 'status'}">${entry.approval ? '● ' : ''}${entry.status}</span></div></button>`; }).join('') : '<div class="empty-state">所有审批已处理完成 ✦</div>';
  document.querySelectorAll('[data-activity]').forEach((button) => button.addEventListener('click', () => selectConversation(button.dataset.activity)));
  $('#allFilter').classList.toggle('active', !approvalOnly);
  $('#approvalFilter').classList.toggle('active', approvalOnly);
  $('#workspace').classList.toggle('approvals', approvalOnly);
  $('#approvalFilter .approval-badge').textContent = activity.filter((entry) => entry.approval).length;
}

function selectConversation(id) {
  selected = id;
  if (id !== 'assistant') { const entry = activity.find((item) => item.id === id); if (entry) entry.unread = false; }
  renderContacts(); renderChat(); renderActivity();
  $('#sidebar').classList.remove('mobile-open');
}

function resolveApproval(id, approved) {
  const entry = activity.find((item) => item.id === id);
  if (entry) { entry.approval = false; entry.status = approved ? '已批准' : '已暂缓'; entry.text = approved ? '你已批准执行，Agent 正在继续处理。' : '你已暂缓这项操作。'; }
  (conversations[id] || []).forEach((message) => { message.resolved = true; });
  (conversations[id] || []).push({ from: 'me', text: approved ? '批准执行' : '暂不批准' });
  renderChat(); renderActivity(); showToast(approved ? '已批准，Agent 将继续处理' : '已暂缓这项操作');
}

function showToast(message) { clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').classList.add('show'); toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 3000); }
function closeOverlays() { $('#settingsDrawer').classList.remove('open'); $('#settingsDrawer').setAttribute('aria-hidden', 'true'); $('#createModal').hidden = true; $('#overlay').hidden = true; }
function openSettings() {
  const agent = agents.find((item) => item.id === selected); if (!agent) return;
  settingsAgent = agent;
  $('#drawerTitle').textContent = `${agent.name}的能力配置`;
  $('#drawerAgentName').textContent = agent.name;
  $('#drawerAgentRole').textContent = agent.role;
  $('#drawerAvatar').style.cssText = `background:${agent.color};color:${agent.ink}`;
  $('#drawerAvatar').textContent = agent.icon;
  $('#modelSelect').value = agent.model;
  $('#approvalToggle').checked = agent.approval;
  $('#toolToggles').innerHTML = toolOptions.map((tool) => `<label class="setting-row"><span><strong>${tool}</strong><small>${tool === '外部发送' ? '邮件或消息发送需额外审批' : '允许 Agent 使用此工具'}</small></span><input type="checkbox" data-tool="${tool}" ${agent.tools.includes(tool) ? 'checked' : ''}/><span class="switch"></span></label>`).join('');
  $('#overlay').hidden = false; $('#settingsDrawer').classList.add('open'); $('#settingsDrawer').setAttribute('aria-hidden', 'false');
}
function createAgent() {
  const name = $('#newAgentName').value.trim(); const role = $('#newAgentRole').value.trim();
  if (!name || !role) { showToast('请填写 Agent 名称和专长'); return; }
  const agent = { id: `custom-${Date.now()}`, name, role, icon: name.slice(0, 1), color: '#e0f1e9', ink: '#398d73', tools: ['文件读取'], model: 'GPT-5.1', approval: true };
  agents.push(agent); conversations[agent.id] = [{ from: 'them', text: `你好，我是${name}。${role}，期待和你一起工作！` }];
  activity.unshift({ id: agent.id, kind: 'agent', text: conversations[agent.id][0].text, time: '刚刚', status: '新成员', unread: true });
  closeOverlays(); $('#newAgentName').value = ''; $('#newAgentRole').value = '';
  selectConversation(agent.id); showToast(`${name}已加入你的团队`);
}
function sendMessage(event) {
  event.preventDefault(); const text = $('#messageInput').value.trim(); if (!text) return;
  const target = selected === 'assistant' ? assistantMessages : (conversations[selected] ||= []);
  target.push({ from: 'me', text }); $('#messageInput').value = '';
  if (selected === 'assistant') {
    const needsNewAgent = /竞品|分析|数据/.test(text);
    let reply;
    if (needsNewAgent && !agents.some((agent) => agent.id === 'analyst')) {
      agents.push({ id: 'analyst', name: '数数', role: '数据分析与竞品洞察', icon: '数', color: '#e2ebfa', ink: '#6787b9', tools: ['网页搜索', '文件读取'], model: 'GPT-5.1', approval: true });
      conversations.analyst = [{ from: 'them', text: '你好！我已经准备好分析数据与竞品，之后可以直接找我。' }];
      activity.unshift({ id: 'analyst', kind: 'agent', text: conversations.analyst[0].text, time: '刚刚', status: '新成员', unread: true });
      reply = '我已将任务拆解，并为你创建了「数数」这位数据分析 Agent。已配置网页搜索和文件读取权限，关键操作仍需你审批。你可以在左侧好友列表找到她。';
      renderContacts(); renderActivity();
    } else if (/(skill|技能)/i.test(text) && /创建|制作|改进/.test(text)) reply = '我会先明确这个 Skill 的用途和触发条件，再整理可复用步骤。正式创建前需要你审批。';
    else if (/图片|视频|媒体|发布/.test(text)) reply = '收到。我会在媒体群协调小T和小V处理图片与视频，关键操作会先请你审批。';
    else reply = '收到，我会先拆解任务，再分配给合适的 Agent。你可以随时在右侧查看最新进展和待审批事项。';
    assistantMessages.push({ from: 'them', text: reply });
  } else target.push({ from: 'them', text: '收到，我已经记下这项需求，会继续推进并同步进展。' });
  renderChat();
}

$('#messageForm').addEventListener('submit', sendMessage);
$('#messageInput').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#messageForm').requestSubmit(); } });
document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => { $('#messageInput').value = button.dataset.prompt; $('#messageForm').requestSubmit(); }));
$('#homeButton').addEventListener('click', () => selectConversation('assistant'));
$('#railAgents').addEventListener('click', () => { $('#sidebar').classList.remove('collapsed'); $('#sidebar').classList.add('mobile-open'); $('#agentsToggle').setAttribute('aria-expanded', 'true'); $('#agentList').classList.remove('collapsed'); });
$('#railGroups').addEventListener('click', () => { $('#sidebar').classList.remove('collapsed'); $('#sidebar').classList.add('mobile-open'); $('#groupsToggle').setAttribute('aria-expanded', 'true'); $('#groupList').classList.remove('collapsed'); });
$('#collapseSidebar').addEventListener('click', () => { $('#sidebar').classList.toggle('collapsed'); $('#sidebar').classList.remove('mobile-open'); });
$('#mobileMenu').addEventListener('click', () => { $('#sidebar').classList.remove('collapsed'); $('#sidebar').classList.toggle('mobile-open'); });
for (const id of ['agents', 'groups']) { $(`#${id}Toggle`).addEventListener('click', () => { const button = $(`#${id}Toggle`); const open = button.getAttribute('aria-expanded') === 'true'; button.setAttribute('aria-expanded', String(!open)); $(`#${id === 'agents' ? 'agentList' : 'groupList'}`).classList.toggle('collapsed', open); }); }
$('#expandButton').addEventListener('click', () => { expanded = !expanded; $('#workspace').classList.toggle('expanded', expanded); $('#expandButton').innerHTML = expanded ? '⤡ <span>收起</span>' : '⤢ <span>展开</span>'; $('#expandButton').setAttribute('aria-label', expanded ? '收起所有对话' : '展开所有对话'); renderActivity(); });
$('#mobileActivityButton').addEventListener('click', () => $('#expandButton').click());
$('#allFilter').addEventListener('click', () => { approvalOnly = false; renderActivity(); });
$('#approvalFilter').addEventListener('click', () => { approvalOnly = true; expanded = true; $('#workspace').classList.add('expanded'); $('#expandButton').innerHTML = '⤡ <span>收起</span>'; renderActivity(); });
$('#agentSettings').addEventListener('click', openSettings);
$('#closeDrawer').addEventListener('click', closeOverlays); $('#overlay').addEventListener('click', closeOverlays);
$('#saveSettings').addEventListener('click', () => { if (!settingsAgent) return; settingsAgent.model = $('#modelSelect').value; settingsAgent.approval = $('#approvalToggle').checked; settingsAgent.tools = [...document.querySelectorAll('[data-tool]:checked')].map((input) => input.dataset.tool); closeOverlays(); showToast(`${settingsAgent.name}的能力配置已更新`); });
$('#newAgentButton').addEventListener('click', () => { $('#createModal').hidden = false; $('#newAgentName').focus(); });
$('#closeModal').addEventListener('click', closeOverlays); $('#cancelCreate').addEventListener('click', closeOverlays); $('#confirmCreate').addEventListener('click', createAgent);
$('#createModal').addEventListener('click', (event) => { if (event.target.id === 'createModal') closeOverlays(); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeOverlays(); if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); $('#searchButton').click(); } });
$('#searchButton').addEventListener('click', () => { const name = window.prompt('搜索 Agent 或群聊'); if (!name) return; const result = [...agents, ...groups].find((item) => item.name.includes(name.trim()) || item.role.includes(name.trim())); if (result) selectConversation(result.id); else showToast('没有找到相关对话'); });
$('#attachButton').addEventListener('click', () => showToast('附件上传将在正式产品中开放'));
$('#chatMore').addEventListener('click', () => showToast('这是 FutureWork 的交互设计原型'));
renderContacts(); renderChat(); renderActivity();
