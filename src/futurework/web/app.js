/* Live Agent Team client: loads the API, submits messages, handles approvals, and refreshes activity. */
let clientConfig;
let bootstrap;
let agents = [];
let groups = [];
let activity = [];
let messages = [];
let selected = 'assistant';
let expanded = false;
let approvalOnly = false;
let settingsAgent = null;
let eventSource;
let lastSequence = 0;
let refreshTimer;
let reconnectTimer;
let toastTimer;
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
const renderMessageText = (value) => String(value ?? '').split(/(https:\/\/[^\s<>"']+|\/api\/v1\/artifacts\/(?:media|outputs)\/[A-Za-z0-9_.-]+)/g).map((part) => {
  if (!part.startsWith('https://') && !part.startsWith('/api/v1/artifacts/')) return escapeHtml(part);
  const safe = escapeHtml(part);
  const image = /\.(png|jpe?g|webp|gif)(?:\?[^\s]*)?$/i.test(part);
  const video = /\.mp4(?:\?[^\s]*)?$/i.test(part);
  return image ? `<a href="${safe}" target="_blank" rel="noopener noreferrer"><img src="${safe}" alt="生成的图片" style="max-width:100%;max-height:320px;border-radius:9px"></a>`
    : video ? `<video controls src="${safe}" style="max-width:100%;max-height:320px;border-radius:9px"></video>`
    : `<a href="${safe}" target="_blank" rel="noopener noreferrer">${safe}</a>`;
}).join('');
const itemById = (id) => [...agents, ...groups].find((item) => item.id === id);
const avatar = (item, className = '') => `<span class="avatar ${className}" style="background:${item.color};color:${item.ink}">${escapeHtml(item.icon)}</span>`;

async function api(path, options = {}) {
  const response = await fetch(`${clientConfig.apiBase}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers }
  });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try { detail = (await response.json()).detail || detail; } catch { /* use status */ }
    throw new Error(detail);
  }
  return response.json();
}

function showToast(message) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').classList.add('show');
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), clientConfig.toastDurationMs);
}

function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

async function refresh({ includeMessages = true } = {}) {
  const view = approvalOnly ? 'approvals' : expanded ? 'all' : 'recent';
  const requestedConversation = selected;
  const requests = [api('/bootstrap'), api(`/inbox?view=${view}`)];
  if (includeMessages) requests.push(api(`/conversations/${encodeURIComponent(selected)}/messages`));
  const results = await Promise.all(requests);
  bootstrap = results[0];
  agents = bootstrap.agents;
  groups = bootstrap.groups;
  activity = results[1];
  if (includeMessages && requestedConversation !== selected) return refresh();
  if (includeMessages) messages = results[2];
  renderContacts(); renderChat(); renderActivity();
  const latest = includeMessages ? messages.at(-1) : null;
  if (latest && requestedConversation !== 'assistant' && latest.from !== 'me') {
    await api(`/conversations/${encodeURIComponent(requestedConversation)}/read`, {
      method: 'POST', body: JSON.stringify({ message_id: latest.id })
    });
    const entry = activity.find((item) => item.id === requestedConversation);
    if (entry) { entry.unread = false; renderActivity(); }
  }
}

function renderContacts() {
  $('#agentCount').textContent = String(agents.length).padStart(2, '0');
  $('#groupsToggle em').textContent = String(groups.length).padStart(2, '0');
  $('#teamCount').textContent = `${agents.length} 位 Agent 正在协作`;
  $('#agentList').innerHTML = agents.map((agent) => `<button class="contact-row ${selected === agent.id ? 'selected' : ''}" data-contact="${agent.id}">${avatar(agent)}<span class="contact-copy"><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.role)}</small></span><span class="tiny-dot"></span></button>`).join('');
  $('#groupList').innerHTML = groups.map((group) => `<button class="contact-row ${selected === group.id ? 'selected' : ''}" data-contact="${group.id}">${avatar(group)}<span class="contact-copy"><strong>${escapeHtml(group.name)}</strong><small>${escapeHtml(group.role)}</small></span></button>`).join('');
  document.querySelectorAll('[data-contact]').forEach((button) => button.addEventListener('click', () => selectConversation(button.dataset.contact)));
}

function renderChat() {
  const assistant = selected === 'assistant';
  const item = itemById(selected);
  if (!assistant && !item) { selected = 'assistant'; return renderChat(); }
  $('#chatAvatar').outerHTML = assistant ? '<div class="avatar assistant-avatar" id="chatAvatar">✦</div>' : `<div class="avatar" id="chatAvatar" style="background:${item.color};color:${item.ink}">${escapeHtml(item.icon)}</div>`;
  $('#chatTitle').innerHTML = assistant ? `${escapeHtml(bootstrap.ui.assistant_name)} <span class="assistant-label">${escapeHtml(bootstrap.ui.assistant_role)}</span>` : `${escapeHtml(item.name)} <span class="assistant-label">${agents.includes(item) ? 'Agent 好友' : '协作群聊'}</span>`;
  $('#chatSubtitle').textContent = `${assistant ? '在线 · 随时为你协调团队' : item.role}${bootstrap.model_provider === 'mock' ? ' · 本地演示模式' : ''}`;
  $('#agentSettings').hidden = assistant || !agents.includes(item);
  $('#messageInput').placeholder = assistant ? `给${bootstrap.ui.assistant_name}发消息，或安排一个任务…` : `给${item.name}发消息…`;
  $('#suggestions').hidden = !assistant || messages.length > 0;
  $('#suggestions').innerHTML = bootstrap.ui.suggestions.map((prompt) => `<button data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join('');
  document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => { $('#messageInput').value = button.dataset.prompt; $('#messageForm').requestSubmit(); }));
  const welcome = assistant && !messages.length ? `<div class="day-marker">今天 · 你的团队已准备就绪</div><div class="welcome"><div class="avatar assistant-avatar">✦</div><div class="bubble"><p><strong>你好，我是${escapeHtml(bootstrap.ui.assistant_name)}。✦</strong></p><p>告诉我你想完成什么，我会匹配合适的 Agent、拆解并分派任务；需要新能力时，也会创建新的 Agent 好友。</p><p>任务分派会真实保存。模型和外部工具需单独配置，未执行的工作会明确标注。</p></div></div>` : '<div class="day-marker">对话记录</div>';
  $('#chatBody').innerHTML = welcome + messages.map((message) => {
    const own = message.from === 'me';
    const speakerAgent = agents.find((agent) => agent.name === message.speaker);
    const face = assistant ? '<div class="avatar assistant-avatar">✦</div>' : avatar(speakerAgent || item);
    const approvalCard = message.approval ? `<div class="task-card"><span class="task-card-label">待我审批</span><h4>${escapeHtml(message.approval_description)}</h4><button class="approve-action" data-approval="${message.approval_id}" data-decision="approve">批准</button><button class="approve-action" data-approval="${message.approval_id}" data-decision="reject" style="margin-left:15px;color:#a08373">拒绝</button></div>` : '';
    const taskCard = message.task_id && !own ? `<div class="task-card"><span class="task-card-label">任务已记录</span><button class="task-action" data-task="${message.task_id}">查看任务分派</button></div>` : '';
    return `<div class="message-row ${own ? 'mine' : ''}">${own ? '' : face}<div><div class="message-meta">${escapeHtml(message.speaker)} · ${formatTime(message.created_at)}</div><div class="bubble">${renderMessageText(message.text)}${approvalCard}${taskCard}</div></div></div>`;
  }).join('');
  document.querySelectorAll('.approve-action').forEach((button) => button.addEventListener('click', () => decideApproval(button.dataset.approval, button.dataset.decision)));
  document.querySelectorAll('.task-action').forEach((button) => button.addEventListener('click', () => viewTask(button.dataset.task)));
  $('#chatBody').scrollTop = $('#chatBody').scrollHeight;
}

