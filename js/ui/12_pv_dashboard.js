'use strict';
// ===== ui/12_pv_dashboard.js -- PV Connection Status Dashboard =====
// @module ui/12_pv_dashboard
// @exports PV_DASHBOARD_GROUPS, _pvDashboardEl, _pvDashboardRefresh, _pvDashboardTimer, showPVConnectionStatus
// Phoebus-style overview of all 86 PVs: connection state, value, alarm severity.
// Opens as a resizable popup. Updates in real-time via PV_REGISTRY.

// ===== Dashboard Data: all device groups with full PV lists =====
var PV_DASHBOARD_GROUPS = [
  { name: 'IVU', pvs: ['BL10:IVU:Gap', 'BL10:IVU:TaperGap', 'BL10:IVU:Harmonic', 'BL10:IVU:GirderX', 'BL10:IVU:GirderY', 'BL10:IVU:GirderPitch', 'BL10:IVU:GirderYaw', 'BL10:IVU:EncUS', 'BL10:IVU:EncDS'] },
  { name: 'FMASK', pvs: ['BL10:FMASK:X', 'BL10:FMASK:Y', 'BL10:FMASK:Hgap', 'BL10:FMASK:Vgap'] },
  { name: 'MMASK', pvs: ['BL10:MMASK:X', 'BL10:MMASK:Y', 'BL10:MMASK:Hgap', 'BL10:MMASK:Vgap'] },
  { name: 'WBS', pvs: ['BL10:WBS:Top', 'BL10:WBS:Bot', 'BL10:WBS:Inb', 'BL10:WBS:Outb', 'BL10:WBS:Hgap', 'BL10:WBS:Vgap'] },
  { name: 'ATT', pvs: ['BL10:ATT:X', 'BL10:ATT:Y'] },
  { name: 'M1', pvs: ['BL10:M1:Z', 'BL10:M1:Pitch', 'BL10:M1:PitchF', 'BL10:M1:Tx', 'BL10:M1:Roll', 'BL10:M1:Yaw', 'BL10:M1:BendU', 'BL10:M1:BendD'] },
  { name: 'DCM', pvs: ['BL10:DCM:Theta', 'BL10:DCM:Chi1', 'BL10:DCM:TX', 'BL10:DCM:Y1', 'BL10:DCM:Y2', 'BL10:DCM:Z2', 'BL10:DCM:DTheta2', 'BL10:DCM:Roll2', 'BL10:DCM:DTheta2F'] },
  { name: 'M2', pvs: ['BL10:M2:Z', 'BL10:M2:Pitch', 'BL10:M2:PitchF', 'BL10:M2:Tx', 'BL10:M2:Roll', 'BL10:M2:Yaw', 'BL10:M2:BendU', 'BL10:M2:BendD'] },
  { name: 'SSA', pvs: ['BL10:SSA:Hgap', 'BL10:SSA:Vgap', 'BL10:SSA:Hcen', 'BL10:SSA:Vcen'] },
  { name: 'KBV', pvs: ['BL10:KBV:X', 'BL10:KBV:Y', 'BL10:KBV:Z', 'BL10:KBV:Pitch', 'BL10:KBV:BendU', 'BL10:KBV:BendD'] },
  { name: 'KBH', pvs: ['BL10:KBH:X', 'BL10:KBH:Z', 'BL10:KBH:Pitch', 'BL10:KBH:Y', 'BL10:KBH:BendU', 'BL10:KBH:BendD'] },
  { name: 'ZP', pvs: ['BL10:ZP:X', 'BL10:ZP:Y', 'BL10:ZP:Z'] },
  { name: 'SAM', pvs: ['BL10:SAM:CX', 'BL10:SAM:CY', 'BL10:SAM:CZ', 'BL10:SAM:Theta', 'BL10:SAM:Phi', 'BL10:SAM:FX', 'BL10:SAM:FY', 'BL10:SAM:FZ', 'BL10:SAM:SX', 'BL10:SAM:SY'] },
  { name: 'DET', pvs: ['BL10:DET:X', 'BL10:DET:Y', 'BL10:DET:Z'] },
  { name: 'Status', pvs: ['BL10:RING:Current', 'BL10:RING:Energy', 'BL10:RING:Lifetime', 'BL10:FE:Shutter', 'BL10:XBPM1:X', 'BL10:XBPM1:Y', 'BL10:IC1:Current'] },
  { name: 'XBPM2', pvs: ['BL10:XBPM2:Current1:MeanValue_RBV', 'BL10:XBPM2:Current2:MeanValue_RBV', 'BL10:XBPM2:Current3:MeanValue_RBV', 'BL10:XBPM2:Current4:MeanValue_RBV', 'BL10:XBPM2:SumAll:MeanValue_RBV', 'BL10:XBPM2:PosX:MeanValue_RBV', 'BL10:XBPM2:PosY:MeanValue_RBV'] }
];

var _pvDashboardEl = null;
var _pvDashboardTimer = null;

