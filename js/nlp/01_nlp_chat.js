// ===== nlp_chat.js — NLP Chat UI + WebSocket Client for Beamline Control =====
'use strict';

// ===== NLP Chat State =====
// @module nlp/01_nlp_chat
// @exports ACTION_META, NLP_STATE, _actionLabel, _chatTabInitialized, _generateClientFallback, _origSwitchTab, _riskColor, addChatMessage, connectNLP, disconnectNLP, escapeHtml, executeNLPActions, handleNLPResponse, initNLPChat, rejectNLPActions, ...
var NLP_STATE = {
  wsUrl: 'ws://' + (typeof SERVER_HOST !== 'undefined' ? SERVER_HOST : 'localhost') + ':' + (typeof SERVER_WS_PORT !== 'undefined' ? SERVER_WS_PORT : 8001) + '/ws/chat',
  ws: null,
  connected: false,
  reconnectTimer: null,
  reconnectAttempts: 0,
  maxReconnect: 5,
  messages: [],       // {role:'user'|'assistant'|'system', text:string, actions?:[], ts:number}
  pendingActions: null // actions awaiting user confirmation
};

// ===== Connect to NLP WebSocket =====
function connectNLP(url) {
  // Guard: skip if already connected or connecting
  if (NLP_STATE.ws) {
    var s = NLP_STATE.ws.readyState;
    if (s === WebSocket.OPEN || s === WebSocket.CONNECTING) return;
    NLP_STATE.ws.onopen = null;
    NLP_STATE.ws.onclose = null;
    NLP_STATE.ws.onmessage = null;
    NLP_STATE.ws.onerror = null;
    NLP_STATE.ws.close();
  }
  if (NLP_STATE.reconnectTimer) {
    clearTimeout(NLP_STATE.reconnectTimer);
    NLP_STATE.reconnectTimer = null;
  }
  NLP_STATE.wsUrl = url || NLP_STATE.wsUrl;

  try {
    NLP_STATE.ws = new WebSocket(NLP_STATE.wsUrl);

    NLP_STATE.ws.onopen = function() {
      NLP_STATE.connected = true;
      NLP_STATE.reconnectAttempts = 0;
      addChatMessage('system', 'Connected to NLP agent.');
      updateNLPStatusUI();
      log('info', 'NLP WebSocket connected');
    };

    NLP_STATE.ws.onmessage = function(e) {
      try {
        var msg = JSON.parse(e.data);
        handleNLPResponse(msg);
      } catch (err) {
        log('err', 'NLP message parse error');
      }
    };

    NLP_STATE.ws.onclose = function() {
      var wasConnected = NLP_STATE.connected;
      NLP_STATE.connected = false;
      updateNLPStatusUI();
      if (wasConnected && NLP_STATE.reconnectAttempts < NLP_STATE.maxReconnect) {
        var delay = Math.min(1000 * Math.pow(2, NLP_STATE.reconnectAttempts), 30000);
        NLP_STATE.reconnectAttempts++;
        NLP_STATE.reconnectTimer = setTimeout(function() { connectNLP(); }, delay);
      } else if (!wasConnected) {
        addChatMessage('system',
          'NLP server connection failed. Please follow these steps:\n' +
          '1. Open a terminal and navigate to the server folder:\n' +
          '   cd K4GSR-Beamline/server\n' +
          '2. Start the server:\n' +
          '   python server.py\n' +
          '3. After seeing "server listening on 0.0.0.0:8001", click [Connect]\n\n' +
          'NLP engine settings (server/.env):\n' +
          '  NLP_ENGINE=ollama  -> Ollama local LLM (requires ollama serve)\n' +
          '  NLP_ENGINE=claude  -> Anthropic Claude API\n' +
          '  NLP_ENGINE=gemini  -> Google Gemini API');
      }
    };

    NLP_STATE.ws.onerror = function() {
      // onerror is always called just before onclose -- guidance is shown in onclose
    };
  } catch (e) {
    log('err', 'NLP connect failed: ' + e.message);
  }
}

function disconnectNLP() {
  if (NLP_STATE.ws) { NLP_STATE.ws.close(); NLP_STATE.ws = null; }
  if (NLP_STATE.reconnectTimer) { clearTimeout(NLP_STATE.reconnectTimer); }
  NLP_STATE.connected = false;
  NLP_STATE.reconnectAttempts = 0;
  updateNLPStatusUI();
}