function renderActivity() {
  $('#activityTitle').innerHTML = `${approvalOnly ? '待我审批' : '最近动态'} <span class="activity-count" id="activityCount">${String(activity.length).padStart(2, '0')}</span>`;
  $('#activityIntro').textContent = approvalOnly ? '所有需要你做决定的对话，都汇集在这里。' : expanded ? '所有 Agent 好友和群聊的消息，一屏查看。' : '团队正在处理的事，随时一眼掌握。';
  $('#activityList').innerHTML = activity.length ? activity.map((entry) => {
    const item = itemById(entry.id);
    if (!item) return '';
    return `<button class="activity-card" data-activity="${entry.id}"><div class="card-top">${avatar(item)}<span class="card-title"><strong>${escapeHtml(item.name)}${entry.unread ? '<span class="unread-dot"></span>' : ''}</strong><small>${entry.kind === 'group' ? '协作群聊' : escapeHtml(item.role)}</small></span><span class="card-time">${formatTime(entry.time)}</span></div><p>${escapeHtml(entry.text)}</p><div class="card-footer"><span>${entry.kind === 'group' ? escapeHtml(item.role) : 'Agent 好友'}</span><span class="${entry.approval_count ? 'approval-status' : 'status'}">${entry.approval_count ? '● ' : ''}${escapeHtml(entry.status)}</span></div></button>`;
  }).join('') : `<div class="empty-state">${approvalOnly ? '没有待审批事项 ✦' : '暂无对话'}</div>`;
  document.querySelectorAll('[data-activity]').forEach((button) => button.addEventListener('click', () => selectConversation(button.dataset.activity)));
  $('#allFilter').classList.toggle('active', !approvalOnly);
  $('#approvalFilter').classList.toggle('active', approvalOnly);
  $('#workspace').classList.toggle('approvals', approvalOnly);
  $('#approvalFilter .approval-badge').textContent = bootstrap.pending_approval_count;
}

