'use strict';
// Step name → i18n key mapping (display only; original name stays as API key)
var _ALIGN_STEP_I18N = {
  'Half-Cut (pitch=0)': 'align_halfcut',
  'Half-Cut C1 (theta=0)': 'align_halfcut_c1',
  'Set Operating Angle': 'align_set_angle',
  'Rotation Center': 'align_rot_center',
  'Set Bragg': 'align_set_bragg',
  'dTheta2 Coarse': 'align_dtheta2_coarse',
  'dTheta2 Fine': 'align_dtheta2_fine'
};
function _tStep(name) {
  var key = _ALIGN_STEP_I18N[name];
  return key ? _t(key) : name;
}
// ===== alignment/04_align_ui.js -- Alignment Popup UI =====
// @module alignment/04_align_ui
// @exports _ALIGN_STEP_I18N, _alignBpmCenter, _alignPopupDismissed, _alignScanLog, _alignState, _restoreAlignPopupState, _tStep, drawAlignBeamProfile, drawAlignScanInPopup, drawMaBeamProfile, exportAlignScanLog, getAlignScanLog, logAlignScan, openAlignMonitor, openDeviceAlignSetup, ...
// Extracted from 14_v435_final.js (DDD Phase 5e)
// drawMaBeamProfile (v2, half-cut clipping), drawAlignScanInPopup,
// updateAlignProgress, showAlignSummary,
// _alignState, logAlignScan, exportAlignScanLog,
// openMirrorAlignPopup, runMirrorAlignUI, openDeviceAlignSetup,
// closeModal/openModal overrides, modal resize init
// Dependencies: mcBeamWithPitch, beamAt, pos, applyColormap, state, MOTORS,
//   MIRROR_ALIGN_SEQ, ALIGN_CONFIG, openModal, closeModal, _makePopupResizable,
//   log, runMirrorAlign, _isAlignPopupVisible, _showAlignConfirmButtons,
//   drawAlignBeamProfile, updateOptics, renderLayout, syncMotorToState

// ===================================================================
// drawMaBeamProfile v2 -- with half-cut clipping visualization
// ===================================================================
window.drawMaBeamProfile = function(mirrorId, pitch_mrad, detId) {
  var cv = document.getElementById('maMonBeam') || document.getElementById('alignMonBeam');
  if (!cv) return;
  var sz = Math.min(cv.clientWidth || 240, cv.clientHeight || 240);
  if (sz < 50) sz = 240;
  var dw = sz, dh = sz;
  var dpr = Math.max(2, window.devicePixelRatio || 1);
  cv.width = dw * dpr; cv.height = dh * dpr;
  var ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);
  var w = dw, h = dh;
  var _th = typeof _getChartTheme==='function' ? _getChartTheme() : 'dark2';
  var _bgc = _th==='light' ? '#ffffff' : _th==='dark' ? '#000000' : '#0a0f18';
  ctx.fillStyle = _bgc; ctx.fillRect(0,0,w,h);

  var _nR = (typeof MC_NRAYS !== 'undefined') ? MC_NRAYS : 100000;
  var mc = mcBeamWithPitch(mirrorId, pitch_mrad, detId, _nR);
  if (!mc || !mc.hist2d) {
    var bs = beamAt(pos(detId));
    ctx.fillStyle='#40d89a';ctx.font='9px monospace';ctx.textAlign='center';
    ctx.fillText('H:'+bs.h.toFixed(1)+' V:'+bs.v.toFixed(1)+' \u03BCm',w/2,h/2);
    return;
  }
  var G = mc.grid, h2 = mc.hist2d;
  var maxV = 0;
  for(var k=0;k<h2.length;k++) if(h2[k]>maxV) maxV=h2[k];
  if(maxV===0) maxV=1;
  var cw2=w/G, ch2=h/G;

  // Half-cut clipping: ty determines how much beam is blocked
  var clipRow = -1;
  if (state._alignAlgo === 'halfcut' && mc.fwhmV > 0) {
    var ty = state._alignTy || 0;
    var bs2 = beamAt(pos(mirrorId));
    var sigma_mm = bs2.v / 2.355 * 0.001;
    // ty in mm, convert to grid row: center = G/2, sigma maps to ~G/6
    var sigPx = (sigma_mm / (mc.fovV * 2)) * G;
    if (sigPx < 0.5) sigPx = G / 6;
    clipRow = Math.round(G/2 + ty / (sigma_mm * 3) * (G/2));
  }

  // Blue-cyan colormap helper (matches applyColormap 'blue')
  var _maLb = (_th === 'light');
  function _bcRGB(v){
    var r,g,b;
    if(v<0.15){r=0;g=Math.round(v/0.15*60);b=Math.round(v/0.15*180);}
    else if(v<0.45){var t2=(v-0.15)/0.3;r=Math.round(t2*60);g=Math.round(60+t2*160);b=Math.round(180+t2*75);}
    else if(v<0.75){var t2b=(v-0.45)/0.3;r=Math.round(60+t2b*120);g=Math.round(220+t2b*35);b=255;}
    else{var t2c=(v-0.75)/0.25;r=Math.round(180+t2c*75);g=255;b=255;}
    if(_maLb && v<0.5){var wb=1-v/0.5;r=Math.round(r+(255-r)*wb);g=Math.round(g+(255-g)*wb);b=Math.round(b+(255-b)*wb);}
    return'rgb('+r+','+g+','+b+')';
  }
  for(var iy=0;iy<G;iy++) for(var ix=0;ix<G;ix++){
    var t=h2[iy*G+ix]/maxV; if(t<0.01) continue;
    var dispIy = G-1-iy;
    if (clipRow >= 0 && dispIy > clipRow) {
      ctx.fillStyle = 'rgba(80,20,20,0.4)';
      ctx.fillRect(ix*cw2, dispIy*ch2, cw2+1, ch2+1);
      continue;
    }
    ctx.fillStyle=_bcRGB(t);
    ctx.fillRect(ix*cw2, dispIy*ch2, cw2+1, ch2+1);
  }

  // Mirror edge line
  if (clipRow >= 0 && clipRow < G) {
    ctx.strokeStyle='#ff6b6b'; ctx.lineWidth=1.5;
    ctx.beginPath(); ctx.moveTo(0, clipRow*ch2); ctx.lineTo(w, clipRow*ch2); ctx.stroke();
    ctx.fillStyle='#ff6b6b'; ctx.font='8px monospace'; ctx.textAlign='right';
    ctx.fillText('mirror edge', w-2, clipRow*ch2-2);
  }

  // Shift marker for rocking
  if (mc.centerShiftV && state._alignAlgo !== 'halfcut') {
    var shPx = mc.centerShiftV*1000/(mc.fwhmV||100)*h*0.3;
    ctx.strokeStyle='#ffb340';ctx.lineWidth=1;ctx.setLineDash([2,2]);
    ctx.beginPath();ctx.moveTo(0,h/2-shPx);ctx.lineTo(w,h/2-shPx);ctx.stroke();ctx.setLineDash([]);
  }

  ctx.fillStyle=_maLb?'rgba(0,102,170,0.85)':'rgba(255,255,255,0.85)';ctx.font='8px monospace';ctx.textAlign='left';
  ctx.fillText('H:'+mc.fwhmH.toFixed(1)+' V:'+mc.fwhmV.toFixed(1)+' \u03BCm',2,10);
  if(state._alignAlgo==='halfcut') ctx.fillText('ty:'+(state._alignTy||0).toFixed(2)+'mm',2,20);
  else ctx.fillText('shift:'+(mc.centerShiftV*1000).toFixed(1)+'\u03BCm',2,20);
  ctx.fillText('flux:'+mc.flux.toExponential(1),2,30);
};