// ===== Send User Message =====
function sendNLPMessage(text) {
  if (!text || !text.trim()) return;
  text = text.trim();

  addChatMessage('user', text);

  if (!NLP_STATE.connected || !NLP_STATE.ws) {
    addChatMessage('system', 'Not connected to server. Please check the connection.');
    return;
  }

  // Build context from current beamline state
  var context = {};
  if (typeof state !== 'undefined') {
    context.energy = state.energy;
    context.gap = state.gap;
    context.mode = state.mode;
    context.focusMode = state.focusMode;
    context.crystal = state.crystal;
    context.ssaH = state.ssaH;
    context.ssaV = state.ssaV;
    context.m1pitch = state.m1pitch;
    context.m2pitch = state.m2pitch;
  }
  // Nano scanner state
  if (typeof NANO_SCANNER !== 'undefined') {
    context.nano_connected = NANO_SCANNER.connected;
    context.nano_scanning = NANO_SCANNER.scanning;
    context.nano_px_nm = NANO_SCANNER.positions[0];
    context.nano_py_nm = NANO_SCANNER.positions[1];
    context.nano_pz_nm = NANO_SCANNER.positions[2];
  }

  NLP_STATE._lastUserText = text;  // Layer 5: save for fallback

  NLP_STATE.ws.send(JSON.stringify({
    action: 'chat',
    text: text,
    context: context,
    language: (typeof UI_LANG !== 'undefined') ? UI_LANG : 'ko'
  }));

  // Clear input
  var inp = document.getElementById('nlpChatInput');
  if (inp) inp.value = '';
}

// ===== Handle NLP Response =====
function handleNLPResponse(msg) {
  if (msg.type === 'thinking') {
    showThinkingIndicator(true);
    return;
  }

  showThinkingIndicator(false);

  // Handle Bluesky scan events in chat
  if (msg.type === 'scan_event') {
    var docType = msg.doc_type;
    var doc = msg.doc || {};
    if (docType === 'start') {
      addChatMessage('system', 'Bluesky scan started: ' + (msg.plan || 'unknown'));
    } else if (docType === 'stop') {
      var status = doc.exit_status === 'success' ? 'complete' : 'failed';
      addChatMessage('system', 'Bluesky scan ' + status + ': ' + (msg.event_count || 0) + ' points');
    }
    return;
  }

  if (msg.type === 'error') {
    addChatMessage('system', 'Error: ' + (msg.message || 'Unknown error'));
    return;
  }

  if (msg.type === 'nlp_response') {
    var explanation = msg.explanation || '';
    var actions = msg.actions || [];
    var needConfirm = msg.confirmation_required !== false;

    // ── Layer 5: Client-side fallback for empty/unhelpful responses ──
    if (actions.length === 0 && explanation.trim().length < 5) {
      explanation = _generateClientFallback(NLP_STATE._lastUserText || '');
    }

    // Set pendingActions BEFORE addChatMessage -- renderChatMessages()
    // needs this to be non-null to render Run/Cancel buttons
    if (actions.length > 0 && needConfirm) {
      NLP_STATE.pendingActions = actions;
    }

    addChatMessage('assistant', explanation, actions, needConfirm);

    if (actions.length > 0 && !needConfirm) {
      // Auto-execute (e.g., tab switching, status queries)
      executeNLPActions(actions);
    }
  }

  if (msg.type === 'rag_response') {
    var ragExplanation = msg.explanation || '';
    var ragSources = msg.sources || [];
    // Append source citations
    if (ragSources.length > 0) {
      ragExplanation += '\n\n---\nSources:\n';
      for (var si = 0; si < ragSources.length; si++) {
        ragExplanation += '- ' + ragSources[si] + '\n';
      }
    }
    addChatMessage('assistant', ragExplanation);
  }

  if (msg.type === 'status') {
    var d = msg.data || {};
    var statusText = 'Ring Current: ' + (d.ring_current ? d.ring_current.toFixed(1) + ' mA' : 'N/A') +
      ', DCM theta: ' + (d.dcm_theta ? d.dcm_theta.toFixed(3) + ' deg' : 'N/A') +
      ', IVU Gap: ' + (d.ivu_gap ? d.ivu_gap.toFixed(1) + ' mm' : 'N/A') +
      ', PV: ' + (d.pv_count || 0) + ', Clients: ' + (d.client_count || 0);
    addChatMessage('assistant', statusText);
  }
}

