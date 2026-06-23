// ============================= NOVA APP v2 — All Phases =============================
// Phase 1: Bug fixes (markdown rendering, no duplicate turn, etc.)
// Phase 3: Confirmation modal, PDF attach in chat, new tool icons
// Phase 4: PDF upload to /api/upload, documents list
// Phase 5: Workflow support, WebSocket live updates
// Phase 6: Scheduled tasks in Automations view
(function () {
  'use strict';

  const API = '';

  // ── Configure marked.js for safe markdown ──────────────────────────────────
  if (typeof marked !== 'undefined') {
    marked.setOptions({
      breaks: true,         // newlines become <br>
      gfm: true,            // GitHub-flavored markdown
    });
  }

  function renderMarkdown(text) {
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
      const html = marked.parse(text);
      return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
    }
    // Fallback: basic escaping if CDN failed to load
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const navItems       = document.querySelectorAll('.nav-item');
  const views          = document.querySelectorAll('.view');
  const thread         = document.getElementById('thread');
  const textInput      = document.getElementById('text-input');
  const sendBtn        = document.getElementById('send-btn');
  const micBtn         = document.getElementById('mic-btn');
  const toggleActivity = document.getElementById('toggle-activity');
  const activityDrawer = document.getElementById('activity');
  const convItems      = document.querySelectorAll('.conv-item');
  const toastContainer = document.getElementById('toast-container');
  const settingsBtn    = document.getElementById('settings-btn');
  const settingsModal  = document.getElementById('settings-modal');
  const modalClose     = document.getElementById('modal-close');
  const memSearch      = document.getElementById('mem-search');
  const mobileToggle   = document.getElementById('mobile-toggle');
  const rail           = document.querySelector('.rail');
  const dropzone       = document.getElementById('dropzone');
  const turnCount      = document.getElementById('turn-count');
  const memoryList     = document.getElementById('memory-list');
  const remindersList  = document.getElementById('reminders-list');
  const traceContainer = document.getElementById('trace-container');
  const settingVoice   = document.getElementById('setting-voice');
  const attachBtn      = document.getElementById('attach-btn');
  const pdfFileInput   = document.getElementById('pdf-file-input');
  const docFileInput   = document.getElementById('doc-file-input');
  const browseDocsBtn  = document.getElementById('browse-docs-btn');
  const docsList       = document.getElementById('documents-list');
  const tasksList      = document.getElementById('tasks-list');
  const confirmModal   = document.getElementById('confirm-modal');
  const confirmTitle   = document.getElementById('confirm-title');
  const confirmDesc    = document.getElementById('confirm-description');
  const confirmApprove = document.getElementById('confirm-approve-btn');
  const confirmDeny    = document.getElementById('confirm-deny-btn');

  let currentTurn = 0;
  let isSending = false;
  let pendingConfirmRequestId = null;
  let pendingConfirmResolve = null;

  // ============================= VIEW SWITCHING =============================
  navItems.forEach(btn => {
    btn.addEventListener('click', () => {
      navItems.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const target = btn.dataset.view;
      views.forEach(v => {
        v.classList.remove('active');
        if (v.id === 'view-' + target) {
          requestAnimationFrame(() => v.classList.add('active'));
        }
      });
      if (target === 'memory') loadMemory();
      if (target === 'automations') { loadReminders(); loadTasks(); }
      if (target === 'documents') loadDocuments();
      if (rail) rail.classList.remove('open');
    });
  });

  // ============================= CONVERSATION LIST =============================
  convItems.forEach(btn => {
    btn.addEventListener('click', () => {
      convItems.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });

  // ============================= ACTIVITY DRAWER =============================
  if (toggleActivity && activityDrawer) {
    toggleActivity.addEventListener('click', () => {
      activityDrawer.classList.toggle('open');
    });
  }

  // ============================= MOBILE SIDEBAR =============================
  if (mobileToggle && rail) {
    mobileToggle.addEventListener('click', () => {
      rail.classList.toggle('open');
    });
    document.addEventListener('click', (e) => {
      if (rail.classList.contains('open') && !rail.contains(e.target) && e.target !== mobileToggle) {
        rail.classList.remove('open');
      }
    });
  }

  // ============================= HELPERS =============================
  let voiceEnabled = localStorage.getItem('nova_voice_responses') !== 'false';
  if (settingVoice) {
    settingVoice.checked = voiceEnabled;
    settingVoice.addEventListener('change', () => {
      voiceEnabled = settingVoice.checked;
      localStorage.setItem('nova_voice_responses', voiceEnabled);
      if (!voiceEnabled && 'speechSynthesis' in window) window.speechSynthesis.cancel();
    });
  }

  function speakText(text) {
    if (!voiceEnabled || !('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const cleanText = text.replace(/<[^>]*>/g, '').replace(/[*_`#]/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    const utterance = new SpeechSynthesisUtterance(cleanText);
    const voices = window.speechSynthesis.getVoices();
    const enVoice = voices.find(v => v.lang.startsWith('en-') && v.name.toLowerCase().includes('google'))
                 || voices.find(v => v.lang.startsWith('en-') && v.name.toLowerCase().includes('natural'))
                 || voices.find(v => v.lang.startsWith('en-'));
    if (enVoice) utterance.voice = enVoice;
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    window.speechSynthesis.speak(utterance);
  }

  function getCurrentTime() {
    return new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function scrollToBottom() {
    if (thread) thread.scrollTo({ top: thread.scrollHeight, behavior: 'smooth' });
  }

  // ============================= COPY TO CLIPBOARD =============================
  function createCopyButton() {
    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.title = 'Copy to clipboard';
    btn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
      </svg>
      <span class="copy-tooltip">Copied!</span>
    `;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const msg = btn.closest('.msg');
      const bubble = msg ? msg.querySelector('.bubble') : null;
      if (!bubble) return;
      const text = bubble.innerText.trim();
      navigator.clipboard.writeText(text).then(() => {
        btn.classList.add('copied');
        btn.querySelector('svg').innerHTML = `<polyline points="20 6 9 17 4 12"/>`;
        showToast('Copied to clipboard', 'success');
        setTimeout(() => {
          btn.classList.remove('copied');
          btn.querySelector('svg').innerHTML = `<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>`;
        }, 2000);
      }).catch(() => showToast('Failed to copy', 'error'));
    });
    return btn;
  }

  // ============================= TOAST NOTIFICATIONS =============================
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = 'toast';
    const iconSvgs = {
      success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>',
      info:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
      error:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>'
    };
    toast.innerHTML = `
      <span class="toast-icon ${type}">${iconSvgs[type] || iconSvgs.info}</span>
      <span>${escapeHtml(message)}</span>
    `;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('leaving');
      toast.addEventListener('animationend', () => toast.remove());
    }, 3000);
  }

  // ============================= TYPING INDICATOR =============================
  function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.className = 'msg from-nova';
    indicator.id = 'typing-indicator';
    indicator.innerHTML = `
      <div class="msg-meta">Nova</div>
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    `;
    thread.appendChild(indicator);
    scrollToBottom();
  }

  function removeTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) indicator.remove();
  }

  // ============================= TOOL CHIP BUILDER =============================
  const TOOL_ICONS = {
    web_search:              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="6"/><path d="M20 20l-3.5-3.5"/></svg>',
    browser_search_web:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="6"/><path d="M20 20l-3.5-3.5"/></svg>',
    get_weather:             '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>',
    get_current_datetime:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="13" r="7"/><path d="M12 9v4l2.5 1.5"/></svg>',
    set_reminder:            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="13" r="7"/><path d="M12 9v4l2.5 1.5M9.6 3.4h4.8"/></svg>',
    browser_navigate:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="14" rx="2"/><path d="M7 21h10M12 17v4"/></svg>',
    browser_extract_text:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="14" rx="2"/><path d="M7 21h10M12 17v4"/></svg>',
    browser_search_and_book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="14" rx="2"/><path d="M7 21h10M12 17v4"/></svg>',
    draft_email:             '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>',
    send_email:              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>',
    get_drafts:              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>',
    create_calendar_event:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    list_calendar_events:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    delete_calendar_event:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    search_documents:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v4h4M9 12h6M9 15.5h6"/></svg>',
    list_documents:          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v4h4M9 12h6M9 15.5h6"/></svg>',
    schedule_task:           '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    list_scheduled_tasks:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    cancel_task:             '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
  };

  function buildToolChips(toolsUsed) {
    if (!toolsUsed || toolsUsed.length === 0) return '';
    const chips = toolsUsed.map(name => {
      const icon = TOOL_ICONS[name] || TOOL_ICONS.web_search;
      const label = name.replace(/_/g, ' ');
      return `<span class="tool-chip">${icon}${escapeHtml(label)}</span>`;
    }).join('');
    return `<div class="tool-row">${chips}</div>`;
  }

  // ============================= TRACE BUILDER =============================
  function addTraceStep(label, dotClass = '') {
    if (!traceContainer) return;
    const step = document.createElement('div');
    step.className = 'trace-step';
    const now = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    step.innerHTML = `
      <div class="trace-dot ${dotClass}"></div>
      <div class="trace-text"><span class="t-label">${escapeHtml(label)}</span><span class="t-time">${now}</span></div>
    `;
    traceContainer.appendChild(step);
  }

  function clearTrace() {
    if (traceContainer) traceContainer.innerHTML = '';
  }

  // ============================= WEBSOCKET (live updates) =============================
  let ws = null;

  function connectWebSocket() {
    const wsUrl = `ws://${location.host}/ws`;
    ws = new WebSocket(wsUrl);

    ws.addEventListener('message', (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'confirmation_required') {
          handleConfirmationRequired(data);
        } else if (data.type === 'reminder') {
          showToast(`⏰ Reminder: ${data.message}`, 'info');
          addTraceStep(`Reminder: ${data.message}`, 'amber');
        } else if (data.type === 'pong') {
          // keepalive ok
        }
      } catch (e) {}
    });

    ws.addEventListener('close', () => {
      // Reconnect after 3 seconds
      setTimeout(connectWebSocket, 3000);
    });

    ws.addEventListener('error', () => {
      ws.close();
    });

    // Keepalive ping every 25s
    setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 25000);
  }

  // ============================= CONFIRMATION MODAL =============================
  function handleConfirmationRequired(data) {
    pendingConfirmRequestId = data.request_id;
    if (confirmTitle) confirmTitle.textContent = `Confirm: ${data.tool_name.replace(/_/g, ' ')}`;
    if (confirmDesc) confirmDesc.textContent = `Nova wants to: ${data.description}`;
    if (confirmModal) {
      confirmModal.style.display = 'flex';
      confirmModal.classList.add('open');
    }
    addTraceStep(`awaiting confirmation: ${data.tool_name}`, 'amber');
  }

  async function sendConfirmation(confirmed) {
    if (!pendingConfirmRequestId) return;
    const reqId = pendingConfirmRequestId;
    pendingConfirmRequestId = null;

    if (confirmModal) {
      confirmModal.style.display = 'none';
      confirmModal.classList.remove('open');
    }

    try {
      await fetch(`${API}/api/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: reqId, confirmed }),
      });
      addTraceStep(confirmed ? 'action approved by user' : 'action denied by user', confirmed ? '' : 'rose');
    } catch (e) {
      console.error('Confirm API error:', e);
    }
  }

  if (confirmApprove) confirmApprove.addEventListener('click', () => sendConfirmation(true));
  if (confirmDeny)    confirmDeny.addEventListener('click',    () => sendConfirmation(false));

  // Close confirm modal on overlay click
  if (confirmModal) {
    confirmModal.addEventListener('click', (e) => {
      if (e.target === confirmModal) sendConfirmation(false);
    });
  }

  // ============================= SEND MESSAGE (REAL API) =============================
  async function sendMessage() {
    const text = textInput.value.trim();
    if (!text || isSending) return;

    isSending = true;
    currentTurn++;
    if (turnCount) turnCount.textContent = currentTurn;

    const userMsg = document.createElement('div');
    userMsg.className = 'msg from-user';
    userMsg.innerHTML = `
      <div class="msg-meta">${getCurrentTime()}</div>
      <div class="bubble">${escapeHtml(text)}</div>
    `;
    userMsg.appendChild(createCopyButton());
    thread.appendChild(userMsg);
    scrollToBottom();

    textInput.value = '';
    sendBtn.disabled = true;

    setTimeout(() => showTypingIndicator(), 200);
    clearTrace();
    addTraceStep('assemble context');

    try {
      addTraceStep('llm → reasoning', 'amber');

      const res = await fetch(`${API}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });

      removeTypingIndicator();

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Server error' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();

      currentTurn = data.turn;
      if (turnCount) turnCount.textContent = currentTurn;

      if (data.tools_used && data.tools_used.length > 0) {
        data.tools_used.forEach(tool => addTraceStep(`tool: ${tool.replace(/_/g, ' ')}`, 'amber'));
      }
      addTraceStep('goal met → reply composed');

      const novaMsg = document.createElement('div');
      novaMsg.className = 'msg from-nova';
      const toolChips = buildToolChips(data.tools_used);
      // BUG FIX #3: render markdown instead of escapeHtml
      novaMsg.innerHTML = `
        <div class="msg-meta">Nova · ${getCurrentTime()}</div>
        <div class="bubble markdown-body">
          ${toolChips}
          ${renderMarkdown(data.response)}
        </div>
      `;
      novaMsg.appendChild(createCopyButton());
      thread.appendChild(novaMsg);
      scrollToBottom();
      speakText(data.response);

    } catch (err) {
      removeTypingIndicator();
      addTraceStep(`error: ${err.message}`, 'rose');
      const errorMsg = document.createElement('div');
      errorMsg.className = 'msg from-nova';
      errorMsg.innerHTML = `
        <div class="msg-meta">Nova · ${getCurrentTime()}</div>
        <div class="bubble" style="color: var(--rose);">
          Sorry, something went wrong: ${escapeHtml(err.message)}
        </div>
      `;
      thread.appendChild(errorMsg);
      scrollToBottom();
      showToast(`Error: ${err.message}`, 'error');
    } finally {
      isSending = false;
      if (textInput) sendBtn.disabled = textInput.value.trim().length === 0;
    }
  }

  // ============================= LOAD CONVERSATION HISTORY =============================
  async function loadHistory() {
    try {
      const res = await fetch(`${API}/api/history`);
      if (!res.ok) { showWelcomeMessage(); return; }
      const data = await res.json();

      currentTurn = data.turn;
      if (turnCount) turnCount.textContent = currentTurn;
      thread.innerHTML = '';

      for (const msg of data.messages) {
        const div = document.createElement('div');
        if (msg.role === 'user') {
          div.className = 'msg from-user';
          div.innerHTML = `<div class="msg-meta">${getCurrentTime()}</div><div class="bubble">${escapeHtml(msg.content)}</div>`;
        } else {
          div.className = 'msg from-nova';
          div.innerHTML = `<div class="msg-meta">Nova</div><div class="bubble markdown-body">${renderMarkdown(msg.content)}</div>`;
        }
        div.appendChild(createCopyButton());
        thread.appendChild(div);
      }

      if (data.messages.length === 0) showWelcomeMessage();
      scrollToBottom();
    } catch (e) {
      showWelcomeMessage();
    }
  }

  function showWelcomeMessage() {
    thread.innerHTML = `
      <div class="empty-state">
        <div class="orb-wrap"><div class="orb-ring"></div><div class="orb"></div></div>
        <h3>Good ${getGreetingTime()}, I'm Nova</h3>
        <p>Type a message or tap the mic to get started.<br>I can search the web, book tickets, send emails, search PDFs, set reminders, and more.</p>
        <div class="capability-chips">
          <span class="cap-chip">🌐 Web search</span>
          <span class="cap-chip">✈️ Ticket booking</span>
          <span class="cap-chip">📧 Email</span>
          <span class="cap-chip">📄 PDF analysis</span>
          <span class="cap-chip">⏰ Reminders</span>
          <span class="cap-chip">📅 Calendar</span>
          <span class="cap-chip">🤖 Multi-agent</span>
        </div>
      </div>
    `;
  }

  function getGreetingTime() {
    const hour = new Date().getHours();
    if (hour < 12) return 'morning';
    if (hour < 17) return 'afternoon';
    return 'evening';
  }

  // ============================= LOAD MEMORY =============================
  async function loadMemory() {
    if (!memoryList) return;
    try {
      const res = await fetch(`${API}/api/memory`);
      if (!res.ok) return;
      const data = await res.json();
      memoryList.innerHTML = '';

      if (data.facts.length === 0) {
        memoryList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px; padding: 10px;">No memories stored yet. Chat with Nova to build up context.</p>';
        return;
      }

      const groupDiv = document.createElement('div');
      groupDiv.className = 'mem-group';
      groupDiv.innerHTML = `<div class="mem-group-title">Known Facts</div>`;

      data.facts.forEach((item) => {
        const memItem = document.createElement('div');
        memItem.className = 'mem-item';
        memItem.dataset.index = item.index;
        memItem.innerHTML = `
          <div class="mem-item-text">${escapeHtml(item.fact)}<span>Extracted from conversations</span></div>
          <button class="mem-forget" title="Forget this"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
        `;
        memItem.querySelector('.mem-forget').addEventListener('click', () => deleteMemory(item.index, memItem));
        groupDiv.appendChild(memItem);
      });
      memoryList.appendChild(groupDiv);
    } catch (e) {
      console.error('Failed to load memory:', e);
    }
  }

  async function deleteMemory(index, element) {
    try {
      const res = await fetch(`${API}/api/memory/${index}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Delete failed');
      element.classList.add('removing');
      element.addEventListener('animationend', () => { element.remove(); showToast('Memory forgotten', 'success'); loadMemory(); });
    } catch (e) {
      showToast('Failed to delete memory', 'error');
    }
  }

  const clearAllBtn = document.getElementById('clear-all-memory');
  if (clearAllBtn) {
    clearAllBtn.addEventListener('click', async () => {
      try {
        const res = await fetch(`${API}/api/memory`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Clear failed');
        showToast('All memories cleared', 'success');
        loadMemory();
      } catch (e) {
        showToast('Failed to clear memory', 'error');
      }
    });
  }

  // ============================= LOAD REMINDERS =============================
  async function loadReminders() {
    if (!remindersList) return;
    try {
      const res = await fetch(`${API}/api/reminders`);
      if (!res.ok) return;
      const data = await res.json();
      remindersList.innerHTML = '';

      if (data.reminders.length === 0) {
        remindersList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px; padding: 10px;">No reminders set. Ask Nova to set one via chat.</p>';
        return;
      }

      data.reminders.forEach((r) => {
        const row = document.createElement('div');
        row.className = 'auto-row';
        let timeStr = '';
        try {
          const dt = new Date(r.time);
          timeStr = dt.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
        } catch (e) { timeStr = r.time; }
        const statusClass = r.done ? 'ok' : 'warn';
        const statusText = r.done ? 'completed' : 'pending';
        row.innerHTML = `
          <div class="auto-row-top">
            <div>
              <div class="auto-name">${escapeHtml(r.message)}</div>
              <div class="auto-schedule">${escapeHtml(timeStr)}</div>
            </div>
            <div class="auto-right">
              <span class="status-chip ${statusClass}"><span class="dot"></span>${statusText}</span>
            </div>
          </div>
        `;
        remindersList.appendChild(row);
      });
    } catch (e) {
      console.error('Failed to load reminders:', e);
    }
  }

  // ============================= LOAD SCHEDULED TASKS =============================
  async function loadTasks() {
    if (!tasksList) return;
    try {
      const res = await fetch(`${API}/api/tasks`);
      if (!res.ok) { tasksList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px; padding: 10px;">Scheduler not available (install apscheduler).</p>'; return; }
      const data = await res.json();

      if (!data.available) {
        tasksList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px; padding: 10px;">Scheduler not available. Run: pip install apscheduler</p>';
        return;
      }

      if (!data.tasks || data.tasks.length === 0) {
        tasksList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px; padding: 10px;">No background tasks scheduled. Ask Nova to schedule one.</p>';
        return;
      }

      tasksList.innerHTML = '';
      data.tasks.forEach((t) => {
        const row = document.createElement('div');
        row.className = 'auto-row';
        const statusClass = t.status === 'scheduled' ? 'ok' : t.status === 'completed' ? '' : 'warn';
        row.innerHTML = `
          <div class="auto-row-top">
            <div>
              <div class="auto-name">${escapeHtml(t.name)}</div>
              <div class="auto-schedule">${escapeHtml(t.trigger)} · runs: ${t.run_count || 0}x · ${t.last_run ? 'last: ' + new Date(t.last_run).toLocaleString() : 'never run'}</div>
            </div>
            <div class="auto-right">
              <span class="status-chip ${statusClass}"><span class="dot"></span>${escapeHtml(t.status)}</span>
              <button class="mem-forget" title="Cancel task" data-task-id="${escapeHtml(t.task_id)}" style="margin-left:6px;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6 6 18"/></svg>
              </button>
            </div>
          </div>
        `;
        row.querySelector('.mem-forget').addEventListener('click', async (e) => {
          const tid = e.currentTarget.dataset.taskId;
          try {
            await fetch(`${API}/api/tasks/${tid}`, { method: 'DELETE' });
            showToast('Task cancelled', 'success');
            loadTasks();
          } catch (err) { showToast('Failed to cancel task', 'error'); }
        });
        tasksList.appendChild(row);
      });
    } catch (e) {
      if (tasksList) tasksList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px; padding: 10px;">Could not load tasks.</p>';
    }
  }

  // ============================= LOAD DOCUMENTS (RAG) =============================
  async function loadDocuments() {
    if (!docsList) return;
    try {
      const res = await fetch(`${API}/api/documents`);
      if (!res.ok) { docsList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px;">RAG not available. Install: chromadb sentence-transformers pymupdf</p>'; return; }
      const data = await res.json();

      if (!data.available) {
        docsList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px;">RAG not available. Run: pip install chromadb sentence-transformers pymupdf</p>';
        return;
      }

      if (!data.documents || data.documents.length === 0) {
        docsList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px; text-align:center;">No documents indexed yet. Drop a PDF above.</p>';
        return;
      }

      docsList.innerHTML = '<div class="mem-group-title" style="margin-bottom:8px;">Indexed Documents</div>';
      data.documents.forEach((doc) => {
        const row = document.createElement('div');
        row.className = 'auto-row';
        const date = doc.indexed_at ? new Date(doc.indexed_at).toLocaleDateString() : '';
        row.innerHTML = `
          <div class="auto-row-top">
            <div>
              <div class="auto-name">📄 ${escapeHtml(doc.filename)}</div>
              <div class="auto-schedule">${doc.chunk_count || 0} chunks indexed · ${date}</div>
            </div>
            <div class="auto-right">
              <span class="status-chip ok"><span class="dot"></span>indexed</span>
              <button class="mem-forget" title="Remove document" data-doc-id="${escapeHtml(doc.doc_id)}" style="margin-left:6px;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6 6 18"/></svg>
              </button>
            </div>
          </div>
        `;
        row.querySelector('.mem-forget').addEventListener('click', async (e) => {
          const did = e.currentTarget.dataset.docId;
          try {
            await fetch(`${API}/api/documents/${did}`, { method: 'DELETE' });
            showToast('Document removed', 'success');
            loadDocuments();
          } catch (err) { showToast('Failed to remove document', 'error'); }
        });
        docsList.appendChild(row);
      });
    } catch (e) {
      if (docsList) docsList.innerHTML = '<p style="color: var(--mist-dim); font-size: 13px;">Could not load documents.</p>';
    }
  }

  // ============================= PDF UPLOAD =============================
  async function uploadPDF(file, notifyInChat = false) {
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
      showToast('Only PDF files are supported', 'error');
      return;
    }

    const progressEl = document.getElementById('upload-progress');
    if (progressEl) { progressEl.style.display = 'block'; progressEl.textContent = `Uploading ${file.name}…`; }
    showToast(`Uploading ${file.name}…`, 'info');

    const formData = new FormData();
    formData.append('file', file, file.name);

    try {
      const res = await fetch(`${API}/api/upload`, { method: 'POST', body: formData });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      showToast(`✅ "${data.filename}" indexed — ${data.chunks} chunks`, 'success');
      if (progressEl) { progressEl.textContent = `✅ Indexed: ${data.filename} (${data.chunks} chunks)`; }

      if (notifyInChat && thread) {
        const msg = document.createElement('div');
        msg.className = 'msg from-nova';
        msg.innerHTML = `
          <div class="msg-meta">Nova · ${getCurrentTime()}</div>
          <div class="bubble markdown-body">
            📄 <strong>${escapeHtml(data.filename)}</strong> has been indexed (${data.chunks} chunks). You can now ask me questions about it!
          </div>
        `;
        thread.appendChild(msg);
        scrollToBottom();
      }

      // Reload documents list if on that view
      loadDocuments();
    } catch (err) {
      showToast(`Upload failed: ${err.message}`, 'error');
      if (progressEl) { progressEl.textContent = `❌ Upload failed: ${err.message}`; }
    }
  }

  // ── Attach button in chat composer (quick PDF attach) ──────────────────────
  if (attachBtn && pdfFileInput) {
    attachBtn.addEventListener('click', () => pdfFileInput.click());
    pdfFileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (file) uploadPDF(file, true);
      pdfFileInput.value = '';
    });
  }

  // ── Browse button in Documents view ───────────────────────────────────────
  if (browseDocsBtn && docFileInput) {
    browseDocsBtn.addEventListener('click', () => docFileInput.click());
    docFileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (file) uploadPDF(file, false);
      docFileInput.value = '';
    });
  }

  // ── Dropzone in Documents view ─────────────────────────────────────────────
  if (dropzone) {
    ['dragenter', 'dragover'].forEach(evt => {
      dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(evt => {
      dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.remove('dragover'); });
    });
    dropzone.addEventListener('drop', (e) => {
      const files = Array.from(e.dataTransfer.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
      if (files.length === 0) { showToast('Only PDF files are supported', 'error'); return; }
      files.forEach(f => uploadPDF(f, false));
    });
  }

  // ============================= MEMORY SEARCH =============================
  if (memSearch) {
    memSearch.addEventListener('input', () => {
      const query = memSearch.value.toLowerCase();
      document.querySelectorAll('.mem-item').forEach(item => {
        const text = item.querySelector('.mem-item-text').textContent.toLowerCase();
        item.style.display = text.includes(query) ? 'flex' : 'none';
      });
    });
  }

  // ============================= COMPOSER EVENTS =============================
  if (textInput) {
    textInput.addEventListener('input', () => { sendBtn.disabled = textInput.value.trim().length === 0; });
    textInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
  }
  if (sendBtn) sendBtn.addEventListener('click', sendMessage);

  // ============================= WAV AUDIO RECORDER =============================
  class WAVRecorder {
    constructor() {
      this.audioContext = null;
      this.processor = null;
      this.source = null;
      this.stream = null;
      this.samples = [];
    }

    async start() {
      this.samples = [];
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { autoGainControl: true, echoCancellation: true, noiseSuppression: true }
      });
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioContextClass();
      if (this.audioContext.state === 'suspended') await this.audioContext.resume();
      this.source = this.audioContext.createMediaStreamSource(this.stream);
      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = (e) => {
        this.samples.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      this.source.connect(this.processor);
      this.processor.connect(this.audioContext.destination);
    }

    stop() {
      return new Promise((resolve) => {
        if (this.processor) { this.processor.disconnect(); this.processor.onaudioprocess = null; this.processor = null; }
        if (this.source) { this.source.disconnect(); this.source = null; }
        const actualSampleRate = this.audioContext ? this.audioContext.sampleRate : 44100;
        if (this.audioContext) { this.audioContext.close(); this.audioContext = null; }
        if (this.stream) { this.stream.getTracks().forEach(t => t.stop()); this.stream = null; }
        const flattened = this.flattenSamples();
        let maxVal = 0;
        for (let i = 0; i < flattened.length; i++) {
          const val = Math.abs(flattened[i]);
          if (val > maxVal) maxVal = val;
        }
        const wavBlob = this.encodeWAV(flattened, actualSampleRate);
        resolve({ blob: wavBlob, peak: maxVal, length: flattened.length, sampleRate: actualSampleRate });
      });
    }

    flattenSamples() {
      let totalLength = 0;
      for (const s of this.samples) totalLength += s.length;
      const result = new Float32Array(totalLength);
      let offset = 0;
      for (const s of this.samples) { result.set(s, offset); offset += s.length; }
      return result;
    }

    encodeWAV(samples, sampleRate) {
      const buffer = new ArrayBuffer(44 + samples.length * 2);
      const view = new DataView(buffer);
      this.writeString(view, 0, 'RIFF');
      view.setUint32(4, 36 + samples.length * 2, true);
      this.writeString(view, 8, 'WAVE');
      this.writeString(view, 12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      this.writeString(view, 36, 'data');
      view.setUint32(40, samples.length * 2, true);
      this.floatTo16BitPCM(view, 44, samples);
      return new Blob([view], { type: 'audio/wav' });
    }

    floatTo16BitPCM(output, offset, input) {
      for (let i = 0; i < input.length; i++, offset += 2) {
        let s = Math.max(-1, Math.min(1, input[i]));
        output.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      }
    }

    writeString(view, offset, string) {
      for (let i = 0; i < string.length; i++) view.setUint8(offset + i, string.charCodeAt(i));
    }
  }

  const wavRecorder = new WAVRecorder();

  async function startRecording() {
    try {
      await wavRecorder.start();
      micBtn.classList.add('recording');
      showToast('Listening… tap mic again to stop', 'info');
    } catch (err) {
      showToast('Could not access microphone: ' + err.message, 'error');
      micBtn.classList.remove('recording');
    }
  }

  async function stopRecording() {
    micBtn.classList.remove('recording');
    try {
      const result = await wavRecorder.stop();
      const duration = result.length / result.sampleRate;
      if (result.peak < 0.015 || duration < 0.4) {
        showToast("Didn't catch that — try speaking closer to the mic", 'info');
        return;
      }
      await sendAudioMessage(result.blob);
    } catch (err) {
      showToast('Error saving audio', 'error');
    }
  }

  async function sendAudioMessage(audioBlob) {
    if (isSending) return;
    isSending = true;
    currentTurn++;
    if (turnCount) turnCount.textContent = currentTurn;

    const userMsg = document.createElement('div');
    userMsg.className = 'msg from-user';
    userMsg.id = 'voice-pending-msg';
    userMsg.innerHTML = `
      <div class="msg-meta">${getCurrentTime()} <span class="mic-chip"><svg viewBox="0 0 24 24" fill="currentColor" style="width:10px;height:10px;display:inline-block;margin-right:2px;"><path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11Z"/></svg>voice</span></div>
      <div class="bubble" style="font-style: italic; color: var(--mist);">🎙️ Transcribing audio...</div>
    `;
    userMsg.appendChild(createCopyButton());
    thread.appendChild(userMsg);
    scrollToBottom();

    setTimeout(() => showTypingIndicator(), 200);
    clearTrace();
    addTraceStep('assemble context');

    try {
      addTraceStep('upload audio & transcribe', 'amber');
      const formData = new FormData();
      formData.append('file', audioBlob, 'query.wav');
      const res = await fetch(`${API}/api/voice`, { method: 'POST', body: formData });
      removeTypingIndicator();

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Server error during transcription' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      const bubble = userMsg.querySelector('.bubble');
      if (bubble) { bubble.textContent = data.transcript; bubble.style.fontStyle = 'normal'; bubble.style.color = ''; }
      userMsg.removeAttribute('id');

      currentTurn = data.turn;
      if (turnCount) turnCount.textContent = currentTurn;
      if (data.tools_used && data.tools_used.length > 0) {
        data.tools_used.forEach(tool => addTraceStep(`tool: ${tool.replace(/_/g, ' ')}`, 'amber'));
      }
      addTraceStep('goal met → reply composed');

      const novaMsg = document.createElement('div');
      novaMsg.className = 'msg from-nova';
      novaMsg.innerHTML = `
        <div class="msg-meta">Nova · ${getCurrentTime()}</div>
        <div class="bubble markdown-body">
          ${buildToolChips(data.tools_used)}
          ${renderMarkdown(data.response)}
        </div>
      `;
      novaMsg.appendChild(createCopyButton());
      thread.appendChild(novaMsg);
      scrollToBottom();
      speakText(data.response);

    } catch (err) {
      removeTypingIndicator();
      addTraceStep(`error: ${err.message}`, 'rose');
      const bubble = userMsg.querySelector('.bubble');
      if (bubble) { bubble.textContent = '🎙️ Transcription failed'; bubble.style.color = 'var(--rose)'; }
      const errorMsg = document.createElement('div');
      errorMsg.className = 'msg from-nova';
      errorMsg.innerHTML = `
        <div class="msg-meta">Nova · ${getCurrentTime()}</div>
        <div class="bubble" style="color: var(--rose);">Sorry, I encountered an error: ${escapeHtml(err.message)}</div>
      `;
      thread.appendChild(errorMsg);
      scrollToBottom();
      showToast(`Voice Error: ${err.message}`, 'error');
    } finally {
      isSending = false;
    }
  }

  if (micBtn) {
    micBtn.addEventListener('click', () => {
      micBtn.classList.contains('recording') ? stopRecording() : startRecording();
    });
  }

  // ============================= SETTINGS MODAL =============================
  if (settingsBtn && settingsModal) settingsBtn.addEventListener('click', () => settingsModal.classList.add('open'));
  if (modalClose && settingsModal) {
    modalClose.addEventListener('click', () => settingsModal.classList.remove('open'));
    settingsModal.addEventListener('click', (e) => { if (e.target === settingsModal) settingsModal.classList.remove('open'); });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (settingsModal && settingsModal.classList.contains('open')) settingsModal.classList.remove('open');
      if (confirmModal && confirmModal.style.display !== 'none') sendConfirmation(false);
    }
  });

  // ============================= CLEAR HISTORY =============================
  const clearHistoryBtn = document.getElementById('clear-history-btn');
  if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener('click', async () => {
      try {
        const res = await fetch(`${API}/api/history`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Clear failed');
        currentTurn = 0;
        if (turnCount) turnCount.textContent = 0;
        showWelcomeMessage();
        clearTrace();
        showToast('Conversation cleared', 'success');
      } catch (e) {
        showToast('Failed to clear history', 'error');
      }
    });
  }

  // ============================= KEYBOARD SHORTCUTS =============================
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      const activeView = document.querySelector('.view.active');
      if (activeView && activeView.id === 'view-chat' && textInput) textInput.focus();
      else if (activeView && activeView.id === 'view-memory' && memSearch) memSearch.focus();
    }
  });

  // ============================= INIT =============================
  if (sendBtn) sendBtn.disabled = true;
  loadHistory();
  connectWebSocket();

})();