// ===================================================================
// drawAlignScanInPopup -- Shadow4-style scan chart
// ===================================================================
window.drawAlignScanInPopup = function(cv, pos2, sig, center, label, idx, total) {
  if (!pos2 || pos2.length < 1) {
    if (typeof _drawSpecChart === 'function') _drawSpecChart(cv, [], {});
    return;
  }
  // Build data array
  var data = [];
  for (var i = 0; i < pos2.length; i++) data.push({x: pos2[i], y: sig[i]});
  // Determine x range (SPEC-style fixed axis)
  var as2 = window._alignState;
  var xRange = null;
  if (as2 && as2._scanXMin != null && as2._scanXMax != null
      && pos2[0] >= as2._scanXMin - 0.01 && pos2[0] <= as2._scanXMax + 0.01) {
    xRange = [as2._scanXMin, as2._scanXMax];
  } else if (pos2.length >= 2) {
    var step2 = pos2[1] - pos2[0];
    var nTotal2 = total || pos2.length;
    xRange = [pos2[0], pos2[0] + step2 * (nTotal2 - 1)];
  }
  // Axis labels from _alignState
  var as = window._alignState;
  var xlabel = (as && as._xlabel) ? as._xlabel : '';
  var ylabel = (as && as._ylabel) ? as._ylabel : '';
  _drawSpecChart(cv, data, {
    xRange: xRange,
    xlabel: xlabel,
    ylabel: ylabel,
    title: label || '',
    centerMarker: center,
    showFill: true,
    showDots: true
  });
};

// ===================================================================
// updateAlignProgress -- progress bar update for full-alignment panel
// ===================================================================
window.updateAlignProgress = function(stepIdx, totalSteps, stepName, status) {
  var cont = document.getElementById('alignProgress');
  if (cont) cont.style.display = 'block';
  var bar = document.getElementById('alignProgBar');
  var txt = document.getElementById('alignProgText');
  if (bar) bar.style.width = Math.round((stepIdx + 1) / totalSteps * 100) + '%';
  if (txt) txt.textContent = (stepIdx + 1) + ' / ' + totalSteps + '  ' + stepName;
  if (status === 'done') {
    if (bar) bar.style.background = 'var(--gn)';
  } else if (status === 'fail') {
    if (bar) bar.style.background = 'var(--rd)';
  } else {
    if (bar) bar.style.background = 'var(--am)';
  }
};

// ===================================================================
// showAlignSummary -- display per-device results in alignResultSummary
// ===================================================================
window.showAlignSummary = function(results) {
  var el = document.getElementById('alignResultSummary');
  if (!el) return;
  var lines = [];
  var keys = Object.keys(results);
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i], r = results[k];
    if (!r) { lines.push('<span style="color:var(--rd)">' + k + ': FAIL</span>'); continue; }
    var info = k;
    if (r.center != null) info += ': ' + r.center.toFixed(4);
    if (r.fwhm != null) info += ' (FWHM ' + r.fwhm.toFixed(4) + ')';
    if (r.spot) info += ': ' + r.spot.h.toFixed(0) + 'x' + r.spot.v.toFixed(0) + 'nm';
    if (r.method) info += ' [' + r.method + ']';
    lines.push('<span style="color:var(--gn)">' + info + '</span>');
  }
  el.innerHTML = lines.join('<br>');
};