async function selectConversation(id) {
  selected = id;
  $('#sidebar').classList.remove('mobile-open');
  try {
    await refresh();
  } catch (error) { showToast(error.message); }
}

async function sendMessage(event) {
  event.preventDefault();
  const field = $('#messageInput');
  const text = field.value.trim();
  if (!text) return;
  const submit = $('#messageForm .send-button');
  submit.disabled = true;
  try {
    await api(`/conversations/${encodeURIComponent(selected)}/messages`, {
      method: 'POST', body: JSON.stringify({ client_message_id: crypto.randomUUID(), body: text })
    });
    field.value = '';
    await refresh();
  } catch (error) { showToast(error.message); }
  finally { submit.disabled = false; }
}

function closeOverlays() {
  $('#settingsDrawer').classList.remove('open');
  $('#settingsDrawer').setAttribute('aria-hidden', 'true');
  $('#createModal').hidden = true;
  $('#groupModal').hidden = true;
  $('#overlay').hidden = true;
}

function openSettings() {
  const agent = agents.find((item) => item.id === selected);
  if (!agent) return;
  settingsAgent = agent;
  $('#drawerTitle').textContent = `${agent.name}的能力配置`;
  $('#drawerAgentName').textContent = agent.name;
  $('#drawerAgentRole').textContent = agent.role;
  $('#drawerAvatar').style.cssText = `background:${agent.color};color:${agent.ink}`;
  $('#drawerAvatar').textContent = agent.icon;
  $('#modelSelect').innerHTML = bootstrap.models.map((model) => `<option>${escapeHtml(model)}</option>`).join('');
  $('#modelSelect').value = agent.model;
  $('#approvalToggle').checked = agent.approval;
  $('#toolToggles').innerHTML = bootstrap.tools.map((tool) => `<label class="setting-row"><span><strong>${escapeHtml(tool)}</strong><small>记录授权意图；执行器尚未接入</small></span><input type="checkbox" data-tool="${escapeHtml(tool)}" ${agent.tools.includes(tool) ? 'checked' : ''}/><span class="switch"></span></label>`).join('');
  $('#overlay').hidden = false;
  $('#settingsDrawer').classList.add('open');
  $('#settingsDrawer').setAttribute('aria-hidden', 'false');
}

