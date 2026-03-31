'use strict';
// ===== alignment/03_runners.js -- Alignment Sequence Runners =====
// @module alignment/03_runners
// @exports KB_PARAMS, MIRROR_ALIGN_SEQ, _alignFullAuto, _alignNextPending, _alignPitchZero, _alignPopupDismissed, _alignRayCount, _alignStepResolve, _alignWaitForNext, _alignWaitingStep, _applyRows, _autoDetectReflectedROI, _bpmFovROI, _collectAllSteps, _createAlignNextButtons, ...
// Extracted from 14_v435_final.js (DDD Phase 5e)
// MIRROR_ALIGN_SEQ definitions, runMirrorAlign, KB_PARAMS, axis range expansion,
// abortAlignment, setAlignConfig, setMirrorAlignRange,
// _alignWaitForNext, _createAlignNextButtons, runFullAlignment
// Dependencies: mcRayTrace, pos, beamAt, braggAngle, MOTORS, state, ALIGN_CONFIG,
//   log, _isAlignPopupVisible, _showAlignConfirmButtons, alignNextStep,
//   openMirrorAlignPopup, runMirrorAlignUI, runAlignStepUI, updateAlignProgress

// ===================================================================
// Yield helper: skip yield entirely when tab is hidden (background).
// Virtual-mode alignment is pure computation — no UI yield needed
// in background. In foreground, use MessageChannel (faster than setTimeout).
// ===================================================================
var _resolvedPromise = Promise.resolve();
var _yieldAsync = function(){
  if (document.hidden) return _resolvedPromise;  // no yield in background
  if (typeof MessageChannel !== 'undefined') {
    return new Promise(function(r){ var ch=new MessageChannel(); ch.port1.onmessage=function(){r();}; ch.port2.postMessage(''); });
  }
  return new Promise(function(r){ setTimeout(r,0); });
};