// ===== Open/Close Dashboard =====
function showPVConnectionStatus() {
  if (_pvDashboardEl) {
    _pvDashboardEl.style.display = _pvDashboardEl.style.display === 'none' ? 'flex' : 'none';
    if (_pvDashboardEl.style.display !== 'none') _pvDashboardRefresh();
    return;
  }

  // Create popup
  var el = document.createElement('div');
  el.id = 'pvDashboardPopup';
  el.style.cssText = 'position:fixed;top:60px;left:50%;transform:translateX(-50%);' +
    'width:680px;height:520px;z-index:10100;display:flex;flex-direction:column;' +
    'background:var(--bg);border:1px solid var(--ac);border-radius:6px;' +
    'box-shadow:0 8px 32px rgba(0,0,0,.6);font-family:var(--mn)';

  // Title bar
  var header = document.createElement('div');
  header.id = 'pvDashHeader';
  header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;' +
    'padding:8px 12px;background:var(--s1);border-bottom:1px solid var(--ac);' +
    'border-radius:6px 6px 0 0;cursor:move;user-select:none;flex-shrink:0';
  header.innerHTML = '<span style="color:var(--ac);font-size:12px;font-weight:600">PV Connection Status</span>' +
    '<span id="pvDashSummary" style="color:var(--t2);font-size:10px"></span>' +
    '<span onclick="showPVConnectionStatus()" style="color:var(--t3);cursor:pointer;font-size:14px;padding:0 4px">&times;</span>';
  el.appendChild(header);

  // Body
  var body = document.createElement('div');
  body.id = 'pvDashBody';
  body.style.cssText = 'flex:1;overflow-y:auto;padding:8px 12px';
  el.appendChild(body);

  document.body.appendChild(el);
  _pvDashboardEl = el;

  // Make resizable
  if (typeof _makePopupResizable === 'function') {
    _makePopupResizable(el, { dragEl: header, minWidth: 480, minHeight: 300 });
  }

  _pvDashboardRefresh();

  // Auto-refresh every 2s
  if (_pvDashboardTimer) clearInterval(_pvDashboardTimer);
  _pvDashboardTimer = setInterval(function() {
    if (_pvDashboardEl && _pvDashboardEl.style.display !== 'none') {
      _pvDashboardRefresh();
    }
  }, 2000);
}

// ===== Refresh Dashboard Content =====
function _pvDashboardRefresh() {
  var body = document.getElementById('pvDashBody');
  var summary = document.getElementById('pvDashSummary');
  if (!body) return;

  var totalConn = 0;
  var totalDisc = 0;
  var totalAlarm = 0;
  var totalPVs = 0;
  var html = '';

  PV_DASHBOARD_GROUPS.forEach(function(grp) {
    var grpHtml = '';
    var grpCount = grp.pvs.length;
    totalPVs += grpCount;

    grp.pvs.forEach(function(pv) {
      var reg = (typeof PV_REGISTRY !== 'undefined') ? PV_REGISTRY[pv] : null;
      var connected = reg ? reg.connected : false;
      var severity = reg ? reg.severity : 3;
      var value = reg ? reg.value : null;
      var shortName = pv.replace('BL10:' + grp.name + ':', '').replace('BL10:', '');

      // Connection icon (Phoebus standard)
      var icon, iconColor;
      if (!connected) {
        icon = '&#9675;';  // hollow circle
        iconColor = 'var(--t3)';
        totalDisc++;
      } else if (severity >= 2) {
        icon = '&#9650;';  // triangle
        iconColor = '#ff4444';
        totalAlarm++;
        totalConn++;
      } else if (severity === 1) {
        icon = '&#9650;';
        iconColor = 'var(--am)';
        totalAlarm++;
        totalConn++;
      } else {
        icon = '&#9679;';  // filled circle
        iconColor = 'var(--gn)';
        totalConn++;
      }

      // Format value
      var fmtVal = '--';
      if (value !== null && value !== undefined) {
        if (typeof value === 'number') {
          if (Math.abs(value) < 0.001 && value !== 0) {
            fmtVal = value.toExponential(2);
          } else if (Math.abs(value) >= 1000) {
            fmtVal = value.toFixed(1);
          } else {
            fmtVal = value.toFixed(3);
          }
        } else {
          fmtVal = String(value);
        }
      }

      // HW badge
      var hwBadge = '';
      if (typeof EPICS_STATE !== 'undefined' && EPICS_STATE.pvSources) {
        var src = EPICS_STATE.pvSources[pv];
        if (src === 'hardware') {
          hwBadge = ' <span style="color:var(--gn);font-size:7px;font-weight:700;' +
            'border:1px solid var(--gn);border-radius:2px;padding:0 2px">HW</span>';
        }
      }

      grpHtml += '<span style="display:inline-flex;align-items:center;gap:2px;margin:1px 6px 1px 0;white-space:nowrap">' +
        '<span style="color:' + iconColor + ';font-size:8px">' + icon + '</span>' +
        '<span style="color:var(--t2);font-size:9px">' + shortName + '</span>' +
        hwBadge +
        '<span style="color:var(--t1);font-size:9px;font-weight:500">' + fmtVal + '</span>' +
        '</span>';
    });

    // Group header with count
    html += '<div style="margin:6px 0 2px 0">' +
      '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">' +
        '<span style="color:var(--ac);font-size:10px;font-weight:600">' + grp.name + '</span>' +
        '<span style="color:var(--t3);font-size:8px">(' + grpCount + ')</span>' +
      '</div>' +
      '<div style="display:flex;flex-wrap:wrap;padding:4px 8px;' +
        'background:var(--s1);border-radius:4px;border:1px solid rgba(77,184,255,.1)">' +
        grpHtml +
      '</div>' +
    '</div>';
  });

  body.innerHTML = html;

  // Update summary bar
  if (summary) {
    var parts = [];
    parts.push('<span style="color:var(--gn)">' + totalConn + '/' + totalPVs + ' Connected</span>');
    if (totalDisc > 0) {
      parts.push('<span style="color:var(--t3)">' + totalDisc + ' Disconnected</span>');
    }
    if (totalAlarm > 0) {
      parts.push('<span style="color:var(--am)">' + totalAlarm + ' Alarm</span>');
    }
    summary.innerHTML = parts.join(' &middot; ');
  }
}