// ===================================================================
// Alignment popup IIFE -- state, logging, modal overrides, popup UI
// ===================================================================
(function(){

// --- Alignment state tracking (survives popup close/reopen) ---
window._alignState={active:false,completed:false,mid:null,currentStep:0,stepName:'',
  results:[],lastScanPositions:[],lastScanSignals:[],lastScanBeamPos:[],
  _useBeamPos:false,_xlabel:'',_ylabel:'Intensity (a.u.)'};
window._alignPopupDismissed=false;

// --- Alignment scan log (persists across sessions for comparison) ---
window._alignScanLog=window._alignScanLog||[];
window.logAlignScan=function(rec){
  rec.ts=new Date().toISOString();
  rec.energy=state.energy;
  window._alignScanLog.push(rec);
  if(typeof log==='function') log('info','[ScanLog] '+rec.mid+'/'+rec.step+
    ' center='+(rec.center!=null?rec.center.toFixed(4):'N/A')+
    ' pts='+rec.positions.length);
};
window.getAlignScanLog=function(){return window._alignScanLog;};
window.exportAlignScanLog=function(){
  var logs=window._alignScanLog;
  if(!logs.length){log('warn','No scan log entries');return '';}
  var rows=['timestamp\tdevice\tstep\talgo\tmotor\tenergy_keV\tcenter\tnPts\tpositions\tsignals\tbeamPos'];
  for(var i=0;i<logs.length;i++){
    var r=logs[i];
    rows.push([r.ts,r.mid,r.step,r.algo,r.motor,
      r.energy?r.energy.toFixed(3):'',
      r.center!=null?r.center.toFixed(6):'',
      r.positions.length,
      r.positions.map(function(v){return v.toFixed(6);}).join(','),
      r.signals.map(function(v){return v.toFixed(2);}).join(','),
      r.beamPos?r.beamPos.map(function(v){return v.toFixed(6);}).join(','):''
    ].join('\t'));
  }
  var tsv=rows.join('\n');
  // Copy to clipboard if available
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(tsv).then(function(){
      log('info','Scan log copied to clipboard ('+logs.length+' entries)');
    });
  }
  return tsv;
};

// NOTE: closeModal/openModal overrides removed — now inline merged in ui/05_modal.js
// NOTE: Modal resize IIFE removed — now in ui/05_modal.js

// Open multi-step alignment popup (scaled-up 2x for analysis)
// Respects _alignPopupDismissed: won't reopen if user dismissed
window.openMirrorAlignPopup=function(mid){
  if(window._alignPopupDismissed) return;
  var seq=MIRROR_ALIGN_SEQ[mid];
  if(!seq)return;
  var det=seq.det, detD=pos(det).toFixed(1);
  // Flex container -- all sizes relative for proper resize behavior
  var html='<div style="min-height:360px;display:flex;flex-direction:column;height:100%">';
  html+='<div style="display:flex;gap:10px;flex:1;min-height:0">';
  // Left: scan chart (flex, fills available space)
  html+='<div style="flex:1;display:flex;flex-direction:column;min-width:0">';
  html+='<div id="alignStepLabel" data-i18n="align_ready" style="font-size:10px;color:var(--am);margin-bottom:3px;min-height:14px;flex-shrink:0">'+_t('align_ready')+'</div>';
  html+='<canvas id="alignMonScan" width="500" height="240" style="border:1px solid var(--b1);border-radius:4px;width:100%;flex:1;min-height:120px"></canvas>';
  html+='</div>';
  // Right: beam profile (square, JS sizes to match scan chart height)
  html+='<div id="alignBeamCol" style="flex-shrink:0;display:flex;flex-direction:column;width:200px">';
  html+='<div style="font-size:9px;color:var(--t3);margin-bottom:3px;flex-shrink:0">'+_tf('align_beam_at',det,detD)+'</div>';
  html+='<canvas id="alignMonBeam" width="240" height="240" style="border:1px solid var(--b1);border-radius:4px;width:100%;aspect-ratio:1"></canvas>';
  html+='</div></div>';
  // Progress (pre-allocated height)
  html+='<div id="alignMonInfo" data-i18n="align_starting" style="font-size:10px;font-family:var(--mn);color:var(--ac);margin-top:8px;min-height:28px">'+_t('align_starting')+'</div>';
  html+='<div style="display:flex;gap:4px;margin-top:6px;align-items:center">';
  html+='<div style="flex:1"><div class="prog-bar"><div class="prog-fill" id="alignMonProg"></div></div></div>';
  html+='<span id="alignMonPct" style="font-size:9px;color:var(--ac);min-width:34px">0%</span>';
  html+='<button class="sb stop act" onclick="abortAlignment()" data-i18n="align_abort" style="margin-left:6px">'+_t('align_abort')+'</button>';
  html+='<button onclick="exportAlignScanLog()" title="Copy all scan logs to clipboard (TSV)" data-i18n="align_export_log" style="font-size:9px;padding:3px 10px;background:var(--b2);color:var(--ac);border:1px solid var(--b1);border-radius:3px;cursor:pointer;margin-left:4px">'+_t('align_export_log')+'</button></div>';
  // Step list
  html+='<div style="margin-top:8px;font-size:9px">';
  for(var i=0;i<seq.steps.length;i++){
    var s=seq.steps[i];
    html+='<div id="alignStep_'+i+'" style="display:flex;gap:4px;padding:3px 6px;color:var(--t3)">';
    html+='<span style="min-width:16px">'+(i+1)+'.</span>';
    html+='<span style="flex:1">'+_tStep(s.name)+'</span>';
    html+='<span id="alignStepSt_'+i+'" style="min-width:60px;text-align:right">--</span>';
    html+='</div>';
  }
  html+='</div>';
  html+='</div>'; // close min-height container
  openModal(seq.name, html);
  // Initialize canvases with dark background (match in-progress appearance)
  setTimeout(function(){
    var _initDpr=Math.max(2,window.devicePixelRatio||1);
    var scanCv=document.getElementById('alignMonScan');
    if(scanCv){
      var sw=scanCv.clientWidth||500,sh=scanCv.clientHeight||240;
      scanCv.width=sw*_initDpr;scanCv.height=sh*_initDpr;
      var ctx2=scanCv.getContext('2d');ctx2.scale(_initDpr,_initDpr);
      var _th3=typeof _getChartTheme==='function'?_getChartTheme():'dark2';
      var _ct3=typeof _CHART_THEMES!=='undefined'&&_CHART_THEMES[_th3]?_CHART_THEMES[_th3]:null;
      var _wbg=_ct3?_ct3.bg:'#0d1117';
      ctx2.fillStyle=_wbg;ctx2.fillRect(0,0,sw,sh);
      ctx2.fillStyle=_th3==='light'?'rgba(80,100,120,0.5)':'rgba(90,122,154,0.4)';ctx2.font='11px monospace';ctx2.textAlign='center';
      ctx2.fillText(_t('align_scan_waiting'),sw/2,sh/2);
    }
    // Match beam profile column width to scan canvas height (square XBPM)
    var beamCv=document.getElementById('alignMonBeam');
    var beamCol=document.getElementById('alignBeamCol');
    if(beamCv&&scanCv){
      var scanH=scanCv.clientHeight||240;
      if(scanH>100&&beamCol) beamCol.style.width=scanH+'px';
    }
    if(beamCv){
      // Show initial beam profile if available (drawAlignBeamProfile handles HiDPI)
      if(typeof drawAlignBeamProfile==='function'){
        try{drawAlignBeamProfile(det);}catch(e){}
      } else {
        var bw=beamCv.clientWidth||240,bh=beamCv.clientHeight||240;
        beamCv.width=bw*_initDpr;beamCv.height=bh*_initDpr;
        var ctx3=beamCv.getContext('2d');
        var _ebg3=(typeof _getChartTheme==='function'&&_getChartTheme()==='light')?'#fff':(_wbg||'#0d1117');
        ctx3.fillStyle=_ebg3;ctx3.fillRect(0,0,bw*_initDpr,bh*_initDpr);
      }
    }
  },50);
};

// Restore popup UI state from _alignState (for reopen during active alignment)
function _restoreAlignPopupState(mid){
  var as=window._alignState;
  if(!as)return;
  // Handle completed alignment: restore final state
  if(as.completed&&as.results&&as.results.length>0){
    var seq=MIRROR_ALIGN_SEQ[mid];
    if(!seq)return;
    for(var i=0;i<as.results.length;i++){
      var stEl=document.getElementById('alignStepSt_'+i);
      var el=document.getElementById('alignStep_'+i);
      if(stEl&&as.results[i]){
        if(as.results[i].center!=null){
          stEl.textContent=as.results[i].center.toFixed(4);stEl.style.color='var(--gn)';
        }else if(as.results[i].value!=null){
          stEl.textContent=as.results[i].value.toFixed?as.results[i].value.toFixed(3):as.results[i].value;
          stEl.style.color='var(--gn)';
        }else if(as.results[i].pass!=null){
          stEl.textContent=as.results[i].pass?_t('align_pass'):_t('align_fail');
          stEl.style.color=as.results[i].pass?'var(--gn)':'var(--rd)';
        }
      }
      if(el)el.style.color='var(--gn)';
    }
    var info2=document.getElementById('alignMonInfo');
    if(info2){info2.textContent='Alignment complete';info2.style.color='var(--gn)';}
    var progBar=document.getElementById('alignMonProg');
    if(progBar)progBar.style.width='100%';
    return;
  }
  if(!as.active)return;
  var seq=MIRROR_ALIGN_SEQ[mid];
  if(!seq)return;
  // Mark completed steps
  for(var i=0;i<as.results.length;i++){
    var stEl=document.getElementById('alignStepSt_'+i);
    var el=document.getElementById('alignStep_'+i);
    if(stEl&&as.results[i]){
      if(as.results[i].center!=null){
        stEl.textContent=as.results[i].center.toFixed(4);stEl.style.color='var(--gn)';
      }else if(as.results[i].value!=null){
        stEl.textContent=as.results[i].value.toFixed?as.results[i].value.toFixed(3):as.results[i].value;
        stEl.style.color='var(--gn)';
      }else if(as.results[i].pass!=null){
        stEl.textContent=as.results[i].pass?_t('align_pass'):_t('align_fail');
        stEl.style.color=as.results[i].pass?'var(--gn)':'var(--rd)';
      }
    }
    if(el)el.style.color='var(--gn)';
  }
  // Show current step
  var lbl=document.getElementById('alignStepLabel');
  if(lbl)lbl.textContent=as.stepName;
  var curEl=document.getElementById('alignStep_'+as.currentStep);
  if(curEl)curEl.style.color='var(--am)';
  var curSt=document.getElementById('alignStepSt_'+as.currentStep);
  if(curSt){curSt.textContent=_t('align_scanning');curSt.style.color='var(--am)';}
  // Redraw last scan data (raw: beamPos for verify, signals otherwise)
  if(as.lastScanPositions&&as.lastScanPositions.length>1){
    var cv=document.getElementById('alignMonScan');
    var plotData=as._useBeamPos&&as.lastScanBeamPos&&as.lastScanBeamPos.length>0?as.lastScanBeamPos:as.lastScanSignals;
    if(cv)drawAlignScanInPopup(cv,as.lastScanPositions,plotData,null,as.stepName);
  }
  // If waiting for user confirmation, show buttons
  if(window._alignStepResolve&&window._alignWaitingStep){
    _showAlignConfirmButtons(window._alignWaitingStep,window._lastAlignResult||{});
  }
}

// Run full mirror/DCM alignment with UI
window.runMirrorAlignUI=async function(mid,opts){
  opts=opts||{};
  window._alignPopupDismissed=false; // User explicitly requested -> clear dismissed flag
  // Re-open: if same mid is already aligning, just re-show popup
  var as=window._alignState;
  if(as&&as.active&&as.mid===mid){
    openMirrorAlignPopup(mid);
    setTimeout(function(){_restoreAlignPopupState(mid);},50);
    return;
  }
  if(!opts.skipGuard&&state.aligning)return;
  state.aligning=true;
  state._alignAborted=false;
  // Initialize alignment state
  as=window._alignState;
  as.active=true; as.completed=false; as.mid=mid; as.currentStep=0; as.stepName='';
  as.results=[]; as.lastScanPositions=[]; as.lastScanSignals=[]; as.lastScanBeamPos=[];
  as._useBeamPos=false; as._xlabel=''; as._ylabel='Intensity (a.u.)';
  openMirrorAlignPopup(mid);
  await (typeof _yieldAsync==='function'?_yieldAsync():new Promise(function(r){setTimeout(r,0);}));
  var seq=MIRROR_ALIGN_SEQ[mid];
  // Save pre-alignment motor state for restore
  var _savedMotors = {};
  if(MOTORS[mid]){
    var mDev = MOTORS[mid];
    for(var ax in mDev){
      if(mDev[ax] && mDev[ax].value !== undefined)
        _savedMotors[ax] = mDev[ax].value;
    }
  }
  try{
    var results=await runMirrorAlign(mid,
      // onStepStart
      function(si,total,step){
        as.currentStep=si;as.stepName=_tf('align_step_fmt',si+1,total,_tStep(step.name));
        as.lastScanPositions=[];as.lastScanSignals=[];as.lastScanBeamPos=[];
        // Determine axis labels and data type per scan algo
        var mObj=null;
        if(typeof MOTORS!=='undefined'&&MOTORS[mid]){
          // Try direct key first, then strip groupId prefix (e.g. 'y1' for dcm)
          mObj=MOTORS[mid][step.motor]||null;
        }
        var mUnit=step.unit||(mObj?mObj.unit:'');
        var mName=step.axisLabel||(mObj?mObj.name:step.motor);
        as._xlabel=mName+(mUnit?' ('+mUnit+')':'');
        as._useBeamPos=((step.algo==='rocking'||step.algo==='verify'||step.algo==='rot_center'||step.algo==='verify_pos')&&mid!=='dcm');
        as._ylabel=as._useBeamPos?'Beam Position (mm)':'Intensity (a.u.)';
        var lbl2=document.getElementById('alignStepLabel');
        if(lbl2)lbl2.textContent=as.stepName;
        var el2=document.getElementById('alignStep_'+si);
        if(el2)el2.style.color='var(--am)';
        var st=document.getElementById('alignStepSt_'+si);
        if(st){st.textContent=_t('align_scanning');st.style.color='var(--am)';}
      },
      // onPoint
      function(si,i,nPts,p,sig2,bp,positions,signals,beamPos2){
        // Track scan data in state (for reopen)
        as.lastScanPositions=positions.slice();
        as.lastScanSignals=signals.slice();
        as.lastScanBeamPos=beamPos2?beamPos2.slice():[];
        // Always plot raw measured data (signals or beamPos for verify)
        var plotData=as._useBeamPos&&beamPos2&&beamPos2.length>0?beamPos2:signals;
        // Scan chart (only if popup visible)
        if(_isAlignPopupVisible()){
          var cv=document.getElementById('alignMonScan');
          if(cv&&positions.length>1)
            drawAlignScanInPopup(cv,positions,plotData,null,
              seq.steps[si].name+' ('+(i+1)+'/'+nPts+')',i,nPts);
          // Beam profile
          if(typeof drawAlignBeamProfile==='function')
            drawAlignBeamProfile(seq.det);
          // Info -- show relevant value per scan type
          var info=document.getElementById('alignMonInfo');
          if(info){
            if(as._useBeamPos)
              info.textContent=_tf('align_motor_fmt',p.toFixed(4))+'  '+_tf('align_centroid_fmt',bp.toFixed(4))+'  ['+(i+1)+'/'+nPts+']';
            else
              info.textContent=_tf('align_motor_fmt',p.toFixed(4))+'  '+_tf('align_intensity_fmt',sig2.toFixed(0))+'  ['+(i+1)+'/'+nPts+']';
          }
          // Progress
          var totalPts=0,donePts=0;
          for(var k=0;k<seq.steps.length;k++){
            var n=seq.steps[k].nPts||1;
            totalPts+=n;
            if(k<si)donePts+=n;
            else if(k===si)donePts+=(i+1);
          }
          var pct=(donePts/totalPts*100).toFixed(0);
          var pg=document.getElementById('alignMonProg');
          if(pg)pg.style.width=pct+'%';
          var pc=document.getElementById('alignMonPct');
          if(pc)pc.textContent=pct+'%';
          // On last scan point: compute center + redraw chart with marker + update step status
          if(i===nPts-1){
            var step2=seq.steps[si];
            var stEl=document.getElementById('alignStepSt_'+si);
            var foundCenter=null,resText='';
            if(step2.algo==='halfcut'){
              // Use same fitting as 03_runners: boxerf for WB (m1,dcm), halfcut for mono
              var _isWB=(mid==='m1'||mid==='dcm');
              var _hcAlgo=_isWB?'boxerf':'halfcut';
              try{
                var _hcA=analyzeAlignScan(positions,signals,_hcAlgo);
                foundCenter=_hcA.center;
                resText=foundCenter!=null?foundCenter.toFixed(4)+' ('+_hcAlgo+')':'N/A';
              }catch(e){foundCenter=null;resText='fit err';}
            } else if(step2.algo==='rocking'){
              // Use same fitting as 03_runners: lorentzian for DCM, gaussian for mirrors
              var _rcAlgo=(mid==='dcm')?'rocking':'gaussian';
              try{
                var _rcA=analyzeAlignScan(positions,signals,_rcAlgo);
                foundCenter=_rcA.center;
                resText=foundCenter!=null?foundCenter.toFixed(4):'N/A';
              }catch(e){foundCenter=null;resText='fit err';}
            } else if(step2.algo==='verify'||step2.algo==='verify_pos'){
              if(as._useBeamPos&&beamPos2&&beamPos2.length>0){
                var bMin=Infinity,bMax=-Infinity;
                for(var j4=0;j4<beamPos2.length;j4++){if(beamPos2[j4]<bMin)bMin=beamPos2[j4];if(beamPos2[j4]>bMax)bMax=beamPos2[j4];}
                var drift=(bMax-bMin);
                resText='drift='+drift.toFixed(4)+' '+(drift<0.01?_t('align_pass'):_t('align_fail'));
              } else {
                var bMin2=Infinity,bMax2=-Infinity;
                for(var j5=0;j5<signals.length;j5++){if(signals[j5]<bMin2)bMin2=signals[j5];if(signals[j5]>bMax2)bMax2=signals[j5];}
                resText='var='+(((bMax2-bMin2)/bMax2)*100).toFixed(1)+'%';
              }
            } else if(step2.algo==='rot_center'){
              // rot_center: show beam position drift (linear fit slope)
              if(as._useBeamPos&&beamPos2&&beamPos2.length>0){
                var bMin3=Infinity,bMax3=-Infinity;
                for(var j6=0;j6<beamPos2.length;j6++){if(beamPos2[j6]<bMin3)bMin3=beamPos2[j6];if(beamPos2[j6]>bMax3)bMax3=beamPos2[j6];}
                var drift3=(bMax3-bMin3);
                resText='drift='+drift3.toFixed(4)+'mm';
              }
            }
            // Redraw chart with center marker
            if(cv&&foundCenter!=null)
              drawAlignScanInPopup(cv,positions,plotData,foundCenter,
                seq.steps[si].name+' (done)',i,nPts);
            // Update step status immediately
            if(stEl&&resText){stEl.textContent=resText;stEl.style.color='var(--gn)';}
            var elRow=document.getElementById('alignStep_'+si);
            if(elRow)elRow.style.color='var(--gn)';
            // Save scan to log for later comparison
            if(typeof logAlignScan==='function')
              logAlignScan({mid:mid,step:step2.name,algo:step2.algo,motor:step2.motor,
                positions:positions.slice(),signals:signals.slice(),
                beamPos:beamPos2?beamPos2.slice():[],center:foundCenter,result:resText});
          }
        }
        // Layout update always (even when popup closed)
        try{if(typeof updateOptics==='function')updateOptics();}catch(e){}
        try{if(typeof renderLayout==='function')renderLayout();}catch(e){}
      }
    );
    // Store results in state
    as.results=results||[];
    // Mark step results in popup (if visible)
    if(results&&_isAlignPopupVisible()){
      for(var r=0;r<results.length;r++){
        var st2=document.getElementById('alignStepSt_'+r);
        var el3=document.getElementById('alignStep_'+r);
        if(st2&&results[r]){
          if(results[r].center!=null){
            st2.textContent=results[r].center.toFixed(4);
            st2.style.color='var(--gn)';
          }else if(results[r].value!=null){
            st2.textContent=results[r].value.toFixed?results[r].value.toFixed(3):results[r].value;
            st2.style.color='var(--gn)';
          }else if(results[r].pass!=null){
            st2.textContent=results[r].pass?_t('align_pass'):_t('align_fail');
            st2.style.color=results[r].pass?'var(--gn)':'var(--rd)';
          }
        }
        if(el3)el3.style.color='var(--gn)';
      }
      var info2=document.getElementById('alignMonInfo');
      if(info2){
        info2.textContent='Alignment complete';info2.style.color='var(--gn)';
        // Add explicit Close button so user knows alignment is done
        var closeBtn=document.createElement('button');
        closeBtn.textContent='Close';
        closeBtn.className='sb';
        closeBtn.style.cssText='font-size:9px;padding:3px 12px;margin-left:8px;background:var(--s2);color:var(--t1);border:1px solid var(--b1);border-radius:3px;cursor:pointer';
        closeBtn.onclick=function(){closeModal();};
        info2.parentElement.appendChild(closeBtn);
      }
      // Progress bar to 100%
      var progBar=document.getElementById('alignMonProg');
      if(progBar)progBar.style.width='100%';
      as.completed=true;
    }
    // After successful alignment: keep aligned positions (halfcut center,
    // rotation center corrections, etc.) -- only ensure pitch is at operating angle.
    // Do NOT restore deflection/translation axes to pre-alignment values.
    // Alignment already sets correct pitch in Step 3 (Set Operating Angle)
    // and Step 4 (Rotation Center) restores it. No need to override here.
    // Just sync UI with current motor state.
    if(MOTORS[mid]&&MOTORS[mid].pitch){
      var stKeyMap={m1:'m1pitch',m2:'m2pitch',kbv:'kbvpitch',kbh:'kbhpitch'};
      var sk=stKeyMap[mid];
      var finalPitch=MOTORS[mid].pitch.value;
      if(sk) state[sk]=finalPitch;
      try{
        if(mid==='m1'&&typeof updateM1==='function')updateM1(finalPitch);
        if(mid==='m2'&&typeof updateM2==='function')updateM2(finalPitch);
      }catch(e){}
    }
  }catch(e){
    var info3=document.getElementById('alignMonInfo');
    if(info3){info3.textContent='ERROR: '+e.message;info3.style.color='var(--rd)';}
    // Restore motors on error too
    if(MOTORS[mid]){
      for(var ax3 in _savedMotors) MOTORS[mid][ax3].value = _savedMotors[ax3];
      var stKeyMap2={m1:'m1pitch',m2:'m2pitch',kbv:'kbvpitch',kbh:'kbhpitch'};
      var _errNomPitch=(mid==='m1'||mid==='m2')?2.5:3.0;
      var sk2=stKeyMap2[mid]; if(sk2)state[sk2]=_savedMotors.pitch||_errNomPitch;
      try{
        if(mid==='m1'&&typeof updateM1==='function')updateM1(state.m1pitch);
        if(mid==='m2'&&typeof updateM2==='function')updateM2(state.m2pitch);
      }catch(e2){}
    }
  }
  as.active=false; as.mid=null;
  // Only reset aligning if standalone call (not inside runFullAlignment)
  if (!opts.skipGuard) state.aligning=false;
  window._alignBpmCenter=null; // reset BPM pan
  // Alignment changed motor positions → recalculate beam
  if(typeof _invalidateMCCache==='function') _invalidateMCCache();
  if(typeof updateLiveBeamInfo==='function') try{updateLiveBeamInfo();}catch(e){}
};

console.log('[alignment/04_align_ui] Align popup loaded (background + reopen)');
})();