// ===================================================================
// MC align sequences IIFE
// ===================================================================
(function(){
// --- MC signal helpers (use MC_NRAYS from View tab) ---
function _alignRayCount(){
  return (typeof MC_NRAYS!=='undefined')?MC_NRAYS:80000;
}

// Get BPM FOV as ROI box (fixed physical FOV)
function _bpmFovROI(detDist){
  if(typeof CD==='undefined') return null;
  for(var i=0;i<CD.length;i++){
    if(CD[i].tp==='bpm'&&CD[i].optics&&CD[i].optics.fov){
      var p=(typeof pos==='function')?pos(CD[i].id):CD[i].dp;
      if(Math.abs(p-detDist)<0.5){
        var f=CD[i].optics.fov;
        // ROI centered on main beam (x=0 in beam frame)
        return{xMin:-f,xMax:f,yMin:-f,yMax:f};
      }
    }
  }
  return null;
}

// MC flux at detector position (weight-based)
// Uses BPM physical FOV as natural ROI — rays outside FOV are not counted.
function mcSig(detDist, roi){
  try{
    var mc=mcRayTrace(detDist,_alignRayCount());
    var effectiveROI=roi||_bpmFovROI(detDist);
    if(effectiveROI) return _roiSig(mc, effectiveROI);
    return (mc.wMean||1)*(mc.nSurvived||0);
  }catch(e){return 0;}
}
// MC beam centroid position at detector (returns {cx,cy} in mm, n=surviving rays)
// Only counts rays within BPM physical FOV.
function mcCentroid(detDist, roi){
  try{
    var mc=mcRayTrace(detDist,_alignRayCount());
    var effectiveROI=roi||_bpmFovROI(detDist);
    if(effectiveROI) return _roiCentroid(mc, effectiveROI);
    return{cx:(mc.meanH||0)*1e3, cy:(mc.meanV||0)*1e3, n:mc.nSurvived||0};
  }catch(e){return{cx:0,cy:0,n:0};}
}

// ROI-filtered signal: count only rays within ROI box {xMin,xMax,yMin,yMax} (meters)
function _roiSig(mc, roi){
  var al=mc._aliveRays||[];
  var n=0,wSum=0;
  for(var i=0;i<al.length;i++){
    var r=al[i];
    if(roi.xMin!=null && r.x<roi.xMin) continue;
    if(roi.xMax!=null && r.x>roi.xMax) continue;
    if(roi.yMin!=null && r.y<roi.yMin) continue;
    if(roi.yMax!=null && r.y>roi.yMax) continue;
    n++; wSum+=r.w;
  }
  return n>0 ? (wSum/n)*n : 0;
}

// ROI-filtered centroid
function _roiCentroid(mc, roi){
  var al=mc._aliveRays||[];
  var sx=0,sy=0,sw=0;
  for(var i=0;i<al.length;i++){
    var r=al[i];
    if(roi.xMin!=null && r.x<roi.xMin) continue;
    if(roi.xMax!=null && r.x>roi.xMax) continue;
    if(roi.yMin!=null && r.y<roi.yMin) continue;
    if(roi.yMax!=null && r.y>roi.yMax) continue;
    sx+=r.x*r.w; sy+=r.y*r.w; sw+=r.w;
  }
  if(sw<=0) return{cx:0,cy:0,n:0};
  return{cx:sx/sw*1e3, cy:sy/sw*1e3, n:Math.round(sw)};
}

// Auto-detect ROI for reflected beam at given pitch.
// Strategy: at pitch > 0, reflected beam is spatially separated from bypass beam.
// Run MC at a known positive pitch, find the reflected beam cluster using
// 1D histogram in deflection axis, then set ROI to that cluster.
function _autoDetectReflectedROI(detDist, mid, pitch_mrad){
  try{
    var mp=M_PARAMS[mid]; if(!mp) return null;
    var isDeflX=(mp.deflAxis==='x');
    var stKey=(mid==='m1')?'m1pitch':(mid==='m2')?'m2pitch':null;
    var origPitch=stKey?state[stKey]:2.5;
    // Use a large enough pitch to clearly separate bypass and reflected beams.
    // At pitch=p, reflected beam offset = 2*p*L from bypass beam.
    // Need offset >> beam size (~3mm at M1 XBPM) → p >= 1.5 mrad.
    var testPitch=Math.max(pitch_mrad||0.15, 0.05);
    if(stKey) state[stKey]=testPitch;
    var mot=MOTORS[mid]&&MOTORS[mid].pitch;
    if(mot) mot.value=testPitch;

    log('info','AutoROI['+mid+']: probing at pitch='+testPitch.toFixed(2)+' mrad...');
    var mc=mcRayTrace(detDist,_alignRayCount());
    var al=mc._aliveRays||[];

    // Restore pitch
    if(stKey) state[stKey]=origPitch;
    if(mot) mot.value=origPitch;

    // Filter rays by BPM physical FOV first
    var bpmROI=_bpmFovROI(detDist);
    var alFov=[];
    for(var i=0;i<al.length;i++){
      if(bpmROI){
        if(bpmROI.xMin!=null&&al[i].x<bpmROI.xMin) continue;
        if(bpmROI.xMax!=null&&al[i].x>bpmROI.xMax) continue;
        if(bpmROI.yMin!=null&&al[i].y<bpmROI.yMin) continue;
        if(bpmROI.yMax!=null&&al[i].y>bpmROI.yMax) continue;
      }
      alFov.push(al[i]);
    }

    log('info','AutoROI['+mid+']: '+alFov.length+'/'+al.length+' rays in BPM FOV at probe pitch='+testPitch.toFixed(3));
    if(alFov.length<20) return null;

    // Get positions in deflection axis (only FOV-filtered rays)
    var vals=[];
    for(var i=0;i<alFov.length;i++){
      vals.push({pos: isDeflX ? alFov[i].x : alFov[i].y, w: alFov[i].w});
    }
    vals.sort(function(a,b){return a.pos-b.pos;});

    // Find largest gap between consecutive sorted positions (cluster boundary)
    var maxGap=0, gapIdx=0;
    for(var i=1;i<vals.length;i++){
      var gap=vals[i].pos-vals[i-1].pos;
      if(gap>maxGap){maxGap=gap;gapIdx=i;}
    }

    var totalRange=vals[vals.length-1].pos-vals[0].pos;
    log('info','AutoROI['+mid+']: range='+totalRange.toExponential(2)+
      'm, maxGap='+maxGap.toExponential(2)+'m at idx='+gapIdx+'/'+vals.length);

    if(maxGap < totalRange*0.02 || totalRange<1e-6){
      log('warn','AutoROI['+mid+']: no clear gap found, skip ROI');
      return null;
    }

    var boundary=(vals[gapIdx-1].pos+vals[gapIdx].pos)/2;

    // Determine which cluster is reflected vs bypass:
    // Count rays in each cluster
    var nLow=gapIdx, nHigh=vals.length-gapIdx;
    // Bypass beam has more rays (full undulator beam), reflected is fewer (mirror acceptance)
    // Also: reflected beam center = bypass center + 2*pitch*L
    var meanLow=0, meanHigh=0;
    for(var i=0;i<gapIdx;i++) meanLow+=vals[i].pos;
    meanLow/=nLow;
    for(var i=gapIdx;i<vals.length;i++) meanHigh+=vals[i].pos;
    meanHigh/=nHigh;

    // Reflected beam is the one further from zero (more deflected)
    var roi={};
    var reflectedIsHigh=Math.abs(meanHigh)>Math.abs(meanLow);
    if(isDeflX){
      if(reflectedIsHigh) roi.xMin=boundary;
      else roi.xMax=boundary;
    } else {
      if(reflectedIsHigh) roi.yMin=boundary;
      else roi.yMax=boundary;
    }
    var reflLabel=reflectedIsHigh?'high':'low';
    log('info','AutoROI['+mid+']: reflected='+reflLabel+
      ' cluster (nLow='+nLow+' nHigh='+nHigh+
      '), boundary='+(boundary*1e3).toFixed(2)+'mm'+
      ', ROI: '+(isDeflX?'x':'y')+(reflectedIsHigh?'>':'<')+(boundary*1e3).toFixed(2)+'mm');
    return roi;
  }catch(e){
    log('warn','AutoROI['+mid+'] failed: '+e.message);
    return null;
  }
}

// NOTE: Initial MIRROR_ALIGN_SEQ definition removed (replaced by canonical
// edge-aware halfcut + rot_center version below in the alignment IIFE)

// --- Unified runMirrorAlign (MC-based) ---
window.runMirrorAlign=async function(mid,onStepStart,onPoint){
  var seq=MIRROR_ALIGN_SEQ[mid];
  if(!seq)return[];
  var det=seq.det, results=[], detD=pos(det);
  var isDCM=(mid==='dcm');
  var deflAxis=seq.deflAxis||'y'; // 'x'=horizontal, 'y'=vertical
  var stKeyMap={m1:'m1pitch',m2:'m2pitch',kbv:'kbvpitch',kbh:'kbhpitch'};
  var stKey=isDCM?null:(stKeyMap[mid]||null);
  // Clear pitch zero offset from previous alignment
  if(!window._alignPitchZero) window._alignPitchZero={};
  window._alignPitchZero[mid]=null;

  // KB alignment: open SSA to configured gap for maximum ray throughput
  var isKB=(mid==='kbv'||mid==='kbh');
  var origSsaH=state.ssaH, origSsaV=state.ssaV;
  // Track whether user changed SSA during alignment (don't restore if they did)
  window._kbAlignSsaUserChanged=false;
  if(isKB){
    var kbCfg=ALIGN_CONFIG.kbalign||{};
    var alignSsaH=(kbCfg.ssaGapH!=null&&kbCfg.ssaGapH>0)?kbCfg.ssaGapH:100;
    var alignSsaV=(kbCfg.ssaGapV!=null&&kbCfg.ssaGapV>0)?kbCfg.ssaGapV:100;
    window._kbAlignSsaProgrammatic=true;
    state.ssaH=alignSsaH; state.ssaV=alignSsaV;
    if(MOTORS.ssa&&MOTORS.ssa.hgap){MOTORS.ssa.hgap.value=alignSsaH;MOTORS.ssa.hgap.target=alignSsaH;}
    if(MOTORS.ssa&&MOTORS.ssa.vgap){MOTORS.ssa.vgap.value=alignSsaV;MOTORS.ssa.vgap.target=alignSsaV;}
    if(typeof syncMotorToState==='function'){try{syncMotorToState('ssa','ssa_hgap',alignSsaH);syncMotorToState('ssa','ssa_vgap',alignSsaV);}catch(e){}}
    window._kbAlignSsaProgrammatic=false;
    log('info','KB align: SSA opened H='+alignSsaH+'um V='+alignSsaV+'um (was H='+origSsaH+' V='+origSsaV+')');
  }

  // KB-V alignment: retract KB-H completely (pitch=0 + translate out)
  // KB-H alignment: retract KB-V completely (pitch=0 + translate out)
  var _kbRetracted=null, _kbOrigPitch=null, _kbOrigTrans=null;
  if(mid==='kbv'&&MOTORS.kbh){
    _kbRetracted='kbh';
    _kbOrigPitch=MOTORS.kbh.pitch?MOTORS.kbh.pitch.value:3.0;
    _kbOrigTrans=MOTORS.kbh.x?MOTORS.kbh.x.value:0;
    if(MOTORS.kbh.pitch){MOTORS.kbh.pitch.value=0;MOTORS.kbh.pitch.target=0;}
    if(MOTORS.kbh.x){MOTORS.kbh.x.value=15;MOTORS.kbh.x.target=15;} // translate 15mm out
    state.kbhpitch=0;
    log('info','KB-V align: retracted KB-H (pitch=0, x=15mm)');
  } else if(mid==='kbh'&&MOTORS.kbv){
    _kbRetracted='kbv';
    _kbOrigPitch=MOTORS.kbv.pitch?MOTORS.kbv.pitch.value:3.0;
    _kbOrigTrans=MOTORS.kbv.y?MOTORS.kbv.y.value:0;
    if(MOTORS.kbv.pitch){MOTORS.kbv.pitch.value=0;MOTORS.kbv.pitch.target=0;}
    if(MOTORS.kbv.y){MOTORS.kbv.y.value=15;MOTORS.kbv.y.target=15;} // translate 15mm out
    state.kbvpitch=0;
    log('info','KB-H align: retracted KB-V (pitch=0, y=15mm)');
  }

  try{
  for(var si=0;si<seq.steps.length;si++){
    if(state._alignAborted) throw new Error('Alignment aborted');
    var step=seq.steps[si];
    if(onStepStart)onStepStart(si,seq.steps.length,step);

    // Direct move
    if(step.target!=null){
      if(step.target==='bragg'){
        var thDeg=braggAngle(state.energy)*180/Math.PI;
        if(MOTORS.dcm&&MOTORS.dcm.theta)
          await MOTORS.dcm.theta.moveTo(thDeg);
        results.push({step:step.name,value:thDeg});
      }else{
        if(stKey)state[stKey]=step.target;
        if(!isDCM&&MOTORS[mid]&&MOTORS[mid].pitch)
          await MOTORS[mid].pitch.moveTo(step.target);
        results.push({step:step.name,value:step.target});
      }
      await _yieldAsync();
      continue;
    }

    // Scan: get motor object
    var mot=null;
    if(isDCM&&MOTORS.dcm)mot=MOTORS.dcm[step.motor];
    else if(MOTORS[mid])mot=MOTORS[mid][step.motor];
    if(!mot){results.push({step:step.name,error:'no motor'});continue;}

    // Half-cut prep: set pitch/theta to 0
    if(step.algo==='halfcut'){
      if(isDCM){
        if(MOTORS.dcm&&MOTORS.dcm.theta)
          await MOTORS.dcm.theta.moveTo(0);
      }else{
        if(MOTORS[mid]&&MOTORS[mid].pitch){
          await MOTORS[mid].pitch.moveTo(MOTORS[mid].pitch.min);
          MOTORS[mid].pitch.value=0;
        }
        if(stKey)state[stKey]=0;
      }
      await _yieldAsync();
      // Pre-move to near mirror edge for erf scan
      if(step.edgeMm && mot){
        await mot.moveTo(step.edgeMm);
        await _yieldAsync();
      }
    }

    // rot_center has its own scan loop -- skip generic scan
    var positions=[],signals=[],beamPos=[];
    var res={step:step.name};
    if(step.algo==='rot_center'){
      // Jump directly to rot_center analysis (it manages its own scan)
      res.positions=positions; res.signals=signals; res.beamPos=beamPos;
    } else {
    // Generic scan loop (halfcut, rocking, verify_pos, pitch_zero)
    var base=mot.value;
    var start=base+step.range[0],end=base+step.range[1];
    var ds=(end-start)/(step.nPts-1);
    // SPEC-style: store full scan range for fixed x-axis chart
    if(window._alignState){
      window._alignState._scanXMin=start;
      window._alignState._scanXMax=end;
    }

    for(var i=0;i<step.nPts;i++){
      if(state._alignAborted) throw new Error('Alignment aborted');
      var p=start+i*ds;
      await mot.moveTo(p);
      var sig=mcSig(detD);
      var bp=mcCentroid(detD);
      positions.push(p);
      signals.push(sig);
      var bpComp=(deflAxis==='x')?bp.cx:bp.cy;
      beamPos.push(step.algo==='verify_pos'?bpComp:sig);
      if(onPoint)onPoint(si,i,step.nPts,p,sig,
        bpComp,
        positions,signals,beamPos);
      await _yieldAsync();
    }

    // Assign scan data to result
    res.positions=positions; res.signals=signals; res.beamPos=beamPos;
    } // end generic scan
    if(step.algo==='halfcut'){
      // White beam elements (M1, DCM): rectangular beam → box-erf fit
      // Mono elements (M2, KBV, KBH): Gaussian beam → erf (halfcut) fit
      var isWB=(mid==='m1'||mid==='dcm');
      var hcAlgo=isWB?'boxerf':'halfcut';
      var hcRes=analyzeAlignScan(positions,signals,hcAlgo);
      var center=hcRes.center;
      if(center==null) center=positions[Math.floor(positions.length/2)];
      await mot.moveTo(center);
      res.center=center;
      res.method=hcRes.method||hcAlgo;
      if(hcRes.fwhm!=null) res.fwhm=hcRes.fwhm;
      if(hcRes.sigma!=null) res.sigma=hcRes.sigma;
      if(hcRes.boxWidth!=null) res.boxWidth=hcRes.boxWidth;
      if(hcRes.fit) res.fit=hcRes.fit;
    }else if(step.algo==='rocking'){
      // Use analyzeAlignScan for proper peak fitting
      var rcRes=analyzeAlignScan(positions,signals, isDCM?'rocking':'gaussian');
      var center2=rcRes.center;
      if(center2==null){var maxS=Math.max.apply(null,signals);center2=positions[signals.indexOf(maxS)];}
      await mot.moveTo(center2);
      res.center=center2;
      res.method=rcRes.method||'rocking';
      if(rcRes.fwhm!=null) res.fwhm=rcRes.fwhm;
      if(rcRes.fit) res.fit=rcRes.fit;
    }else if(step.algo==='verify_pos'){
      // Check beam position variation
      var minBP=Math.min.apply(null,beamPos);
      var maxBP=Math.max.apply(null,beamPos);
      res.posRange=maxBP-minBP;
      res.method='verify_pos';
      res.pass=(maxBP-minBP)<0.01; // <10um drift
    }else if(step.algo==='rot_center'){
      // --- Rotation Center: pitch scan + XBPM beam position monitor ---
      // Use step's pitchVal, or mirror nominal pitch, or KB default 3.0
      var _nomPitch = (mid==='m1'||mid==='m2') ? 2.5 : 3.0;
      var opPitch = step.pitchVal || _nomPitch;
      var maxIt = step.maxIter || 3;
      var thresh = step.threshold || 0.01; // mm residSlope threshold
      var pitchMot = MOTORS[mid] ? MOTORS[mid].pitch : null;
      var pitchSK = stKey;
      // RC correction uses along-beam (z) axis for all mirrors
      var tyKey = 'z';
      var transMot = MOTORS[mid] ? MOTORS[mid][tyKey] : null;
      // Mirror-to-detector distance (NOT absolute beamline position!)
      var mirrorPos = pos(mid) || 0;
      var detDist = parseFloat(detD) - mirrorPos;
      if (detDist <= 0) detDist = 1.0; // safety fallback
      // Geometric slope: beam angle change = 2*dpitch, position shift = 2*dpitch(rad)*L(m)
      // slope(mm/mrad) = 2 * 1e-3(rad/mrad) * L(m) * 1000(mm/m) = 2*L
      var geomSlope = 2.0 * 1e-3 * detDist * 1000; // = 2*detDist mm/mrad
      log('info','RotCenter: mirror='+mid+' mirrorPos='+mirrorPos.toFixed(1)+
        'm detPos='+parseFloat(detD).toFixed(1)+'m dist='+detDist.toFixed(2)+
        'm geomSlope='+geomSlope.toFixed(3)+' mm/mrad');

      // For KB mirrors: at operating angle, find reflected beam cluster and
      // set ROI to exclude bypass beam. Reflected beam is sharper/denser.
      // Use 1D histogram peak detection in deflection axis.
      var _rcExcludeROI = null;
      if (isKB) {
        // Already at operating pitch (set in previous step)
        await _yieldAsync();
        try {
          var _rcMC = mcRayTrace(parseFloat(detD), _alignRayCount());
          var _rcAl = _rcMC._aliveRays || [];
          if (_rcAl.length > 50) {
            // Build 1D histogram in deflection axis
            var _rcVals = [];
            for (var _ri = 0; _ri < _rcAl.length; _ri++) {
              _rcVals.push({v: deflAxis==='x' ? _rcAl[_ri].x : _rcAl[_ri].y, w: _rcAl[_ri].w});
            }
            _rcVals.sort(function(a,b){return a.v-b.v;});
            // Find largest gap between clusters
            var _rcMaxGap=0, _rcGapIdx=0;
            for(var _ri2=1;_ri2<_rcVals.length;_ri2++){
              var _g=_rcVals[_ri2].v-_rcVals[_ri2-1].v;
              if(_g>_rcMaxGap){_rcMaxGap=_g;_rcGapIdx=_ri2;}
            }
            var _rcRange=_rcVals[_rcVals.length-1].v-_rcVals[0].v;
            if(_rcMaxGap>_rcRange*0.03&&_rcRange>1e-6){
              var _rcBound=(_rcVals[_rcGapIdx-1].v+_rcVals[_rcGapIdx].v)/2;
              // Reflected beam = cluster with FEWER rays (mirror acceptance < full beam)
              var _rcNLo=_rcGapIdx, _rcNHi=_rcVals.length-_rcGapIdx;
              var _reflIsLo=(_rcNLo<_rcNHi);
              // Set ROI to INCLUDE only reflected beam cluster
              _rcExcludeROI = {};
              if(deflAxis==='x'){
                if(_reflIsLo) _rcExcludeROI.xMax=_rcBound; else _rcExcludeROI.xMin=_rcBound;
              } else {
                if(_reflIsLo) _rcExcludeROI.yMax=_rcBound; else _rcExcludeROI.yMin=_rcBound;
              }
              log('info','RotCenter['+mid+']: reflected beam cluster detected, boundary='
                +(_rcBound*1e3).toFixed(2)+'mm (nRefl='+(_reflIsLo?_rcNLo:_rcNHi)
                +' nBypass='+(_reflIsLo?_rcNHi:_rcNLo)+')');
            } else {
              log('info','RotCenter['+mid+']: no bypass/reflected separation found (single beam)');
            }
          }
        } catch(e) { log('warn','RotCenter cluster detect failed: '+e.message); }
      }

      for (var iter = 0; iter < maxIt; iter++) {
        var pPos=[], pBP=[];
        var pStart = opPitch + step.range[0];
        var pEnd = opPitch + step.range[1];
        // SPEC-style: store full scan range for fixed x-axis chart
        if(window._alignState){window._alignState._scanXMin=pStart;window._alignState._scanXMax=pEnd;}
        var pDs = (pEnd - pStart) / (step.nPts - 1);
        var pFlux=[];
        for (var pi = 0; pi < step.nPts; pi++) {
          var pp = pStart + pi * pDs;
          if(pitchMot) await pitchMot.moveTo(pp);
          if(pitchSK) state[pitchSK] = pp;
          if(pitchMot) pitchMot.value = pp;
          await _yieldAsync();
          // KB: use reflected beam ROI to exclude bypass from centroid
          var flux = mcSig(detD, _rcExcludeROI);
          var bpc = mcCentroid(detD, _rcExcludeROI);
          var bpVal = (deflAxis==='x') ? bpc.cx : bpc.cy;
          pPos.push(pp); pBP.push(bpVal); pFlux.push(flux);
          // onPoint: sig=flux (beam alive?), beamPos=centroid (drift monitor)
          if(onPoint) onPoint(si, pi, step.nPts, pp, flux, bpVal, pPos,
            pFlux, pBP.slice());
          await _yieldAsync();
        }
        // Filter valid points (flux > 0 = beam exists)
        var vPos=[], vBP=[];
        for(var vi=0;vi<pPos.length;vi++){
          if(pFlux[vi]>0){ vPos.push(pPos[vi]); vBP.push(pBP[vi]); }
        }
        var nValid=vPos.length;
        log('info','RotCenter iter'+iter+': '+nValid+'/'+pPos.length+' pts with signal');

        if(nValid < 3){
          log('warn','RotCenter: beam lost ('+nValid+' valid pts), aborting correction');
          res.converged = false; res.iterations = iter + 1;
          res.drift = 999; res.slope = 0; res.beamLost = true;
          break;
        }

        // Linear fit on valid points: bpVal = slope * pitch + offset
        var n=nValid, sx=0,sy=0,sxy=0,sxx=0;
        for(var fi=0;fi<n;fi++){
          sx+=vPos[fi]; sy+=vBP[fi]; sxy+=vPos[fi]*vBP[fi]; sxx+=vPos[fi]*vPos[fi];
        }
        var slope = (n*sxy - sx*sy) / (n*sxx - sx*sx);
        var residSlope = slope - geomSlope;
        var bpMin=Math.min.apply(null,vBP), bpMax=Math.max.apply(null,vBP);
        var drift = bpMax - bpMin;

        log('info','RotCenter iter'+iter+': drift='+drift.toFixed(4)+
          'mm slope='+slope.toFixed(4)+' geom='+geomSlope.toFixed(4)+
          ' resid='+residSlope.toFixed(4));

        if (Math.abs(residSlope) < thresh) {
          res.converged = true; res.iterations = iter + 1;
          res.drift = drift; res.slope = slope; res.residSlope = residSlope;
          log('info','RotCenter converged: |residSlope|='+Math.abs(residSlope).toFixed(4)+
            ' < '+thresh+' mm/mrad');
          break;
        }
        // For KB focusing mirrors: convergence is difficult due to focusing effect.
        // If this is the last iteration, accept the result as-is (best effort).
        if (isKB && iter === maxIt - 1) {
          res.converged = true; res.iterations = maxIt;
          res.drift = drift; res.slope = slope; res.residSlope = residSlope;
          log('info','RotCenter[KB]: accepted after '+maxIt+' iterations (focusing mirror, drift='+drift.toFixed(2)+'mm)');
          break;
        }
        // Correct along-beam (z) motor to shift footprint onto rotation center
        var tyCorr = residSlope * 1000; // meters -> mm along beam
        // Clamp to safe range
        var maxCorr = 150; // mm (along-beam, larger range than deflection axis)
        tyCorr = Math.max(-maxCorr, Math.min(maxCorr, tyCorr));
        log('info','RotCenter: '+tyKey+' correction='+tyCorr.toFixed(4)+'mm ('+
          tyKey+'_before='+((transMot?transMot.value:0)).toFixed(3)+')');
        if(transMot) await transMot.moveTo(transMot.value + tyCorr);

        if (iter === maxIt - 1) {
          res.converged = false; res.iterations = maxIt;
          res.drift = drift; res.slope = slope;
          log('warn','RotCenter: max iterations, drift='+drift.toFixed(4));
        }
      }
      // Restore operating pitch
      if(pitchMot) await pitchMot.moveTo(opPitch);
      if(pitchSK) state[pitchSK] = opPitch;
      if(pitchMot) pitchMot.value = opPitch;
      res.method = 'rot_center';
      res.pass = res.converged;
    }
    results.push(res);
    // Wait for user confirmation before next step
    if(si < seq.steps.length-1){
      await _waitUserConfirm(step.name, res);
    }
  }
  }finally{
    // KB alignment: restore original SSA gaps (unless user changed SSA manually)
    if(isKB&&!window._kbAlignSsaUserChanged){
      window._kbAlignSsaProgrammatic=true;
      state.ssaH=origSsaH; state.ssaV=origSsaV;
      if(MOTORS.ssa&&MOTORS.ssa.hgap){MOTORS.ssa.hgap.value=origSsaH;MOTORS.ssa.hgap.target=origSsaH;}
      if(MOTORS.ssa&&MOTORS.ssa.vgap){MOTORS.ssa.vgap.value=origSsaV;MOTORS.ssa.vgap.target=origSsaV;}
      if(typeof syncMotorToState==='function'){try{syncMotorToState('ssa','ssa_hgap',origSsaH);syncMotorToState('ssa','ssa_vgap',origSsaV);}catch(e){}}
      window._kbAlignSsaProgrammatic=false;
      log('info','KB align done: SSA restored H='+origSsaH+'um V='+origSsaV+'μm');
    }else if(isKB){
      log('info','KB align done: SSA kept at user-set H='+state.ssaH+'um V='+state.ssaV+'μm');
    }
    window._kbAlignSsaUserChanged=false;
  }
  // Restore retracted KB mirror
  if(_kbRetracted==='kbh'&&MOTORS.kbh){
    if(MOTORS.kbh.pitch){MOTORS.kbh.pitch.value=_kbOrigPitch;MOTORS.kbh.pitch.target=_kbOrigPitch;}
    if(MOTORS.kbh.x){MOTORS.kbh.x.value=_kbOrigTrans;MOTORS.kbh.x.target=_kbOrigTrans;}
    state.kbhpitch=_kbOrigPitch;
    log('info','KB-V align done: KB-H restored (pitch='+_kbOrigPitch+', x='+_kbOrigTrans+')');
  } else if(_kbRetracted==='kbv'&&MOTORS.kbv){
    if(MOTORS.kbv.pitch){MOTORS.kbv.pitch.value=_kbOrigPitch;MOTORS.kbv.pitch.target=_kbOrigPitch;}
    if(MOTORS.kbv.y){MOTORS.kbv.y.value=_kbOrigTrans;MOTORS.kbv.y.target=_kbOrigTrans;}
    state.kbvpitch=_kbOrigPitch;
    log('info','KB-H align done: KB-V restored (pitch='+_kbOrigPitch+', y='+_kbOrigTrans+')');
  }
  return results;
};

// Step confirmation: show Next button, wait for click
// If popup is closed, auto-advance so alignment continues in background
window._alignStepResolve=null;
window._alignWaitingStep=null;
window.alignNextStep=function(){
  if(window._alignStepResolve){window._alignStepResolve();window._alignStepResolve=null;}
};
window._isAlignPopupVisible=function(){
  var ov=document.getElementById('modalOverlay');
  return ov&&ov.classList.contains('open');
};
window._showAlignConfirmButtons=function(stepName,res){
  var info=document.getElementById('alignMonInfo');
  if(!info)return;
  var txt='Step "'+stepName+'" done.';
  if(res.center!=null) txt+=' Center='+res.center.toFixed(4);
  if(res.value!=null) txt+=' Value='+(typeof res.value==='number'?res.value.toFixed(3):res.value);
  if(res.pass!=null) txt+=' '+(res.pass?'PASS':'FAIL');
  info.innerHTML=txt+
    '  <button class="sb go act" onclick="alignNextStep()" style="margin-left:6px">Next &rarr;</button>'+
    '  <button class="sb act" onclick="toggleAlignAnalysis()" style="margin-left:6px">Analyze</button>';
  info.style.color='var(--ac)';
};
// End of _showAlignConfirmButtons (window-level)
function _waitUserConfirm(stepName,res){
  return new Promise(function(resolve){
    // Full Auto mode: skip confirmation, update UI, auto-advance
    if(window._alignFullAuto){
      window._lastAlignResult=res;
      // Update step status in UI (same as manual confirm)
      var as=window._alignState;
      if(as&&as.results){
        var si=as.results.length-1;
        var stEl=document.getElementById('alignStepSt_'+si);
        if(stEl&&res){
          if(res.center!=null){stEl.textContent=res.center.toFixed(4);stEl.style.color='var(--gn)';}
          else if(res.value!=null){stEl.textContent=typeof res.value==='number'?res.value.toFixed(3):String(res.value);stEl.style.color='var(--gn)';}
          else if(res.pass!=null){stEl.textContent=res.pass?'PASS':'FAIL';stEl.style.color=res.pass?'var(--gn)':'var(--rd)';}
          else if(res.method){stEl.textContent=res.method;stEl.style.color='var(--gn)';}
          else{stEl.textContent='done';stEl.style.color='var(--gn)';}
        }
      }
      _yieldAsync().then(function(){resolve();});
      return;
    }
    window._alignStepResolve=resolve;
    window._lastAlignResult=res;
    window._alignWaitingStep=stepName;
    // If popup not visible OR tab hidden, auto-advance
    if(!_isAlignPopupVisible() || document.hidden){
      _yieldAsync().then(function(){
        if(window._alignStepResolve===resolve){
          window._alignStepResolve=null;
          resolve();
        }
      });
      return;
    }
    _showAlignConfirmButtons(stepName,res);
  });
}

console.log('[alignment/03_runners] MC-based align sequences loaded');
})();