async function saveSettings() {
  if (!settingsAgent) return;
  try {
    const result = await api(`/agents/${settingsAgent.id}`, {
      method: 'PATCH', body: JSON.stringify({
        expected_version: settingsAgent.version,
        model: $('#modelSelect').value,
        tools: [...document.querySelectorAll('[data-tool]:checked')].map((input) => input.dataset.tool),
        approval: $('#approvalToggle').checked
      })
    });
    closeOverlays();
    showToast(result.status === 'pending_approval' ? '已提交权限审批；批准前不会生效' : '配置已保存');
    await refresh();
  } catch (error) { showToast(error.message); }
}

async function createAgent() {
  const name = $('#newAgentName').value.trim();
  const role = $('#newAgentRole').value.trim();
  if (!name || !role) return showToast('请填写 Agent 名称和专长');
  try {
    const agent = await api('/agents', { method: 'POST', body: JSON.stringify({ name, role }) });
    closeOverlays();
    $('#newAgentName').value = '';
    $('#newAgentRole').value = '';
    await selectConversation(agent.id);
    showToast(`${agent.name}已加入团队`);
  } catch (error) { showToast(error.message); }
}

async function createGroup() {
  const name = $('#newGroupName').value.trim();
  const memberIds = [...document.querySelectorAll('[data-group-member]:checked')].map((input) => input.dataset.groupMember);
  if (!name || !memberIds.length) return showToast('请填写群聊名称并选择成员');
  try {
    const group = await api('/groups', { method: 'POST', body: JSON.stringify({ name, member_ids: memberIds, mode: $('#groupMode').value }) });
    closeOverlays();
    $('#newGroupName').value = '';
    await selectConversation(group.id);
    showToast(`${group.name}已创建`);
  } catch (error) { showToast(error.message); }
}

async function decideApproval(approvalId, decision) {
  try {
    await api(`/approvals/${approvalId}/decision`, { method: 'POST', body: JSON.stringify({ decision }) });
    await refresh();
    showToast(decision === 'approve' ? '审批已通过' : '审批已拒绝');
  } catch (error) { showToast(error.message); await refresh(); }
}

async function viewTask(taskId) {
  try {
    const task = await api(`/tasks/${taskId}`);
    const names = task.steps.map((step) => `${step.title}：${itemById(step.agent_id)?.name || '未知 Agent'}`).join('；');
    showToast(`任务状态：${task.status}。${names}`);
  } catch (error) { showToast(error.message); }
}

function connectEvents() {
  clearTimeout(reconnectTimer);
  eventSource?.close();
  eventSource = new EventSource(`${clientConfig.apiBase}/events?after=${lastSequence}`);
  const onEvent = (event) => {
    lastSequence = Math.max(lastSequence, Number(event.lastEventId) || 0);
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => refresh().catch((error) => showToast(error.message)), clientConfig.eventRefreshMs);
  };
  for (const eventName of ['message.created', 'agent.created', 'agent.updated', 'group.created', 'approval.created', 'approval.resolved', 'task.updated', 'inbox.updated']) {
    eventSource.addEventListener(eventName, onEvent);
  }
  eventSource.onerror = () => {
    eventSource.close();
    reconnectTimer = setTimeout(connectEvents, clientConfig.eventReconnectMs);
  };
}