// ===================================================================
// Per-Device Scan Setup Dialog
// ===================================================================
window.openDeviceAlignSetup = function(key) {
  var existing = document.getElementById('_devAlignSetup');
  if (existing) existing.remove();
  var isMirror = !!MIRROR_ALIGN_SEQ[key];
  var rows = [];
  if (isMirror) {
    var seq = MIRROR_ALIGN_SEQ[key];
    seq.steps.forEach(function(st, i) {
      rows.push({idx:i, name:st.name, motor:st.motor, range:st.range?st.range.slice():null,
        nPts:st.nPts||0, target:st.target, algo:st.algo, editable:!st.target});
    });
  } else if (ALIGN_CONFIG[key]) {
    var cfg = ALIGN_CONFIG[key];
    rows.push({idx:0, name:cfg.label, motor:cfg.motor, range:cfg.range.slice(),
      nPts:cfg.nPts, target:null, algo:cfg.algo, editable:true});
  } else { return; }

  var overlay = document.createElement('div');
  overlay.id = '_devAlignSetup';
  overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center';
  var box = document.createElement('div');
  box.style.cssText = 'background:var(--bg,#0a0f18);border:1px solid var(--bd,#2a3040);border-radius:8px;padding:0;min-width:480px;max-width:92vw;max-height:90vh;color:var(--t1,#e0e0e0);font-family:monospace;overflow:auto;zoom:var(--ui-zoom,1.8)';
  var title = isMirror ? MIRROR_ALIGN_SEQ[key].name : ALIGN_CONFIG[key].label;
  // Draggable title bar
  var hdr = document.createElement('div');
  hdr.style.cssText = 'display:flex;align-items:center;padding:12px 18px;background:var(--s1,#151f2e);border-bottom:1px solid var(--b0,rgba(80,160,255,.06));border-radius:8px 8px 0 0';
  hdr.innerHTML = '<span style="font-size:15px;font-weight:600;color:var(--gn,#40d89a);flex:1">' + title + ' \u2014 Scan Setup</span><span style="font-size:9px;color:var(--t3,#3d5068)">drag to move</span>';
  box.appendChild(hdr);
  // Content area
  var cArea = document.createElement('div');
  cArea.style.cssText = 'padding:16px 20px';
  box.appendChild(cArea);

  // Table
  var tbl = '<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:14px">';
  tbl += '<tr style="color:var(--t2,#9ca3af);border-bottom:2px solid var(--bd,#2a3040)">';
  tbl += '<th style="text-align:left;padding:6px 10px">Step</th>';
  tbl += '<th style="text-align:left;padding:6px 10px">Motor</th>';
  tbl += '<th style="text-align:center;padding:6px 10px">Range Min</th>';
  tbl += '<th style="text-align:center;padding:6px 10px">Range Max</th>';
  tbl += '<th style="text-align:center;padding:6px 10px">Points</th>';
  tbl += '<th style="text-align:center;padding:6px 10px">Algo</th></tr>';
  rows.forEach(function(r) {
    tbl += '<tr style="border-bottom:1px solid var(--s2,#1a2030)">';
    tbl += '<td style="padding:6px 10px;color:var(--t1)">' + r.name + '</td>';
    tbl += '<td style="padding:6px 10px;color:var(--am,#ffb340)">' + r.motor + '</td>';
    if (r.editable && r.range) {
      tbl += '<td style="padding:5px 6px;text-align:center"><input id="_das_min_'+r.idx+'" type="number" step="any" value="'+r.range[0]+'" style="width:100px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:13px;text-align:center;padding:4px"></td>';
      tbl += '<td style="padding:5px 6px;text-align:center"><input id="_das_max_'+r.idx+'" type="number" step="any" value="'+r.range[1]+'" style="width:100px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:13px;text-align:center;padding:4px"></td>';
      tbl += '<td style="padding:5px 6px;text-align:center"><input id="_das_npt_'+r.idx+'" type="number" min="3" max="201" value="'+r.nPts+'" style="width:70px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:13px;text-align:center;padding:4px"></td>';
    } else {
      var val = r.target != null ? ('target=' + r.target) : '--';
      tbl += '<td colspan="3" style="padding:6px 10px;text-align:center;color:var(--t3)">' + val + '</td>';
    }
    tbl += '<td style="padding:6px 10px;text-align:center;color:var(--t3);font-size:11px">' + (r.algo||'--') + '</td>';
    tbl += '</tr>';
  });
  tbl += '</table>';
  var h = tbl;

  // Extra fields for WB Slit / SSA: scan gap size
  if (key === 'wbslit' || key === 'wbslit_v' || key === 'ssacenter' || key === 'ssacenter_v') {
    var isSSA = (key === 'ssacenter' || key === 'ssacenter_v');
    var gapUnit = isSSA ? 'μm' : 'mm';
    var gapStep = isSSA ? '1' : '0.01';
    var gapMin = isSSA ? '1' : '0.01';
    var gapDefault = isSSA ? 'beam/4' : 'beam/10';
    var curGap = ALIGN_CONFIG[key].scanGap;
    var gapVal = (curGap != null && curGap > 0) ? curGap : '';
    h += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;font-size:13px">'
      + '<span style="color:var(--t2)">Scan Gap (' + gapUnit + '):</span>'
      + '<input id="_das_gap" type="number" step="' + gapStep + '" min="' + gapMin + '" value="' + gapVal + '" placeholder="auto (' + gapDefault + ')" '
      + 'style="width:100px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:13px;text-align:center;padding:4px">'
      + '<span style="color:var(--t3)">empty = auto (1/' + (isSSA?'4':'10') + ' beam FWHM)</span></div>';
  }

  // Extra fields for KB alignment: SSA gap during alignment
  if (key === 'kbv' || key === 'kbh') {
    var kbCfg = ALIGN_CONFIG.kbalign || {};
    var kbSsaH = kbCfg.ssaGapH != null ? kbCfg.ssaGapH : 100;
    var kbSsaV = kbCfg.ssaGapV != null ? kbCfg.ssaGapV : 100;
    h += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;font-size:13px">'
      + '<span style="color:var(--t2)">SSA H-Gap (μm):</span>'
      + '<input id="_das_kbssah" type="number" step="1" min="1" max="500" value="' + kbSsaH + '" '
      + 'style="width:80px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:13px;text-align:center;padding:4px">'
      + '<span style="color:var(--t2);margin-left:10px">V-Gap (μm):</span>'
      + '<input id="_das_kbssav" type="number" step="1" min="1" max="500" value="' + kbSsaV + '" '
      + 'style="width:80px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:13px;text-align:center;padding:4px">'
      + '<span style="color:var(--t3)">SSA opens to this gap during KB alignment</span></div>';
  }

  // Buttons
  h += '<div style="display:flex;gap:10px;justify-content:flex-end;margin-top:6px">'
    + '<button id="_dasCancel" class="sb" style="font-size:12px;padding:6px 20px">Cancel</button>'
    + '<button id="_dasApply" class="sb" style="font-size:12px;padding:6px 20px;background:var(--bl,#4db8ff);color:#000">Apply</button>'
    + '<button id="_dasRun" class="sb" style="font-size:12px;padding:6px 20px;background:var(--gn,#40d89a);color:#000;font-weight:600">Apply & Run</button>'
    + '</div>';
  cArea.innerHTML = h;
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  window._makePopupResizable(box, {minWidth:480, dragEl:hdr});
  overlay.addEventListener('mousedown', function(e) { if (e.target === overlay) overlay.remove(); });

  function applyValues() {
    rows.forEach(function(r) {
      if (!r.editable) return;
      var minEl = document.getElementById('_das_min_' + r.idx);
      var maxEl = document.getElementById('_das_max_' + r.idx);
      var nptEl = document.getElementById('_das_npt_' + r.idx);
      if (!minEl) return;
      var mn = parseFloat(minEl.value), mx = parseFloat(maxEl.value), np = parseInt(nptEl.value);
      if (isNaN(mn) || isNaN(mx) || isNaN(np) || np < 3) return;
      if (isMirror) {
        MIRROR_ALIGN_SEQ[key].steps[r.idx].range = [mn, mx];
        MIRROR_ALIGN_SEQ[key].steps[r.idx].nPts = np;
      } else {
        ALIGN_CONFIG[key].range = [mn, mx];
        ALIGN_CONFIG[key].nPts = np;
      }
    });
    // WB Slit / SSA gap
    if (key === 'wbslit' || key === 'wbslit_v' || key === 'ssacenter' || key === 'ssacenter_v') {
      var gapEl = document.getElementById('_das_gap');
      if (gapEl) {
        var gv = parseFloat(gapEl.value);
        ALIGN_CONFIG[key].scanGap = (isNaN(gv) || gv <= 0) ? null : gv;
      }
    }
    // KB SSA gap
    if (key === 'kbv' || key === 'kbh') {
      var shEl = document.getElementById('_das_kbssah');
      var svEl = document.getElementById('_das_kbssav');
      if (ALIGN_CONFIG.kbalign) {
        if (shEl) { var v = parseFloat(shEl.value); if (!isNaN(v) && v >= 1) ALIGN_CONFIG.kbalign.ssaGapH = v; }
        if (svEl) { var v2 = parseFloat(svEl.value); if (!isNaN(v2) && v2 >= 1) ALIGN_CONFIG.kbalign.ssaGapV = v2; }
      }
    }
    log('info', 'Scan setup applied: ' + key);
  }

  document.getElementById('_dasCancel').onclick = function() { overlay.remove(); };
  document.getElementById('_dasApply').onclick = function() { applyValues(); overlay.remove(); };
  document.getElementById('_dasRun').onclick = function() {
    applyValues(); overlay.remove();
    if (isMirror) { runMirrorAlignUI(key); }
    else { runAlignStepUI(key); }
  };
};