// ===================================================================
// Global abort function for alignment popups
// ===================================================================
window.abortAlignment=function(){
  state._alignAborted=true;
  if(typeof MOTORS!=='undefined'){
    Object.keys(MOTORS).forEach(function(grp){
      var dev=MOTORS[grp];
      Object.keys(dev).forEach(function(ax){
        if(dev[ax]&&dev[ax].moving&&typeof dev[ax].stop==='function')dev[ax].stop();
      });
    });
  }
  log('warn','Alignment abort requested');
  var info=document.getElementById('alignMonInfo');
  if(info){info.textContent='ABORTED by user';info.style.color='var(--rd)';}
};

// ===================================================================
// KB mirror params + axis range expansion + edge-aware MIRROR_ALIGN_SEQ
// ===================================================================
(function(){
// KB mirror params (for halfcut boundary check)
// Elliptical pre-figured KB mirrors (JTEC)
// KB-V: 300mm tangential length, KB-H: 100mm tangential length
window.KB_PARAMS = {
  kbv: { type:'elliptical', len:0.300, wid:0.030, thick:0.050, rough:4.0 },
  kbh: { type:'elliptical', len:0.100, wid:0.030, thick:0.050, rough:4.0 }
};

// Expand half-cut motor ranges to cover mirror edge (wid/2)
function expandAxisRange(mid, axisKey, newMin, newMax) {
  if (MOTORS[mid] && MOTORS[mid][axisKey]) {
    MOTORS[mid][axisKey].min = newMin;
    MOTORS[mid][axisKey].max = newMax;
  }
}
// Apply after MOTORS init (use setTimeout to ensure MOTORS exists)
setTimeout(function(){
  expandAxisRange('m1', 'x', -35, 35);   // horizontal deflection -> x axis
  expandAxisRange('m2', 'x', -25, 25);   // horizontal deflection -> x axis
  expandAxisRange('kbv', 'y', -18, 18);  // vertical deflection -> y (height)
  expandAxisRange('kbh', 'x', -18, 18);  // horizontal deflection -> x axis
  expandAxisRange('dcm', 'y1', -35, 35); // horizontal deflection -> y1 (DCM local)
  console.log('[alignment/03_runners] half-cut axis ranges expanded');
}, 500);

// Override MIRROR_ALIGN_SEQ with edge-aware halfcut
// Halfcut scan range stays +/-5mm, but pre-move targets edge
window.MIRROR_ALIGN_SEQ = {
  m1:{name:'M1 Full Alignment', det:'xbpm_m1', deflAxis:'x', steps:[
    {name:'Half-Cut (pitch=0)', motor:'x', range:[-5,5], nPts:61,
     algo:'halfcut', desc:'at pitch~0, scan x (deflection axis), find mirror surface edge'},
    {name:'Set Operating Angle', motor:'pitch', target:2.5},
    {name:'Rotation Center', motor:'pitch', range:[-0.5,0.5], nPts:21,
     algo:'rot_center', pitchVal:2.5, maxIter:5, threshold:0.01,
     desc:'scan pitch, correct z (along-beam) to find RC'}
  ]},
  m2:{name:'M2 Full Alignment', det:'xbpm_m2', deflAxis:'x', steps:[
    {name:'Half-Cut (pitch=0)', motor:'x', range:[-5,5], nPts:61,
     algo:'halfcut', desc:'at pitch~0, scan x (deflection axis), find mirror surface edge'},
    {name:'Set Operating Angle', motor:'pitch', target:2.5},
    {name:'Rotation Center', motor:'pitch', range:[-0.5,0.5], nPts:21,
     algo:'rot_center', pitchVal:2.5, maxIter:5, threshold:0.01,
     desc:'scan pitch, correct z (along-beam) to find RC'}
  ]},
  kbv:{name:'KB-V Alignment', det:'det', deflAxis:'y', steps:[
    {name:'Half-Cut (pitch=0)', motor:'y', range:[-3,3], nPts:41,
     algo:'halfcut', desc:'at pitch~0, scan y (vertical deflection), find mirror surface'},
    {name:'Set Operating Angle', motor:'pitch', target:3.0},
    {name:'Rotation Center', motor:'pitch', range:[-0.5,0.5], nPts:21,
     algo:'rot_center', pitchVal:3.0, maxIter:5, threshold:2.0,
     desc:'scan pitch, correct z (along-beam) to find RC'}
  ]},
  kbh:{name:'KB-H Alignment', det:'det', deflAxis:'x', steps:[
    {name:'Half-Cut (pitch=0)', motor:'x', range:[-3,3], nPts:41,
     algo:'halfcut', desc:'at pitch~0, scan x (deflection axis), find mirror surface'},
    {name:'Set Operating Angle', motor:'pitch', target:3.0},
    {name:'Rotation Center', motor:'pitch', range:[-0.5,0.5], nPts:21,
     algo:'rot_center', pitchVal:3.0, maxIter:5, threshold:2.0,
     desc:'scan pitch, correct z (along-beam) to find RC'}
  ]}
};
// DCM alignment -- HORIZONTAL deflection DCM (XDS Oxford HDCM-HCCM)
window.MIRROR_ALIGN_SEQ.dcm={
  name:'DCM Full Alignment', det:'xbpm1', deflAxis:'x', steps:[
    {name:'Half-Cut C1 (theta=0)', motor:'y1', range:[-5,5], nPts:61,
     algo:'halfcut', axisLabel:'C1 x', unit:'mm',
     desc:'theta=0, scan C1 position along surface normal (horizontal), find crystal edge'},
    {name:'Set Bragg', motor:'theta', target:'bragg'},
    {name:'dTheta2 Coarse', motor:'dTheta2', range:[-30,30], nPts:61,
     algo:'rocking', desc:'Stepper: 1st-2nd crystal parallelism in horizontal diffracting plane'},
    {name:'dTheta2 Fine', motor:'dTheta2F', range:[-5,5], nPts:41,
     algo:'rocking', desc:'Piezo fine parallel adjustment'}
  ]
};

console.log('[alignment/03_runners] Mirror dimensions + edge-aware halfcut loaded');
})();