$('#messageForm').addEventListener('submit', sendMessage);
$('#attachButton').addEventListener('click', () => $('#imageInput').click());
$('#imageInput').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const base64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',', 2)[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const isVideo = file.type.startsWith('video/');
    const uploaded = await api(isVideo ? '/videos' : '/images', {method: 'POST', body: JSON.stringify({filename: file.name, media_type: file.type, data_base64: base64})});
    const field = $('#messageInput');
    field.value += `${field.value ? '\n' : ''}${isVideo ? '视频' : '图片'}：${uploaded.path}。请使用 ${isVideo ? 'video_analyze' : 'image_analyze'} 工具分析。`;
    field.focus();
  } catch (error) { showToast(error.message); }
  finally { event.target.value = ''; }
});
$('#messageInput').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#messageForm').requestSubmit(); } });
$('#homeButton').addEventListener('click', () => selectConversation('assistant'));
$('#railAgents').addEventListener('click', () => { $('#sidebar').classList.remove('collapsed'); $('#sidebar').classList.add('mobile-open'); $('#agentsToggle').setAttribute('aria-expanded', 'true'); $('#agentList').classList.remove('collapsed'); });
$('#railGroups').addEventListener('click', () => { $('#sidebar').classList.remove('collapsed'); $('#sidebar').classList.add('mobile-open'); $('#groupsToggle').setAttribute('aria-expanded', 'true'); $('#groupList').classList.remove('collapsed'); });
$('#collapseSidebar').addEventListener('click', () => { $('#sidebar').classList.toggle('collapsed'); $('#sidebar').classList.remove('mobile-open'); });
$('#mobileMenu').addEventListener('click', () => { $('#sidebar').classList.remove('collapsed'); $('#sidebar').classList.toggle('mobile-open'); });
for (const id of ['agents', 'groups']) {
  $(`#${id}Toggle`).addEventListener('click', () => {
    const button = $(`#${id}Toggle`);
    const open = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!open));
    $(`#${id === 'agents' ? 'agentList' : 'groupList'}`).classList.toggle('collapsed', open);
  });
}
$('#expandButton').addEventListener('click', async () => {
  expanded = !expanded;
  $('#workspace').classList.toggle('expanded', expanded);
  $('#expandButton').innerHTML = expanded ? '⤡ <span>收起</span>' : '⤢ <span>展开</span>';
  $('#expandButton').setAttribute('aria-label', expanded ? '收起所有对话' : '展开所有对话');
  try { await refresh({ includeMessages: false }); } catch (error) { showToast(error.message); }
});
$('#mobileActivityButton').addEventListener('click', () => $('#expandButton').click());
$('#allFilter').addEventListener('click', async () => { approvalOnly = false; try { await refresh({ includeMessages: false }); } catch (error) { showToast(error.message); } });
$('#approvalFilter').addEventListener('click', async () => {
  approvalOnly = true; expanded = true;
  $('#workspace').classList.add('expanded');
  $('#expandButton').innerHTML = '⤡ <span>收起</span>';
  try { await refresh({ includeMessages: false }); } catch (error) { showToast(error.message); }
});
$('#agentSettings').addEventListener('click', openSettings);
$('#closeDrawer').addEventListener('click', closeOverlays);
$('#overlay').addEventListener('click', closeOverlays);
$('#saveSettings').addEventListener('click', saveSettings);
$('#newAgentButton').addEventListener('click', () => { $('#createModal').hidden = false; $('#newAgentName').focus(); });
$('#newGroupButton').addEventListener('click', () => {
  $('#groupMemberList').innerHTML = agents.map((agent) => `<label class="setting-row"><span><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.role)}</small></span><input type="checkbox" data-group-member="${agent.id}"/><span class="switch"></span></label>`).join('');
  $('#groupModal').hidden = false;
  $('#newGroupName').focus();
});
$('#closeModal').addEventListener('click', closeOverlays);
$('#cancelCreate').addEventListener('click', closeOverlays);
$('#confirmCreate').addEventListener('click', createAgent);
$('#closeGroupModal').addEventListener('click', closeOverlays);
$('#cancelGroupCreate').addEventListener('click', closeOverlays);
$('#confirmGroupCreate').addEventListener('click', createGroup);
$('#createModal').addEventListener('click', (event) => { if (event.target.id === 'createModal') closeOverlays(); });
$('#groupModal').addEventListener('click', (event) => { if (event.target.id === 'groupModal') closeOverlays(); });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeOverlays();
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); $('#searchButton').click(); }
});
$('#searchButton').addEventListener('click', () => {
  const name = window.prompt('搜索 Agent 或群聊');
  if (!name) return;
  const found = [...agents, ...groups].find((item) => item.name.includes(name.trim()) || item.role.includes(name.trim()));
  if (found) selectConversation(found.id); else showToast('没有找到相关对话');
});
$('#attachButton').addEventListener('click', () => showToast('附件功能尚未接入'));
$('#chatMore').addEventListener('click', () => showToast(`当前模型模式：${bootstrap.model_provider}`));

(async () => {
  try {
    clientConfig = await (await fetch('/config.json')).json();
    await refresh();
    connectEvents();
  } catch (error) { $('#chatBody').innerHTML = `<div class="empty-state">无法连接后端：${escapeHtml(error.message)}</div>`; }
})();