// ===================================================================
// openAlignMonitor -- monitoring popup for per-device strategy scans
// ===================================================================
window.openAlignMonitor = function(key) {
  var cfg = ALIGN_CONFIG[key], s = ALIGN_STRATEGIES[key];
  if (!cfg || !s) return;
  var detPos = pos(cfg.detector).toFixed(1);
  var html = '<div style="min-height:260px;display:flex;flex-direction:column;height:100%">';
  html += '<div style="display:flex;gap:8px;flex:1;min-height:0">';
  // Left: scan curve
  html += '<div style="flex:1;display:flex;flex-direction:column;min-width:0">';
  html += '<div style="font-size:9px;color:var(--t3);margin-bottom:2px;flex-shrink:0">Scan Curve (' + cfg.algo + ')</div>';
  html += '<canvas id="alignMonScan" width="400" height="200" style="border:1px solid var(--b1);border-radius:4px;width:100%;flex:1;min-height:100px"></canvas>';
  html += '</div>';
  // Right: beam profile (square, JS sizes to match scan chart height)
  html += '<div id="alignBeamCol" style="flex-shrink:0;display:flex;flex-direction:column;width:200px">';
  html += '<div style="font-size:9px;color:var(--t3);margin-bottom:2px;flex-shrink:0">Beam @ ' + cfg.detector + ' (' + detPos + 'm)</div>';
  html += '<canvas id="alignMonBeam" width="200" height="200" style="border:1px solid var(--b1);border-radius:4px;width:100%;aspect-ratio:1"></canvas>';
  html += '</div></div>';
  // Info bar
  html += '<div id="alignMonInfo" style="font-size:10px;font-family:var(--mn);color:var(--am);margin-top:6px;min-height:24px">Initializing...</div>';
  html += '<div style="display:flex;gap:4px;margin-top:4px;align-items:center">';
  html += '<div style="flex:1"><div class="prog-bar"><div class="prog-fill" id="alignMonProg"></div></div></div>';
  html += '<span id="alignMonPct" style="font-size:9px;color:var(--ac);min-width:30px">0%</span>';
  html += '<button onclick="abortAlignment()" style="font-size:9px;padding:3px 10px;background:var(--rd);color:#fff;border:none;border-radius:3px;cursor:pointer;margin-left:6px" data-i18n="align_abort">' + _t('align_abort') + '</button>';
  html += '</div>';
  // Parameters summary
  html += '<div style="font-size:8px;color:var(--t3);margin-top:4px">Motor: ' + cfg.motor + ' | Range: [' + cfg.range[0] + ', ' + cfg.range[1] + '] ' + cfg.unit + ' | Points: ' + cfg.nPts + ' | Detector: ' + cfg.detector + '</div>';
  html += '</div>';
  openModal('Alignment: ' + s.name, html);
  // Initialize canvases (HiDPI)
  setTimeout(function(){
    var _initDpr2=Math.max(2,window.devicePixelRatio||1);
    var scanCv = document.getElementById('alignMonScan');
    if (scanCv) {
      var sw2=scanCv.clientWidth||400,sh2=scanCv.clientHeight||200;
      scanCv.width=sw2*_initDpr2;scanCv.height=sh2*_initDpr2;
      var ctx2 = scanCv.getContext('2d'); ctx2.scale(_initDpr2,_initDpr2);
      var _th3 = typeof _getChartTheme === 'function' ? _getChartTheme() : 'dark2';
      var _ct3 = typeof _CHART_THEMES !== 'undefined' && _CHART_THEMES[_th3] ? _CHART_THEMES[_th3] : null;
      var _wbg = _ct3 ? _ct3.bg : '#0d1117';
      ctx2.fillStyle = _wbg; ctx2.fillRect(0, 0, sw2, sh2);
      ctx2.fillStyle = _th3 === 'light' ? 'rgba(80,100,120,0.5)' : 'rgba(90,122,154,0.4)';
      ctx2.font = '11px monospace'; ctx2.textAlign = 'center';
      ctx2.fillText(_t('align_scan_waiting'), sw2 / 2, sh2 / 2);
    }
    // Match beam profile column width to scan canvas height (square XBPM)
    var beamCv = document.getElementById('alignMonBeam');
    var beamCol2 = document.getElementById('alignBeamCol');
    if (beamCv && scanCv) {
      var scanH2 = scanCv.clientHeight || 200;
      if (scanH2 > 100 && beamCol2) beamCol2.style.width = scanH2 + 'px';
    }
    if (beamCv) {
      if (typeof drawAlignBeamProfile === 'function') {
        try { drawAlignBeamProfile(cfg.detector); } catch(e) {}
      } else {
        var bw2=beamCv.clientWidth||200,bh2=beamCv.clientHeight||200;
        beamCv.width=bw2*_initDpr2;beamCv.height=bh2*_initDpr2;
        var ctx3=beamCv.getContext('2d');
        var _ebg4=(typeof _getChartTheme==='function'&&_getChartTheme()==='light')?'#fff':(_wbg||'#0d1117');
        ctx3.fillStyle=_ebg4;ctx3.fillRect(0,0,bw2*_initDpr2,bh2*_initDpr2);
      }
    }
  }, 50);
};