// ===================================================================
// Alignment Config API (for NLP integration)
// ===================================================================
// Set scan range/points for individual alignment steps (ALIGN_CONFIG keys)
window.setAlignConfig=function(key,rangeMin,rangeMax,nPts){
  var cfg=ALIGN_CONFIG[key];
  if(!cfg){log('warn','setAlignConfig: unknown key '+key);return false;}
  if(rangeMin!=null&&rangeMax!=null&&rangeMin<rangeMax)cfg.range=[rangeMin,rangeMax];
  if(nPts!=null&&nPts>=5&&nPts<=201)cfg.nPts=nPts;
  log('info','AlignConfig['+key+']: range=['+cfg.range+'] nPts='+cfg.nPts);
  return true;
};

// Set scan range/points for multi-step mirror alignment sequences
window.setMirrorAlignRange=function(mid,stepName,rangeMin,rangeMax,nPts){
  var seq=MIRROR_ALIGN_SEQ[mid];
  if(!seq){log('warn','setMirrorAlignRange: unknown mid '+mid);return false;}
  var step=null;
  for(var i=0;i<seq.steps.length;i++){
    if(seq.steps[i].name===stepName||seq.steps[i].algo===stepName){step=seq.steps[i];break;}
  }
  if(!step||!step.range){log('warn','setMirrorAlignRange: step not found '+stepName);return false;}
  if(rangeMin!=null&&rangeMax!=null)step.range=[rangeMin,rangeMax];
  if(nPts!=null&&nPts>=5)step.nPts=nPts;
  log('info','MirrorAlignRange['+mid+'/'+stepName+']: range=['+step.range+'] nPts='+(step.nPts||'default'));
  return true;
};