// ===== Action descriptions & risk classification =====
var ACTION_META = {
  // Scans (risk: high → orange)
  quickEnergyScan:   { label: 'Energy Scan',        risk: 'scan',  color: '#e67e22' },
  quickXafs:         { label: 'XANES Scan',          risk: 'scan',  color: '#e67e22' },
  quickRaster:       { label: 'Raster Scan',        risk: 'scan',  color: '#e67e22' },
  quickAlign:        { label: 'Motor Alignment',    risk: 'scan',  color: '#e67e22' },
  quickCount:        { label: 'Point Measurement',  risk: 'scan',  color: '#e67e22' },
  quickXanes:        { label: 'XANES Scan',         risk: 'scan',  color: '#e67e22' },
  quickFlyScan:      { label: 'Fly Scan',           risk: 'scan',  color: '#e67e22' },
  quickAutoTune:     { label: 'Auto Tuning',        risk: 'scan',  color: '#e67e22' },
  quickAdaptiveScan: { label: 'Adaptive Scan',      risk: 'scan',  color: '#e67e22' },
  quickRelAlign:     { label: 'Relative Alignment', risk: 'scan',  color: '#e67e22' },
  quickFermat:       { label: 'Fermat Scan',        risk: 'scan',  color: '#e67e22' },
  quickRelRaster:    { label: 'Relative Raster',    risk: 'scan',  color: '#e67e22' },
  queueStart:        { label: 'Scan Start',         risk: 'scan',  color: '#e67e22' },
  queueStop:         { label: 'Scan Stop',          risk: 'ctrl',  color: '#e74c3c' },
  queuePause:        { label: 'Scan Pause',         risk: 'ctrl',  color: '#f39c12' },
  queueResume:       { label: 'Scan Resume',        risk: 'ctrl',  color: '#2ecc71' },
  queueAbort:        { label: 'Scan Abort',         risk: 'ctrl',  color: '#e74c3c' },
  queueClear:        { label: 'Queue Reset',        risk: 'ctrl',  color: '#e74c3c' },
  // Motors (risk: medium -- yellow)
  motorSetUI:        { label: 'Motor Move',         risk: 'motor', color: '#f1c40f' },
  setTargetEnergy:   { label: 'Set Energy',         risk: 'motor', color: '#f1c40f' },
  setCrystal:        { label: 'Crystal Change',     risk: 'motor', color: '#f1c40f' },
  setFocusMode:      { label: 'Focus Mode',         risk: 'motor', color: '#f1c40f' },
  maskAperUpdate:    { label: 'Mask Adjust',        risk: 'motor', color: '#f1c40f' },
  emergencyStop:     { label: 'Emergency Stop',     risk: 'ctrl',  color: '#e74c3c' },
  // Alignment (risk: high)
  runAlignStepUI:    { label: 'Alignment Step',     risk: 'scan',  color: '#e67e22' },
  runFullAlignment:  { label: 'Full Alignment',     risk: 'scan',  color: '#e67e22' },
  runMirrorAlignUI:  { label: 'Mirror Alignment',   risk: 'scan',  color: '#e67e22' },
  abortAlignment:    { label: 'Alignment Abort',    risk: 'ctrl',  color: '#e74c3c' },
  // Settings (risk: low -- blue)
  switchTab:         { label: 'Tab Switch',         risk: 'info',  color: '#3498db' },
  showBeamProfile:   { label: 'Beam Profile',       risk: 'info',  color: '#3498db' },
  setupVirtualExperiment: { label: 'Experiment Preset', risk: 'info', color: '#3498db' },
  queuePlan:         { label: 'Add Plan',           risk: 'scan',  color: '#e67e22' },
  // Optimizer (risk: info/motor)
  optimizeBeamline:  { label: 'Beam Optimize',     risk: 'info',  color: '#3498db' },
  sweepEnergy:       { label: 'Energy Sweep',      risk: 'info',  color: '#3498db' },
  sweepSSA:          { label: 'SSA Sweep',          risk: 'info',  color: '#3498db' },
  estimateSignal:    { label: 'Signal Estimate',   risk: 'info',  color: '#3498db' },
  applyOptimization: { label: 'Apply Config',      risk: 'motor', color: '#f1c40f' },
  cancelOptimization:{ label: 'Cancel Optimize',   risk: 'info',  color: '#95a5a6' },
  showTransmission:  { label: 'Transmission Calc', risk: 'info',  color: '#3498db' },
  // Nano Scanner (SmarAct MCS2 + PicoScale)
  nanoScanStep2D:    { label: 'Nano 2D Scan',      risk: 'scan',  color: '#e67e22' },
  nanoScanFly1D:     { label: 'Nano Fly Scan',      risk: 'scan',  color: '#e67e22' },
  nanoScanSpiral:    { label: 'Nano Spiral Scan',   risk: 'scan',  color: '#e67e22' },
  nanoJog:           { label: 'Nano Jog',           risk: 'motor', color: '#f1c40f' },
  nanoMoveTo:        { label: 'Nano Move',          risk: 'motor', color: '#f1c40f' },
  nanoStatus:        { label: 'Nano Status',        risk: 'info',  color: '#3498db' },
  nanoScanAbort:     { label: 'Nano Scan Abort',    risk: 'ctrl',  color: '#e74c3c' },
  queryHardwareStatus: { label: 'HW Status Query',  risk: 'info',  color: '#3498db' }
};