// ===================================================================
// runAlignStepUI -- run a single per-device alignment strategy with UI
// ===================================================================
window.runAlignStepUI = async function(key, opts) {
  opts = opts || {};
  if (!opts.skipGuard && state.aligning) return;
  var cfg = ALIGN_CONFIG[key];
  if (!cfg) return;
  var strat = ALIGN_STRATEGIES[key];
  if (!strat) { log('err', 'No strategy for ' + key); return; }
  // Open monitoring popup
  openAlignMonitor(key);
  var el = document.getElementById('alignSt_' + key);
  if (el) { el.textContent = 'scanning...'; el.style.color = 'var(--am)'; }
  state.aligning = true;
  // Set axis labels for single-step alignment
  var as2=window._alignState||(window._alignState={});
  var mObj2=null;
  if(typeof MOTORS!=='undefined'){
    var parts=cfg.motor.split('_');
    if(parts.length===2&&MOTORS[parts[0]]) mObj2=MOTORS[parts[0]][parts[1]]||null;
  }
  as2._xlabel=(mObj2?mObj2.name:cfg.motor)+(cfg.unit?' ('+cfg.unit+')':'');
  as2._ylabel=(cfg.algo==='centroid')?'Beam Position ('+cfg.unit+')':'Intensity (a.u.)';
  try {
    var result = await strat.run(function(i, n, p, s, positions, signals) {
      // Update scan chart in popup
      if (typeof drawAlignResult === 'function') {
        try { drawAlignResult(positions, signals, null, strat.name + ' (' + (i + 1) + '/' + n + ')'); } catch(e) {}
      }
      // Also draw in popup's scan canvas
      var scanCv = document.getElementById('alignMonScan');
      if (scanCv) drawAlignScanInPopup(scanCv, positions, signals, null, strat.name, i, n);
      // Update beam profile at detector
      if (typeof drawAlignBeamProfile === 'function') {
        try { drawAlignBeamProfile(cfg.detector); } catch(e) {}
      }
      // Update info
      var info = document.getElementById('alignMonInfo');
      if (info) info.textContent = 'Pos=' + p.toFixed(4) + ' ' + cfg.unit + '  Signal=' + s.toExponential(2) + '  [' + (i + 1) + '/' + n + ']';
      var pg = document.getElementById('alignMonProg');
      if (pg) pg.style.width = ((i + 1) / n * 100).toFixed(0) + '%';
      var pc = document.getElementById('alignMonPct');
      if (pc) pc.textContent = ((i + 1) / n * 100).toFixed(0) + '%';
      // SVG update
      if (typeof updateOptics === 'function') try { updateOptics(); } catch(e) {}
      if (typeof renderLayout === 'function') try { renderLayout(); } catch(e) {}
    });
    if (result) {
      var scanCv = document.getElementById('alignMonScan');
      if (scanCv && result.positions) drawAlignScanInPopup(scanCv, result.positions, result.signals, result.center, strat.name + ' DONE', cfg.nPts, cfg.nPts);
      if (typeof drawAlignBeamProfile === 'function') {
        try { drawAlignBeamProfile(cfg.detector); } catch(e) {}
      }
      var info = document.getElementById('alignMonInfo');
      if (info) { info.textContent = 'Complete: center=' + (result.center || 0).toFixed(4) + ' ' + cfg.unit + (result.fwhm ? '  FWHM=' + result.fwhm.toFixed(4) : ''); info.style.color = 'var(--gn)'; }
      if (el) { el.textContent = (result.center || 0).toFixed(3); el.style.color = 'var(--gn)'; }
    }
  } catch (e) {
    log('err', 'Align ' + key + ': ' + e.message);
    if (el) { el.textContent = 'FAIL'; el.style.color = 'var(--rd)'; }
    var info = document.getElementById('alignMonInfo');
    if (info) { info.textContent = 'ERROR: ' + e.message; info.style.color = 'var(--rd)'; }
  }
  // Only reset aligning if this was a standalone call (not inside runFullAlignment)
  if (!opts.skipGuard) state.aligning = false;
};