// ===================================================================
// waitForNext utility -- pause between alignment steps
// ===================================================================
// Tracks pending resolve so AUTO RUN reopen can re-create NEXT button
window._alignNextPending = null; // {resolve, reject, stepLabel, stepIdx, totalSteps}

window._alignWaitForNext = function(stepLabel, stepIdx, totalSteps) {
  return new Promise(function(resolve, reject) {
    // Full Auto mode: skip all waits, auto-advance
    if (window._alignFullAuto) {
      window._alignNextPending = null;
      var infoEl = document.getElementById('maMonInfo') || document.getElementById('alignMonInfo');
      if (infoEl) {
        infoEl.textContent = 'Auto: Step ' + (stepIdx+1) + '/' + totalSteps + ' ' + stepLabel + ' done';
        infoEl.style.color = 'var(--gn)';
      }
      _yieldAsync().then(function(){ resolve('next'); });
      return;
    }
    // If popup dismissed, UI closed, or tab hidden → auto-advance
    if (window._alignPopupDismissed || document.hidden) {
      window._alignNextPending = null;
      _yieldAsync().then(function(){ resolve('next'); });
      return;
    }
    // Find the currently active popup info area
    var infoEl = document.getElementById('maMonInfo') || document.getElementById('alignMonInfo');
    var parentEl = infoEl ? infoEl.parentElement : null;
    if (!parentEl) {
      window._alignNextPending = null;
      _yieldAsync().then(function(){ resolve('next'); });
      return;
    }

    // Store pending state for reopen
    window._alignNextPending = {resolve:resolve, reject:reject, stepLabel:stepLabel, stepIdx:stepIdx, totalSteps:totalSteps};

    window._createAlignNextButtons(parentEl, stepLabel, stepIdx, totalSteps, resolve, reject);
  });
};