function _actionLabel(fn, args) {
  var meta = ACTION_META[fn];
  var label = meta ? meta.label : fn;
  if (fn === 'setTargetEnergy' && args && args[0]) label += ' → ' + args[0] + ' keV';
  if (fn === 'quickXafs' && args) label += ' → ' + (args[0] || '') + ' ' + (args[1] || 'K') + '-edge';
  if (fn === 'quickEnergyScan' && args) label += ' → ' + (args[0]||'') + '~' + (args[1]||'') + ' keV';
  if (fn === 'quickRaster' && args) label += ' → ' + (args[2]||21) + '×' + (args[2]||21) + ' pts';
  if (fn === 'quickXanes' && args) label += ' → ' + (args[0]||'') + ' ' + (args[1]||'K') + '-edge';
  if (fn === 'quickFlyScan' && args) label += ' → ' + (args[0]||'') + ':' + (args[1]||'') + ' ' + (args[2]||'') + '~' + (args[3]||'');
  if (fn === 'quickAutoTune' && args) label += ' → ' + (args[0]||'') + ':' + (args[1]||'') + ' [' + (args[2]||'') + '~' + (args[3]||'') + ']';
  if (fn === 'quickAdaptiveScan' && args) label += ' → ' + (args[0]||'') + '~' + (args[1]||'') + ' keV';
  if (fn === 'quickRelAlign' && args) label += ' → ' + (args[0]||'') + ':' + (args[1]||'') + ' ±' + ((args[2]||0)/2);
  if (fn === 'quickFermat' && args) label += ' → ' + (args[0]||10) + '×' + (args[1]||10) + ' µm';
  if (fn === 'quickRelRaster' && args) label += ' → ' + (args[2]||21) + '×' + (args[3]||21) + ' pts';
  if (fn === 'motorSetUI' && args) label += ' → ' + (args[0]||'') + ':' + (args[1]||'') + '=' + (args[2]||'');
  if (fn === 'switchTab' && args) label += ' → ' + (args[0]||'');
  if (fn === 'optimizeBeamline' && args && args[0]) {
    label += ' -> ' + (args[0].element || '') + ' ' + (args[0].technique || '');
  }
  if (fn === 'estimateSignal' && args) label += ' -> ' + (args[0]||'') + ' ' + (args[1]||'');
  if (fn === 'nanoScanStep2D' && args) label += ' \u2192 ' + (args[0]||10) + '\u00d7' + (args[1]||10) + ' um';
  if (fn === 'nanoScanFly1D' && args) label += ' \u2192 ' + (args[0]||'x') + ' ' + (args[1]||10) + ' um';
  if (fn === 'nanoScanSpiral' && args) label += ' \u2192 R=' + (args[0]||5) + ' um';
  if (fn === 'nanoJog' && args) label += ' \u2192 ' + (args[0]||'x') + ' ' + (args[1]||0) + ' um';
  if (fn === 'nanoMoveTo' && args) label += ' \u2192 ' + (args[0]||'x') + '=' + (args[1]||0) + ' um';
  if (fn === 'queryHardwareStatus' && args) label += ' \u2192 ' + (args[0]||'all');
  return label;
}

function _riskColor(fn) {
  var meta = ACTION_META[fn];
  return meta ? meta.color : '#95a5a6';
}