// === drawAlignBeamProfile: MC beam profile on alignment monitor canvas ===
// Extracted from 13_alignment.js
window.drawAlignBeamProfile = function(detId) {
  var cv = document.getElementById('alignMonBeam');
  if (!cv) return;
  var sz = Math.min(cv.clientWidth || 200, cv.clientHeight || 200);
  if (sz < 50) sz = 200;
  var dw = sz, dh = sz;
  var dpr = Math.max(2, window.devicePixelRatio || 1);
  cv.width = dw * dpr; cv.height = dh * dpr;
  var ctx = cv.getContext('2d');
  var w = dw, h = dh;
  var imgW = Math.round(dw * dpr), imgH = Math.round(dh * dpr);
  // Theme-aware: match drawMCHist2D style
  var _abTh = typeof _getChartTheme==='function' ? _getChartTheme() : 'light';
  var _abBg = _abTh==='dark' ? '#000' : _abTh==='dark2' ? '#0a0f18' : '#fff';
  var _abLb = (_abTh==='light');
  ctx.fillStyle = _abBg; ctx.fillRect(0, 0, imgW, imgH);
  var d = pos(detId);
  var nR = (typeof MC_NRAYS !== 'undefined') ? MC_NRAYS : 100000;
  var mc = (typeof mcRayTrace === 'function') ? mcRayTrace(d, nR) : null;
  if (!mc || mc.nSurvived < 10 || !mc.hist2d) {
    ctx.scale(dpr, dpr);
    ctx.fillStyle = 'rgba(255,80,80,0.7)'; ctx.font = '11px monospace'; ctx.textAlign = 'center';
    ctx.fillText('No beam', w / 2, h / 2);
    return;
  }
  var G = mc.grid, h2 = mc.hist2d;
  var maxV = 0;
  for (var k = 0; k < h2.length; k++) if (h2[k] > maxV) maxV = h2[k];
  if (maxV === 0) maxV = 1;
  var img = ctx.createImageData(imgW, imgH);
  for (var py = 0; py < imgH; py++) {
    var gy = Math.floor(py / imgH * G);
    for (var px = 0; px < imgW; px++) {
      var gx = Math.floor(px / imgW * G);
      var v = h2[gy * G + gx] / maxV;
      if (typeof applyColormap === 'function') applyColormap(img.data, (py * imgW + px) * 4, v, 'blue', _abLb);
    }
  }
  ctx.putImageData(img, 0, 0);
  // Overlay: scale context for logical coordinates
  ctx.save(); ctx.scale(dpr, dpr);
  var _abCross = _abLb ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.12)';
  var _abText = _abLb ? 'rgba(0,102,170,0.85)' : 'rgba(77,184,255,0.85)';
  ctx.strokeStyle = _abCross; ctx.lineWidth = 0.5;
  ctx.setLineDash([2, 3]);
  ctx.beginPath(); ctx.moveTo(w / 2, 0); ctx.lineTo(w / 2, h); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = _abText; ctx.font = 'bold 9px monospace'; ctx.textAlign = 'left';
  ctx.fillText('H:' + (mc.fwhmH * 1e6).toFixed(1) + '\u03BCm V:' + (mc.fwhmV * 1e6).toFixed(1) + '\u03BCm', 3, 12);
  ctx.fillText(mc.nSurvived + '/' + mc.nTotal + ' rays', 3, 24);
  // Draw BPM FOV boundary overlay (fixed coordinate, centered at optical axis)
  if (typeof _pzROI_display !== 'undefined' && _pzROI_display && mc.fovH > 0) {
    var roi = _pzROI_display;
    var fovH = mc.fovH, fovV = mc.fovV;
    // Match histogram center (may be shifted during alignment)
    var cx = (typeof window._alignBpmCenter==='number') ? window._alignBpmCenter : 0;
    var cy = 0;
    ctx.strokeStyle = 'rgba(255,180,0,0.8)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    var x0 = 0, x1 = w, y0 = 0, y1 = h;
    if (roi.xMin != null) x0 = Math.max(0, (roi.xMin - cx + fovH) / (2 * fovH) * w);
    if (roi.xMax != null) x1 = Math.min(w, (roi.xMax - cx + fovH) / (2 * fovH) * w);
    if (roi.yMin != null) y1 = Math.min(h, h - (roi.yMin - cy + fovV) / (2 * fovV) * h);
    if (roi.yMax != null) y0 = Math.max(0, h - (roi.yMax - cy + fovV) / (2 * fovV) * h);
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(255,180,0,0.7)';
    ctx.font = 'bold 8px monospace';
    ctx.fillText('FOV', x0 + 2, y0 + 9);
  }
  ctx.restore();
};

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _ALIGN_STEP_I18N!=="undefined")globalThis._ALIGN_STEP_I18N=_ALIGN_STEP_I18N;
if(typeof _alignBpmCenter!=="undefined")globalThis._alignBpmCenter=_alignBpmCenter;
if(typeof _alignPopupDismissed!=="undefined")globalThis._alignPopupDismissed=_alignPopupDismissed;
if(typeof _alignScanLog!=="undefined")globalThis._alignScanLog=_alignScanLog;
if(typeof _alignState!=="undefined")globalThis._alignState=_alignState;
if(typeof _restoreAlignPopupState!=="undefined")globalThis._restoreAlignPopupState=_restoreAlignPopupState;
if(typeof _tStep!=="undefined")globalThis._tStep=_tStep;
if(typeof drawAlignBeamProfile!=="undefined")globalThis.drawAlignBeamProfile=drawAlignBeamProfile;
if(typeof drawAlignScanInPopup!=="undefined")globalThis.drawAlignScanInPopup=drawAlignScanInPopup;
if(typeof drawMaBeamProfile!=="undefined")globalThis.drawMaBeamProfile=drawMaBeamProfile;
if(typeof exportAlignScanLog!=="undefined")globalThis.exportAlignScanLog=exportAlignScanLog;
if(typeof getAlignScanLog!=="undefined")globalThis.getAlignScanLog=getAlignScanLog;
if(typeof logAlignScan!=="undefined")globalThis.logAlignScan=logAlignScan;
if(typeof openAlignMonitor!=="undefined")globalThis.openAlignMonitor=openAlignMonitor;
if(typeof openDeviceAlignSetup!=="undefined")globalThis.openDeviceAlignSetup=openDeviceAlignSetup;
if(typeof openMirrorAlignPopup!=="undefined")globalThis.openMirrorAlignPopup=openMirrorAlignPopup;
if(typeof runAlignStepUI!=="undefined")globalThis.runAlignStepUI=runAlignStepUI;
if(typeof runMirrorAlignUI!=="undefined")globalThis.runMirrorAlignUI=runMirrorAlignUI;
if(typeof showAlignSummary!=="undefined")globalThis.showAlignSummary=showAlignSummary;
if(typeof updateAlignProgress!=="undefined")globalThis.updateAlignProgress=updateAlignProgress;