// Extracted button creation so it can be called on reopen
window._createAlignNextButtons = function(parentEl, stepLabel, stepIdx, totalSteps, resolve, reject) {
  // Remove existing if any
  var existing = document.getElementById('_alignNextWrap');
  if (existing) existing.remove();

  var div = document.createElement('div');
  div.id = '_alignNextWrap';
  div.style.cssText = 'display:flex;gap:8px;align-items:center;margin-top:8px;padding:8px 10px;'
    + 'background:rgba(60,130,255,0.08);border:1px solid rgba(60,130,255,0.25);border-radius:4px';
  var nextLabel = (stepIdx < totalSteps - 1)
    ? '> Next (' + (stepIdx+2) + '/' + totalSteps + ')'
    : '> Finish';
  div.innerHTML = '<span style="flex:1;font-size:9px;color:var(--ac);font-family:var(--mn)">'
    + stepLabel + ' complete -- click Next to proceed</span>'
    + '<button id="_alignNextBtn" style="font-size:9px;padding:4px 16px;background:var(--gn);'
    + 'color:#000;border:none;border-radius:3px;cursor:pointer;font-weight:bold">' + nextLabel + '</button>'
    + '<button id="_alignAbortBtn" style="font-size:9px;padding:4px 12px;background:var(--rd);'
    + 'color:#fff;border:none;border-radius:3px;cursor:pointer">Abort</button>';
  parentEl.appendChild(div);

  // Scroll into view
  div.scrollIntoView({behavior:'smooth', block:'nearest'});

  document.getElementById('_alignNextBtn').onclick = function() {
    div.remove();
    window._alignNextPending = null;
    resolve('next');
  };
  document.getElementById('_alignAbortBtn').onclick = function() {
    div.remove();
    window._alignNextPending = null;
    state._alignAborted = true;
    reject(new Error('Alignment aborted by user'));
  };
};

// Auto-advance pending alignment steps when tab becomes hidden
document.addEventListener('visibilitychange', function(){
  if(!document.hidden) return;
  // If waiting for user confirm (step result)
  if(window._alignStepResolve){
    var fn=window._alignStepResolve;
    window._alignStepResolve=null;
    fn();
  }
  // If waiting for "Next" button between steps
  if(window._alignNextPending){
    var p=window._alignNextPending;
    window._alignNextPending=null;
    var wrap=document.getElementById('_alignNextWrap');
    if(wrap) wrap.remove();
    p.resolve('next');
  }
});