// ===== Execute NLP Actions (sequential with progress) =====
function executeNLPActions(actions) {
  if (!actions || !actions.length) return;

  var total = actions.length;
  var current = 0;
  var failed = false;

  function runNext() {
    if (current >= total || failed) {
      NLP_STATE.pendingActions = null;
      if (!failed) {
        addChatMessage('system', 'All ' + total + ' commands executed successfully.');
      }
      renderChatMessages();
      return;
    }

    var act = actions[current];
    var fn = act.fn;
    var args = act.args || [];
    var label = _actionLabel(fn, args);

    try {
      if (typeof window[fn] === 'function') {
        // Force full-auto alignment when called from NLP
        if (fn === 'runFullAlignment') {
          window._alignFullAuto = true;
        }
        var result = window[fn].apply(null, args);
        log('info', 'NLP action [' + (current+1) + '/' + total + ']: ' + label);
        current++;
        // If function returns a Promise (async), wait for it before next action
        if (result && typeof result.then === 'function') {
          result.then(function() {
            setTimeout(runNext, 80);
          }).catch(function(e) {
            log('warn', 'NLP async action error: ' + fn + ' — ' + e.message);
            setTimeout(runNext, 80); // continue despite error
          });
          return; // don't call setTimeout below
        }
        // Small delay between actions for UI responsiveness
        setTimeout(runNext, 80);
      } else {
        failed = true;
        log('warn', 'NLP: function not found: ' + fn);
        addChatMessage('system', 'Function not found: ' + fn + '\nRemaining ' + (total - current - 1) + ' commands were not executed.');
        NLP_STATE.pendingActions = null;
        renderChatMessages();
      }
    } catch (e) {
      failed = true;
      log('err', 'NLP action error: ' + fn + ' — ' + e.message);
      addChatMessage('system', 'Execution error (' + label + '): ' + e.message + '\nRemaining ' + (total - current - 1) + ' commands were not executed.');
      NLP_STATE.pendingActions = null;
      renderChatMessages();
    }
  }

  addChatMessage('system', 'Executing ' + total + ' commands sequentially...');
  renderChatMessages();
  setTimeout(runNext, 50);
}

function rejectNLPActions() {
  NLP_STATE.pendingActions = null;
  addChatMessage('system', 'Commands cancelled.');
  renderChatMessages();
}

// ===== Chat Message Management =====
function addChatMessage(role, text, actions, needConfirm) {
  NLP_STATE.messages.push({
    role: role,
    text: text,
    actions: actions || null,
    needConfirm: needConfirm || false,
    ts: Date.now()
  });

  // Keep last 100 messages
  if (NLP_STATE.messages.length > 100) {
    NLP_STATE.messages = NLP_STATE.messages.slice(-100);
  }

  renderChatMessages();
}

// ===== Render Chat UI =====
function renderChatMessages() {
  var el = document.getElementById('nlpChatBody');
  if (!el) return;

  var h = '';
  NLP_STATE.messages.forEach(function(msg, idx) {
    var roleColor = msg.role === 'user' ? 'var(--ac)' :
                    msg.role === 'assistant' ? 'var(--gn)' : 'var(--t3)';
    var roleLabel = msg.role === 'user' ? 'Me' :
                    msg.role === 'assistant' ? 'AI' : 'System';
    var bgColor = msg.role === 'user' ? 'rgba(77,184,255,.06)' :
                  msg.role === 'assistant' ? 'rgba(64,216,154,.06)' : 'rgba(255,255,255,.02)';

    var timeStr = new Date(msg.ts).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

    h += '<div style="padding:6px 8px;margin-bottom:4px;border-radius:4px;background:' + bgColor + '">';
    h += '<div style="display:flex;justify-content:space-between;margin-bottom:2px">';
    h += '<span style="font-size:8px;font-weight:600;color:' + roleColor + '">' + roleLabel + '</span>';
    h += '<span style="font-size:8px;color:var(--t3)">' + timeStr + '</span></div>';
    h += '<div style="font-size:9px;color:var(--t0);line-height:1.5;word-break:break-word">' + escapeHtml(msg.text, msg.role === 'assistant' || msg.role === 'system') + '</div>';

    // Show action summary with risk color + labels
    if (msg.actions && msg.actions.length > 0) {
      h += '<div style="margin-top:4px;padding:4px 6px;background:rgba(160,140,255,.08);border-radius:3px;border-left:2px solid var(--pr)">';
      h += '<div style="font-size:8px;color:var(--t3);margin-bottom:2px">' + msg.actions.length + ' commands:</div>';
      msg.actions.forEach(function(act, ai) {
        var label = _actionLabel(act.fn, act.args);
        var color = _riskColor(act.fn);
        var argsStr = act.args ? act.args.map(function(a) { return JSON.stringify(a); }).join(', ') : '';
        h += '<div style="display:flex;align-items:center;gap:4px;margin:1px 0">';
        h += '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:' + color + ';flex-shrink:0"></span>';
        h += '<span style="font-size:9px;color:var(--t0)">' + escapeHtml(label) + '</span>';
        h += '<span style="font-size:7px;font-family:var(--mn);color:var(--t3);margin-left:auto">' + escapeHtml(act.fn) + '(' + escapeHtml(argsStr) + ')</span>';
        h += '</div>';
      });
      h += '</div>';
    }

    // Show confirm/reject buttons for pending actions
    if (msg.needConfirm && NLP_STATE.pendingActions && idx === NLP_STATE.messages.length - 1) {
      // Find last assistant message with pending actions
      var isLastAssistantWithActions = (msg.role === 'assistant' && msg.actions && msg.actions.length > 0);
      if (isLastAssistantWithActions) {
        h += '<div style="display:flex;gap:4px;margin-top:6px">';
        h += '<button onclick="executeNLPActions(NLP_STATE.pendingActions)" style="flex:1;padding:4px 8px;background:var(--gn);color:#000;border:none;border-radius:3px;font-size:9px;font-weight:600;cursor:pointer;font-family:var(--mn)">Run</button>';
        h += '<button onclick="rejectNLPActions()" style="flex:1;padding:4px 8px;background:var(--s2);color:var(--t2);border:1px solid var(--b1);border-radius:3px;font-size:9px;cursor:pointer;font-family:var(--mn)">Cancel</button>';
        h += '</div>';
      }
    }

    h += '</div>';
  });

  el.innerHTML = h;

  // Auto-scroll to bottom
  el.scrollTop = el.scrollHeight;
}