// ===================================================================
// Full Alignment Config Dialog + Orchestrator
// ===================================================================
(function(){

// Sequence definition (shared by dialog + orchestrator)
var _faSequence=[
  {type:'strategy', key:'wbslit',    label:'WB Slit H-Centering'},
  {type:'strategy', key:'wbslit_v',  label:'WB Slit V-Centering'},
  {type:'mirror',   key:'m1',        label:'M1 Full Alignment'},
  {type:'mirror',   key:'dcm',       label:'DCM Full Alignment'},
  {type:'mirror',   key:'m2',        label:'M2 Full Alignment'},
  {type:'strategy', key:'ssacenter',   label:'SSA H-Centering'},
  {type:'strategy', key:'ssacenter_v', label:'SSA V-Centering'},
  {type:'mirror',   key:'kbv',       label:'KB-V Alignment'},
  {type:'mirror',   key:'kbh',       label:'KB-H Alignment'}
];

// Collect all scan rows for the config table
function _collectAllSteps(){
  var rows=[];
  _faSequence.forEach(function(dev){
    var isMirror=!!MIRROR_ALIGN_SEQ[dev.key];
    if(isMirror){
      var seq=MIRROR_ALIGN_SEQ[dev.key];
      seq.steps.forEach(function(st,i){
        rows.push({device:dev.label, devKey:dev.key, type:'mirror', idx:i,
          name:st.name, motor:st.motor, range:st.range?st.range.slice():null,
          nPts:st.nPts||0, target:st.target, algo:st.algo,
          editable:(!st.target && !!st.range)});
      });
    }else if(ALIGN_CONFIG[dev.key]){
      var cfg=ALIGN_CONFIG[dev.key];
      rows.push({device:dev.label, devKey:dev.key, type:'strategy', idx:0,
        name:cfg.label, motor:cfg.motor, range:cfg.range.slice(),
        nPts:cfg.nPts, target:null, algo:cfg.algo, editable:true});
    }
  });
  return rows;
}

// Apply edited values back to MIRROR_ALIGN_SEQ / ALIGN_CONFIG
function _applyRows(rows){
  rows.forEach(function(r){
    if(!r.editable) return;
    if(r.type==='mirror'){
      MIRROR_ALIGN_SEQ[r.devKey].steps[r.idx].range=[r.range[0],r.range[1]];
      MIRROR_ALIGN_SEQ[r.devKey].steps[r.idx].nPts=r.nPts;
    }else{
      ALIGN_CONFIG[r.devKey].range=[r.range[0],r.range[1]];
      ALIGN_CONFIG[r.devKey].nPts=r.nPts;
    }
  });
}

// Show full alignment config dialog, returns Promise<boolean>
function _showAlignConfigDialog(){
  return new Promise(function(resolve){
    var existing=document.getElementById('_faConfigDlg');
    if(existing) existing.remove();
    var rows=_collectAllSteps();
    var overlay=document.createElement('div');
    overlay.id='_faConfigDlg';
    overlay.style.cssText='position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.65);z-index:9999;display:flex;align-items:center;justify-content:center';
    var box=document.createElement('div');
    box.style.cssText='background:var(--bg,#0a0f18);border:1px solid var(--gn,#40d89a);border-radius:6px;padding:0;min-width:320px;max-width:92vw;max-height:90vh;overflow:auto;color:var(--t1,#e0e0e0);font-family:monospace;zoom:var(--ui-zoom,1.8)';

    // Draggable title bar
    var hdr2=document.createElement('div');
    hdr2.style.cssText='display:flex;align-items:center;padding:8px 14px;background:var(--s1,#151f2e);border-bottom:1px solid var(--b0,rgba(80,160,255,.06));border-radius:6px 6px 0 0';
    hdr2.innerHTML='<span style="font-size:11px;font-weight:600;color:var(--gn,#40d89a);flex:1">Full Beamline Alignment \u2014 Configuration</span><span style="font-size:7px;color:var(--t3,#3d5068)">drag to move</span>';
    box.appendChild(hdr2);
    var cArea2=document.createElement('div');
    cArea2.style.cssText='padding:10px 14px';
    box.appendChild(cArea2);
    // Table
    var h='';
    h+='<table style="width:100%;border-collapse:collapse;font-size:8px;margin-bottom:10px">';
    h+='<tr style="color:var(--t2,#9ca3af);border-bottom:1px solid var(--bd,#2a3040)">';
    h+='<th style="text-align:left;padding:3px 4px">Device</th>';
    h+='<th style="text-align:left;padding:3px 4px">Step</th>';
    h+='<th style="text-align:left;padding:3px 4px">Motor</th>';
    h+='<th style="text-align:center;padding:3px 4px">Min</th>';
    h+='<th style="text-align:center;padding:3px 4px">Max</th>';
    h+='<th style="text-align:center;padding:3px 4px">Pts</th></tr>';
    var prevDev='';
    rows.forEach(function(r,ri){
      var devLabel=(r.device!==prevDev)?r.device:'';
      prevDev=r.device;
      var rowBg=(ri%2===0)?'':'background:var(--s1,#111822)';
      h+='<tr style="border-bottom:1px solid var(--s2,#1a2030);'+rowBg+'">';
      h+='<td style="padding:3px 4px;color:var(--bl,#4db8ff);font-weight:'+(devLabel?'600':'400')+'">'+devLabel+'</td>';
      h+='<td style="padding:3px 4px;color:var(--t1)">'+r.name+'</td>';
      h+='<td style="padding:3px 4px;color:var(--am,#ffb340)">'+r.motor+'</td>';
      if(r.editable&&r.range){
        h+='<td style="padding:2px 3px;text-align:center"><input id="_fac_min_'+ri+'" type="number" step="any" value="'+r.range[0]+'" style="width:55px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:8px;text-align:center;padding:2px"></td>';
        h+='<td style="padding:2px 3px;text-align:center"><input id="_fac_max_'+ri+'" type="number" step="any" value="'+r.range[1]+'" style="width:55px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:8px;text-align:center;padding:2px"></td>';
        h+='<td style="padding:2px 3px;text-align:center"><input id="_fac_npt_'+ri+'" type="number" min="3" max="201" value="'+r.nPts+'" style="width:40px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:8px;text-align:center;padding:2px"></td>';
      }else{
        var val=r.target!=null?('target='+r.target):'--';
        h+='<td colspan="3" style="padding:3px 4px;text-align:center;color:var(--t3)">'+val+'</td>';
      }
      h+='</tr>';
    });
    h+='</table>';
    // WB Slit scan gap
    var _wbGap=ALIGN_CONFIG.wbslit?ALIGN_CONFIG.wbslit.scanGap:null;
    var _wbGapVal=(_wbGap!=null&&_wbGap>0)?_wbGap:'';
    h+='<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;font-size:8px">'
      +'<span style="color:var(--bl,#4db8ff);font-weight:600">WB Slit</span>'
      +'<span style="color:var(--t2)">Scan Gap (mm):</span>'
      +'<input id="_fac_wbgap" type="number" step="0.01" min="0.01" value="'+_wbGapVal+'" placeholder="auto" '
      +'style="width:70px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:8px;text-align:center;padding:2px">'
      +'<span style="color:var(--t3)">empty = auto (1/10 beam FWHM)</span></div>';
    // SSA scan gap
    var _ssaScanGap=ALIGN_CONFIG.ssacenter?ALIGN_CONFIG.ssacenter.scanGap:null;
    var _ssaScanGapVal=(_ssaScanGap!=null&&_ssaScanGap>0)?_ssaScanGap:'';
    h+='<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;font-size:8px">'
      +'<span style="color:var(--bl,#4db8ff);font-weight:600">SSA</span>'
      +'<span style="color:var(--t2)">Scan Gap (μm):</span>'
      +'<input id="_fac_ssagap" type="number" step="1" min="1" value="'+_ssaScanGapVal+'" placeholder="auto" '
      +'style="width:70px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:8px;text-align:center;padding:2px">'
      +'<span style="color:var(--t3)">empty = auto (1/4 beam FWHM)</span></div>';
    // KB align SSA gap
    var _kbSsaH=ALIGN_CONFIG.kbalign?(ALIGN_CONFIG.kbalign.ssaGapH||100):100;
    var _kbSsaV=ALIGN_CONFIG.kbalign?(ALIGN_CONFIG.kbalign.ssaGapV||100):100;
    h+='<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;font-size:8px">'
      +'<span style="color:var(--bl,#4db8ff);font-weight:600">KB Align</span>'
      +'<span style="color:var(--t2)">SSA H-Gap (μm):</span>'
      +'<input id="_fac_kbssah" type="number" step="1" min="1" max="500" value="'+_kbSsaH+'" '
      +'style="width:60px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:8px;text-align:center;padding:2px">'
      +'<span style="color:var(--t2);margin-left:6px">V-Gap (μm):</span>'
      +'<input id="_fac_kbssav" type="number" step="1" min="1" max="500" value="'+_kbSsaV+'" '
      +'style="width:60px;background:var(--s2);color:var(--t1);border:1px solid var(--bd);border-radius:3px;font-size:8px;text-align:center;padding:2px">'
      +'<span style="color:var(--t3)">SSA gap during KB alignment</span></div>';
    // Full Auto checkbox
    h+='<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;font-size:8px">'
      +'<label style="display:flex;align-items:center;gap:4px;cursor:pointer;color:var(--am,#ffb340)">'
      +'<input id="_fac_fullAuto" type="checkbox" checked style="accent-color:var(--am,#ffb340)">'
      +'<span style="font-weight:600">Full Auto</span></label>'
      +'<span style="color:var(--t3)">Run all steps without pause (no Next button between steps)</span></div>';
    // Detector info
    h+='<div style="font-size:8px;color:var(--t3,#6b7280);margin-bottom:10px">Detector: XBPM-based intensity (MC ray-trace)</div>';
    // Buttons
    h+='<div style="display:flex;gap:6px;justify-content:flex-end">';
    h+='<button id="_facCancel" class="sb act">Cancel</button>';
    h+='<button id="_facStart" class="sb go act">\u25B6 Start</button>';
    h+='</div>';
    cArea2.innerHTML=h;
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    window._makePopupResizable(box, {minWidth:320, dragEl:hdr2});
    overlay.addEventListener('mousedown',function(e){if(e.target===overlay){overlay.remove();resolve(false);}});

    document.getElementById('_facCancel').onclick=function(){overlay.remove();resolve(false);};
    document.getElementById('_facStart').onclick=function(){
      // Full Auto mode
      var autoEl=document.getElementById('_fac_fullAuto');
      window._alignFullAuto=!!(autoEl&&autoEl.checked);
      // Read edited values
      rows.forEach(function(r,ri){
        if(!r.editable) return;
        var mnE=document.getElementById('_fac_min_'+ri);
        var mxE=document.getElementById('_fac_max_'+ri);
        var npE=document.getElementById('_fac_npt_'+ri);
        if(!mnE)return;
        var mn=parseFloat(mnE.value),mx=parseFloat(mxE.value),np=parseInt(npE.value);
        if(!isNaN(mn))r.range[0]=mn;
        if(!isNaN(mx))r.range[1]=mx;
        if(!isNaN(np)&&np>=3)r.nPts=np;
      });
      _applyRows(rows);
      // WB Slit gap
      var wbGapEl=document.getElementById('_fac_wbgap');
      if(wbGapEl&&ALIGN_CONFIG.wbslit){
        var gv=parseFloat(wbGapEl.value);
        ALIGN_CONFIG.wbslit.scanGap=(isNaN(gv)||gv<=0)?null:gv;
      }
      // SSA scan gap
      var ssaGapEl=document.getElementById('_fac_ssagap');
      if(ssaGapEl&&ALIGN_CONFIG.ssacenter){
        var sv=parseFloat(ssaGapEl.value);
        ALIGN_CONFIG.ssacenter.scanGap=(isNaN(sv)||sv<=0)?null:sv;
      }
      // KB SSA gap
      var kbSsaHEl=document.getElementById('_fac_kbssah');
      var kbSsaVEl=document.getElementById('_fac_kbssav');
      if(ALIGN_CONFIG.kbalign){
        if(kbSsaHEl){var v=parseFloat(kbSsaHEl.value);if(!isNaN(v)&&v>=1)ALIGN_CONFIG.kbalign.ssaGapH=v;}
        if(kbSsaVEl){var v2=parseFloat(kbSsaVEl.value);if(!isNaN(v2)&&v2>=1)ALIGN_CONFIG.kbalign.ssaGapV=v2;}
      }
      overlay.remove();
      resolve(true);
    };
  });
}

window.runFullAlignment=async function(opts){
  opts=opts||{};
  // If already aligning: reopen popup + re-create NEXT button
  if(state.aligning){
    window._alignPopupDismissed=false;
    var as=window._alignState;
    if(as&&as.active&&as.mid){
      openMirrorAlignPopup(as.mid);
      setTimeout(function(){
        if(typeof _restoreAlignPopupState==='function') _restoreAlignPopupState(as.mid);
        // Re-create NEXT button if waiting
        var pending=window._alignNextPending;
        if(pending){
          var infoEl=document.getElementById('maMonInfo')||document.getElementById('alignMonInfo');
          var parentEl=infoEl?infoEl.parentElement:null;
          if(parentEl){
            window._createAlignNextButtons(parentEl,pending.stepLabel,pending.stepIdx,pending.totalSteps,pending.resolve,pending.reject);
          }
        }
      },100);
    }
    return;
  }

  // Show config dialog if requested (UI button). NLP skips this.
  if(opts.showDialog){
    var confirmed=await _showAlignConfigDialog();
    if(!confirmed) return;
  }
  state.aligning=true;
  state._alignAborted=false;
  log('info','=== FULL BEAMLINE ALIGNMENT (unified, step-gated) ===');

  var sequence=_faSequence;

  try{
  // Reset indicators
  var cont=document.getElementById('alignProgress');
  if(cont)cont.style.display='block';
  sequence.forEach(function(step){
    var el=document.getElementById('alignSt_'+step.key);
    if(el){el.textContent='--';el.style.color='var(--t3)';}
  });

  for(var i=0;i<sequence.length;i++){
    if(state._alignAborted){
      log('warn','Full alignment aborted at step '+(i+1));
      break;
    }
    var step=sequence[i];
    if(typeof updateAlignProgress==='function') updateAlignProgress(i,sequence.length,step.label,'running');
    var el=document.getElementById('alignSt_'+step.key);
    if(el){el.textContent='scanning...';el.style.color='var(--am)';}

    try{
      if(step.type==='mirror'){
        await runMirrorAlignUI(step.key,{skipGuard:true});
      }else{
        await runAlignStepUI(step.key,{skipGuard:true});
      }
      // Update right panel status (always, regardless of popup visibility)
      if(el){
        var resultText='OK';
        // For mirror types, get last result from _alignState
        if(step.type==='mirror'&&window._alignState&&window._alignState.results){
          var mrs=window._alignState.results;
          var lastR=mrs.length>0?mrs[mrs.length-1]:null;
          if(lastR&&lastR.center!=null) resultText=lastR.center.toFixed(3);
          else if(lastR&&lastR.value!=null) resultText=typeof lastR.value==='number'?lastR.value.toFixed(3):String(lastR.value);
          else if(lastR&&lastR.pass!=null) resultText=lastR.pass?'PASS':'FAIL';
        }
        el.textContent=resultText;el.style.color='var(--gn)';
      }
      if(typeof updateAlignProgress==='function') updateAlignProgress(i,sequence.length,step.label,'done');

      // === WAIT FOR USER NEXT ===
      // After each step, pause and wait for user confirmation
      await window._alignWaitForNext(step.label, i, sequence.length);

    }catch(e){
      if(state._alignAborted){
        log('warn','Full alignment aborted by user at: '+step.label);
        if(el){el.textContent='ABORT';el.style.color='var(--am)';}
        if(typeof updateAlignProgress==='function') updateAlignProgress(i,sequence.length,step.label,'fail');
        break;
      }
      log('err','Align '+step.label+': '+e.message);
      if(el){el.textContent='FAIL';el.style.color='var(--rd)';}
      if(typeof updateAlignProgress==='function') updateAlignProgress(i,sequence.length,step.label,'fail');

      // On failure, also wait -- user can choose to continue or abort
      try{
        await window._alignWaitForNext(step.label+' (FAILED)', i, sequence.length);
      }catch(e2){
        log('warn','Full alignment aborted after failure: '+step.label);
        break;
      }
    }
  }

  log('info','=== Full alignment complete ===');
  var liveBar=document.getElementById('alignLiveBar');
  if(liveBar)liveBar.innerHTML='<span style="color:var(--gn)">Alignment complete</span>';
  }finally{
    state.aligning=false;
    state._alignAborted=false;
    window._alignFullAuto=true;
    // Alignment changed motor positions → recalculate beam
    if(typeof _invalidateMCCache==='function') _invalidateMCCache();
    if(typeof updateLiveBeamInfo==='function') try{updateLiveBeamInfo();}catch(e){}
  }
};

console.log('[alignment/03_runners] Full alignment orchestrator + config dialog loaded');
})();

// ===================================================================
// buildAlignPanel -- Per-Device with Setup, no Individual Steps
// ===================================================================
(function(){
window.buildAlignPanel = function() {
  var el = document.getElementById('alignStepsList');
  if (!el) return;
  var html = '';
  // Full Beamline Alignment
  html += '<div style="display:flex;align-items:center;gap:4px;padding:4px 6px;background:var(--s1);border:1px solid var(--gn);border-radius:4px;margin-bottom:6px">';
  html += '<span style="font-size:9px;color:var(--gn);flex:1;font-weight:600">Full Beamline Alignment (WBS\u2192M1\u2192DCM\u2192M2\u2192SSA\u2192KBV\u2192KBH)</span>';
  html += '<button class="sb go act" onclick="runFullAlignment({showDialog:true})">Auto Run</button>';
  html += '</div>';
  html += '<div id="alignProgress" style="display:none;margin-bottom:6px"></div>';
  html += '<div id="alignLiveBar" style="margin-bottom:4px"></div>';
  html += '<div style="font-size:9px;color:var(--t2);margin-bottom:4px;font-weight:600">Per-Device Sequences</div>';
  var seqItems = [
    {type:'strategy', key:'wbslit',   label:'WB Slit H-Centering'},
    {type:'strategy', key:'wbslit_v', label:'WB Slit V-Centering'},
    {type:'mirror',   key:'m1',       label:'M1 Full Alignment'},
    {type:'mirror',   key:'dcm',      label:'DCM Full Alignment'},
    {type:'mirror',   key:'m2',       label:'M2 Full Alignment'},
    {type:'strategy', key:'ssacenter',  label:'SSA H-Centering'},
    {type:'strategy', key:'ssacenter_v',label:'SSA V-Centering'},
    {type:'mirror',   key:'kbv',      label:'KB-V Alignment'},
    {type:'mirror',   key:'kbh',      label:'KB-H Alignment'}
  ];
  seqItems.forEach(function(s){
    var stepsInfo = '';
    if (s.type==='mirror' && MIRROR_ALIGN_SEQ[s.key]) {
      stepsInfo = ' (' + MIRROR_ALIGN_SEQ[s.key].steps.length + ' steps)';
    }
    var onclick = s.type==='mirror'
      ? "runMirrorAlignUI('"+s.key+"')"
      : "runAlignStepUI('"+s.key+"')";
    html += '<div style="display:flex;align-items:center;gap:4px;padding:3px 6px;background:var(--s2);border-radius:4px;margin-bottom:3px">';
    html += '<span id="alignSt_'+s.key+'" style="font-size:8px;color:var(--t3);min-width:32px;text-align:right">--</span>';
    html += '<span style="font-size:8px;color:var(--t1);flex:1">' + s.label + stepsInfo + '</span>';
    html += '<button class="sb" onclick="openDeviceAlignSetup(\''+s.key+'\')" style="font-size:8px;padding:2px 6px" title="Scan setup">\u2699</button>';
    html += '<button class="sb" onclick="'+onclick+'" style="font-size:8px;padding:2px 8px;background:var(--gn);color:#000">Run</button>';
    html += '</div>';
  });
  el.innerHTML = html;
};
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof expandAxisRange!=="undefined")globalThis.expandAxisRange=expandAxisRange;
if(typeof mcCentroid!=="undefined")globalThis.mcCentroid=mcCentroid;
if(typeof mcSig!=="undefined")globalThis.mcSig=mcSig;
if(typeof KB_PARAMS!=="undefined")globalThis.KB_PARAMS=KB_PARAMS;
if(typeof MIRROR_ALIGN_SEQ!=="undefined")globalThis.MIRROR_ALIGN_SEQ=MIRROR_ALIGN_SEQ;
if(typeof _alignFullAuto!=="undefined")globalThis._alignFullAuto=_alignFullAuto;
if(typeof _alignNextPending!=="undefined")globalThis._alignNextPending=_alignNextPending;
if(typeof _alignPitchZero!=="undefined")globalThis._alignPitchZero=_alignPitchZero;
if(typeof _alignPopupDismissed!=="undefined")globalThis._alignPopupDismissed=_alignPopupDismissed;
if(typeof _alignRayCount!=="undefined")globalThis._alignRayCount=_alignRayCount;
if(typeof _alignStepResolve!=="undefined")globalThis._alignStepResolve=_alignStepResolve;
if(typeof _alignWaitForNext!=="undefined")globalThis._alignWaitForNext=_alignWaitForNext;
if(typeof _alignWaitingStep!=="undefined")globalThis._alignWaitingStep=_alignWaitingStep;
if(typeof _applyRows!=="undefined")globalThis._applyRows=_applyRows;
if(typeof _autoDetectReflectedROI!=="undefined")globalThis._autoDetectReflectedROI=_autoDetectReflectedROI;
if(typeof _bpmFovROI!=="undefined")globalThis._bpmFovROI=_bpmFovROI;
if(typeof _collectAllSteps!=="undefined")globalThis._collectAllSteps=_collectAllSteps;
if(typeof _createAlignNextButtons!=="undefined")globalThis._createAlignNextButtons=_createAlignNextButtons;
if(typeof _faSequence!=="undefined")globalThis._faSequence=_faSequence;
if(typeof _isAlignPopupVisible!=="undefined")globalThis._isAlignPopupVisible=_isAlignPopupVisible;
if(typeof _kbAlignSsaProgrammatic!=="undefined")globalThis._kbAlignSsaProgrammatic=_kbAlignSsaProgrammatic;
if(typeof _kbAlignSsaUserChanged!=="undefined")globalThis._kbAlignSsaUserChanged=_kbAlignSsaUserChanged;
if(typeof _lastAlignResult!=="undefined")globalThis._lastAlignResult=_lastAlignResult;
if(typeof _roiCentroid!=="undefined")globalThis._roiCentroid=_roiCentroid;
if(typeof _roiSig!=="undefined")globalThis._roiSig=_roiSig;
if(typeof _showAlignConfigDialog!=="undefined")globalThis._showAlignConfigDialog=_showAlignConfigDialog;
if(typeof _showAlignConfirmButtons!=="undefined")globalThis._showAlignConfirmButtons=_showAlignConfirmButtons;
if(typeof _waitUserConfirm!=="undefined")globalThis._waitUserConfirm=_waitUserConfirm;
if(typeof abortAlignment!=="undefined")globalThis.abortAlignment=abortAlignment;
if(typeof alignNextStep!=="undefined")globalThis.alignNextStep=alignNextStep;
if(typeof buildAlignPanel!=="undefined")globalThis.buildAlignPanel=buildAlignPanel;
if(typeof runFullAlignment!=="undefined")globalThis.runFullAlignment=runFullAlignment;
if(typeof runMirrorAlign!=="undefined")globalThis.runMirrorAlign=runMirrorAlign;
if(typeof setAlignConfig!=="undefined")globalThis.setAlignConfig=setAlignConfig;
if(typeof setMirrorAlignRange!=="undefined")globalThis.setMirrorAlignRange=setMirrorAlignRange;