function showThinkingIndicator(show) {
  var el = document.getElementById('nlpThinking');
  if (el) el.style.display = show ? 'flex' : 'none';
}

function escapeHtml(text, preserveNewlines) {
  var div = document.createElement('div');
  div.textContent = text;
  var html = div.innerHTML;
  if (preserveNewlines) html = html.replace(/\n/g, '<br>');
  return html;
}

// ===== NLP Status UI =====
function updateNLPStatusUI() {
  var dot = document.getElementById('nlpStatusDot');
  var txt = document.getElementById('nlpStatusText');
  if (dot) dot.style.color = NLP_STATE.connected ? 'var(--gn)' : 'var(--rd)';
  if (txt) txt.textContent = NLP_STATE.connected ? 'Connected' : 'Disconnected';
}

// ===== Layer 5: Client-side fallback for empty NLP responses =====
function _generateClientFallback(userText) {
  if (!userText) {
    return '요청을 처리하지 못했습니다. 구체적인 명령을 입력해주세요.';
  }
  var text = userText.toLowerCase();
  var parts = [];

  // Detect possible intent from keywords
  var hasXRF = /xrf|형광|원소.*(분포|맵|이미징)/.test(text);
  var hasXAFS = /xafs|exafs|흡수|흡수단/.test(text);
  var hasXANES = /xanes|니어.?엣지|near.?edge/.test(text);
  var hasXRD = /xrd|회절|분말|결정/.test(text);
  var hasScan = /스캔|scan|측정|맵핑|매핑/.test(text);
  var hasMotor = /이동|모터|피치|pitch|갭|gap/.test(text);
  var hasAlign = /정렬|align|튜닝|tune/.test(text);
  var hasEnergy = /에너지|energy|kev/.test(text);
  var hasInfo = /뭐야|뭔지|알려|차이|설명|help/.test(text);

  if (hasInfo) {
    parts.push('질문을 이해하지 못했습니다. 다음과 같이 구체적으로 물어봐주세요:');
    parts.push('- "XRD가 뭐야?"');
    parts.push('- "XANES와 EXAFS의 차이는?"');
    parts.push('- "사용 가능한 명령어를 알려줘"');
  } else if (hasXAFS || hasXANES) {
    parts.push('XAFS/XANES 측정 요청을 처리하지 못했습니다.');
    parts.push('원소와 edge를 명시해주세요:');
    parts.push('- "Cu K-edge XAFS 측정해줘"');
    parts.push('- "Fe K-edge XANES 측정해줘"');
  } else if (hasXRF) {
    parts.push('XRF 측정 요청을 처리하지 못했습니다.');
    parts.push('원소, 범위, 포인트 수를 명시해주세요:');
    parts.push('- "Fe XRF 10x10 41포인트 맵핑해줘"');
  } else if (hasXRD) {
    parts.push('XRD 측정 요청을 처리하지 못했습니다.');
    parts.push('에너지와 범위를 명시해주세요:');
    parts.push('- "15 keV에서 10x10 XRD 매핑해줘"');
  } else if (hasScan) {
    parts.push('스캔 요청을 처리하지 못했습니다. 다음 정보가 필요합니다:');
    parts.push('- 측정 기법 (XAFS, XRF, XRD 등)');
    parts.push('- 대상 원소');
    parts.push('- 스캔 범위/포인트 수');
  } else if (hasMotor) {
    parts.push('모터 이동 요청을 처리하지 못했습니다.');
    parts.push('모터 이름과 목표값을 명시해주세요:');
    parts.push('- "M1 피치를 2.5 mrad로 이동해"');
    parts.push('- "에너지를 12 keV로 설정해"');
  } else if (hasAlign) {
    parts.push('정렬 요청을 처리하지 못했습니다. 다음 중 선택해주세요:');
    parts.push('- "전체 빔 정렬 시작"');
    parts.push('- "M1 미러 정렬해줘"');
    parts.push('- "M1 피치 자동 정렬해줘"');
  } else if (hasEnergy) {
    parts.push('에너지 설정 요청을 처리하지 못했습니다.');
    parts.push('구체적인 값을 말씀해주세요:');
    parts.push('- "에너지를 12 keV로 설정해"');
    parts.push('- 빔라인 에너지 범위: 5~25 keV');
  } else {
    parts.push('요청을 이해하지 못했습니다. 다음과 같이 말씀해주세요:');
    parts.push('- "Cu K-edge XAFS 측정해줘"');
    parts.push('- "에너지를 12 keV로 설정해"');
    parts.push('- "10x10 41포인트 Fe XRF 맵핑해줘"');
    parts.push('- "전체 빔 정렬 시작"');
    parts.push('- "XRD가 뭐야?"');
  }

  return parts.join('\n');
}

// ===== Beam Profile Popup (NLP-callable) =====
// Opens the sample modal with Monte Carlo beam profile
function showBeamProfile(compId) {
  var id = compId || 'sample';
  if (typeof showComp === 'function') {
    showComp(id);
  } else {
    log('warn', 'showComp not available');
  }
}

// ===== Render Chat Tab =====
var _chatTabInitialized = false;

function renderChatTab() {
  var el = document.getElementById('tab-chat');
  if (!el) return;

  // If already initialized, just restore messages + status — don't rebuild
  if (_chatTabInitialized && document.getElementById('nlpChatBody')) {
    renderChatMessages();
    updateNLPStatusUI();
    return;
  }

  el.innerHTML =
    '<div style="display:flex;flex-direction:column;height:100%">' +
      // Connection controls
      '<div style="margin-bottom:6px">' +
        '<h4 style="font-size:10px;color:var(--t1);font-weight:600;margin:0 0 3px 2px;display:flex;justify-content:space-between;align-items:center">' +
          '<span>NLP CHAT</span>' +
          '<span style="display:flex;align-items:center;gap:3px">' +
            '<span id="nlpStatusDot" style="color:var(--rd);font-size:10px">\u25CF</span>' +
            '<span id="nlpStatusText" style="font-size:8px;color:var(--t3);font-weight:400">Disconnected</span>' +
          '</span>' +
        '</h4>' +
        '<div class="ctrl-group" style="margin:0">' +
        '<div style="display:flex;gap:2px">' +
          '<button class="sb go" onclick="connectNLP()" style="flex:1">Connect</button>' +
          '<button class="sb sec" onclick="disconnectNLP()" style="flex:1">Disconnect</button>' +
        '</div>' +
      '</div></div>' +

      // Chat messages area
      '<div id="nlpChatBody" style="flex:1;overflow-y:auto;min-height:120px;padding:2px;background:var(--s1);border-radius:4px;border:1px solid var(--b0)">' +
        '<div style="padding:10px;font-size:9px;color:var(--t3);line-height:1.6">' +
          '<div style="text-align:center;margin-bottom:6px;color:var(--t2)">Click [Connect] to connect to the NLP server.</div>' +
          '<div style="background:var(--s2);padding:6px 8px;border-radius:4px;font-family:var(--mn);font-size:8px">' +
            '<div style="color:var(--am);margin-bottom:3px">How to start the server:</div>' +
            '<div>cd K4GSR-Beamline/server</div>' +
            '<div>python server.py</div>' +
            '<div style="color:var(--t3);margin-top:3px">Change engine: server/.env -> NLP_ENGINE=ollama|claude|gemini</div>' +
          '</div>' +
        '</div>' +
      '</div>' +

      // Thinking indicator
      '<div id="nlpThinking" style="display:none;align-items:center;gap:4px;padding:4px 8px;font-size:8px;color:var(--am)">' +
        '<span style="animation:blink 1s infinite">\u25CF</span> AI is thinking...' +
      '</div>' +

      // Input area
      '<div style="display:flex;gap:2px;margin-top:4px">' +
        '<input type="text" id="nlpChatInput" placeholder="Enter command..." ' +
          'style="flex:1;background:var(--s2);border:1px solid var(--b1);color:var(--t0);padding:6px 8px;border-radius:4px;font-size:10px;font-family:var(--sn)" ' +
          'onkeydown="if(event.key===\'Enter\')sendNLPMessage(this.value)"/>' +
        '<button onclick="sendNLPMessage(document.getElementById(\'nlpChatInput\').value)" ' +
          'style="padding:6px 10px;background:var(--ac);color:#000;border:none;border-radius:4px;font-size:10px;cursor:pointer;font-weight:600">\u25B6</button>' +
      '</div>' +

      // Quick actions
      '<div style="display:flex;flex-wrap:wrap;gap:2px;margin-top:4px">' +
        '<button onclick="sendNLPMessage(\'Show current beam status\')" style="font-size:8px;padding:2px 6px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:3px;cursor:pointer;font-family:var(--mn)">Beam Status</button>' +
        '<button onclick="sendNLPMessage(\'Run Cu K-edge XANES measurement\')" style="font-size:8px;padding:2px 6px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:3px;cursor:pointer;font-family:var(--mn)">Cu XANES</button>' +
        '<button onclick="sendNLPMessage(\'Set energy to 12 keV\')" style="font-size:8px;padding:2px 6px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:3px;cursor:pointer;font-family:var(--mn)">E=12keV</button>' +
        '<button onclick="sendNLPMessage(\'Align M1 mirror\')" style="font-size:8px;padding:2px 6px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:3px;cursor:pointer;font-family:var(--mn)">M1 Align</button>' +
      '</div>' +
    '</div>';

  _chatTabInitialized = true;

  // Restore existing messages if any
  if (NLP_STATE.messages.length > 0) {
    renderChatMessages();
  }
  updateNLPStatusUI();
}

// ===== Initialize Chat when tab is shown =====
var _origSwitchTab = typeof switchTab === 'function' ? switchTab : null;

// Chat tab rendering will be triggered by switchTab override in init
// This is handled by the initNLPChat function below

function initNLPChat() {
  // Render chat tab content when first shown
  renderChatTab();
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof ACTION_META!=="undefined")globalThis.ACTION_META=ACTION_META;
if(typeof NLP_STATE!=="undefined")globalThis.NLP_STATE=NLP_STATE;
if(typeof addChatMessage!=="undefined")globalThis.addChatMessage=addChatMessage;
if(typeof connectNLP!=="undefined")globalThis.connectNLP=connectNLP;
if(typeof disconnectNLP!=="undefined")globalThis.disconnectNLP=disconnectNLP;
if(typeof escapeHtml!=="undefined")globalThis.escapeHtml=escapeHtml;
if(typeof executeNLPActions!=="undefined")globalThis.executeNLPActions=executeNLPActions;
if(typeof handleNLPResponse!=="undefined")globalThis.handleNLPResponse=handleNLPResponse;
if(typeof initNLPChat!=="undefined")globalThis.initNLPChat=initNLPChat;
if(typeof rejectNLPActions!=="undefined")globalThis.rejectNLPActions=rejectNLPActions;
if(typeof renderChatMessages!=="undefined")globalThis.renderChatMessages=renderChatMessages;
if(typeof renderChatTab!=="undefined")globalThis.renderChatTab=renderChatTab;
if(typeof sendNLPMessage!=="undefined")globalThis.sendNLPMessage=sendNLPMessage;
if(typeof showBeamProfile!=="undefined")globalThis.showBeamProfile=showBeamProfile;
if(typeof showThinkingIndicator!=="undefined")globalThis.showThinkingIndicator=showThinkingIndicator;
if(typeof updateNLPStatusUI!=="undefined")globalThis.updateNLPStatusUI=updateNLPStatusUI;
if(typeof _actionLabel!=="undefined")globalThis._actionLabel=_actionLabel;
if(typeof _chatTabInitialized!=="undefined")globalThis._chatTabInitialized=_chatTabInitialized;
if(typeof _generateClientFallback!=="undefined")globalThis._generateClientFallback=_generateClientFallback;
if(typeof _origSwitchTab!=="undefined")globalThis._origSwitchTab=_origSwitchTab;
if(typeof _riskColor!=="undefined")globalThis._riskColor=_riskColor;
