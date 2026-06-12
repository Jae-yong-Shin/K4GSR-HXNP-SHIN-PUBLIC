// ===== motors.js v4.11 -- Declarative Device Config =====
// ===== motors.js v4.11 -- Declarative Device Configuration System =====
// @module control/01_motors
// @exports DEVICE_CONFIGS, DEVICE_REGISTRY, MOTORS, Motor, PV_TO_MOTOR, SIM_INTEGRATION_MS, SIM_SPEED_FACTOR, SYNC_HANDLERS, _debouncedPhysicsUpdate, _kbAlignSsaUserChanged, _realModeMCTimer, _runPhysicsOrLayout, _syncPhysicsPending, _syncPhysicsTimer, addDevice, ...
// Single source of truth: DEVICE_CONFIGS defines all beamline hardware.
// Motors, PVs, IDs, names, sync bindings are ALL auto-generated.
//
// TO ADD A NEW DEVICE: Just add an entry to DEVICE_CONFIGS. That's it.
// TO RENAME A PV:      Call renamePV('old:pv', 'new:pv')
// TO ADD A MOTOR AXIS: Add to the axes{} of any device config
// =====================================================================
'use strict';

// Simulation speed factor: real motor time / this = sim time
// 20 -> a 20-second real move completes in 1 second in simulation
window.SIM_SPEED_FACTOR = 20;
// Simulated detector integration time per scan point
// Real XBPM integration ~ 1s -> sim = 1000ms / SIM_SPEED_FACTOR = 50ms
window.SIM_INTEGRATION_MS = Math.max(50, Math.round(1000 / (window.SIM_SPEED_FACTOR || 20)));

// ========== Motor Class (ES5 constructor function) ==========
function Motor(cfg){
  this.id        = cfg.id;
  this.name      = cfg.name;
  this.unit      = cfg.unit || 'mm';
  this.value     = (cfg.value != null) ? cfg.value : 0;
  this.min       = (cfg.min != null) ? cfg.min : -1e6;
  this.max       = (cfg.max != null) ? cfg.max : 1e6;
  this.step      = cfg.step || 0.001;
  this.resolution= cfg.resolution || 0.0001;
  this.backlash  = cfg.backlash || 0;
  this.speed     = cfg.speed || 1;
  this.moving    = false;
  this.target    = this.value;
  this.pv        = cfg.pv || null;
  this.deviceId  = cfg.deviceId || null;   // parent device group
  this.axisKey   = cfg.axisKey || null;     // key within device
  this.sync      = cfg.sync || null;        // {stateKey, slider, fn}
  this.correctionTable = null;
  this.correctionPoly  = null;
  this.description     = cfg.description || '';
}

Motor.prototype.stop = function(){
  this._aborted = true;
  this.moving = false;
  this.target = this.value;
  if(this.pv && state.mode === 'real' && typeof epicsPut === 'function')
    epicsPut(this.pv + '.STOP', 1);
  log('warn', 'Motor ' + this.id + ' STOPPED at ' + this.value.toFixed(4));
};

Motor.prototype.moveTo = function(v, cb){
  var self = this;
  self._aborted = false;
  var origV = v;
  v = Math.max(self.min, Math.min(self.max, v));
  if(v !== origV)
    log('warn', 'Motor ' + self.id + ': limit clamped ' + origV.toFixed(4) + ' -> ' + v.toFixed(4));
  if(state.mode === 'real' && self.pv){
    if(typeof epicsPut === 'function') epicsPut(self.pv, v);
    else { log('info', 'EPICS caput ' + self.pv + ' ' + v); }
    self.target = v; self.moving = true; self._syncState();
    // Wait for server readback to reach target
    var motor = self;
    var tol = self.resolution * 2 || 0.001;
    return new Promise(function(resolve) {
      if(Math.abs(motor.value - v) < tol){
        motor.moving = false; motor._syncState(); if(cb) cb(v); resolve(); return;
      }
      var tmr = setTimeout(function() {
        pvUnsubscribe(motor.pv, onUpd);
        motor.moving = false; motor._syncState(); if(cb) cb(motor.value);
        log('warn', 'Motor ' + motor.id + ' timeout waiting for ' + v.toFixed(4));
        resolve();
      }, 15000);
      function onUpd(updPV, val) {
        var isRBV = updPV.indexOf('.RBV') === updPV.length - 4 || EPICS_STATE.mode === 'sim';
        if(isRBV && Math.abs(val - v) < tol){
          clearTimeout(tmr);
          pvUnsubscribe(motor.pv, onUpd);
          motor.moving = false; motor._syncState(); if(cb) cb(val);
          resolve();
        }
      }
      pvSubscribe(motor.pv, onUpd);
    });
  }
  // Backlash compensation (sim only): overshoot on reverse direction
  function doBacklash(){
    if(self.backlash > 0 && v < self.value){
      var overshoot = Math.max(self.min, v - self.backlash);
      self.target = overshoot; self.moving = true;
      var dv0 = (overshoot - self.value);
      var rt0 = Math.abs(dv0) / self.speed;
      var st0 = rt0 / (window.SIM_SPEED_FACTOR || 20);
      var tm0 = Math.max(30, Math.min(2000, st0 * 1000));
      var steps0 = Math.max(1, Math.min(15, Math.round(tm0 / 30)));
      var dl0 = Math.round(tm0 / steps0);
      var dd0 = dv0 / steps0;
      var idx0 = 0;
      return new Promise(function(resolve){
        function stepFn(){
          if(self._aborted){ self._aborted = false; self.moving = false; resolve('abort'); return; }
          if(idx0 >= steps0){ self.value = overshoot; self._syncState(); resolve('ok'); return; }
          setTimeout(function(){
            self.value += dd0;
            self._syncState();
            idx0++;
            stepFn();
          }, dl0);
        }
        stepFn();
      });
    }
    return Promise.resolve('ok');
  }

  function doMain(){
    self.target = v; self.moving = true;
    // Realistic timing: realTime = distance/speed, simTime = realTime/SIM_SPEED_FACTOR
    var realTimeSec = Math.abs(v - self.value) / self.speed;
    var simTimeSec = realTimeSec / (window.SIM_SPEED_FACTOR || 20);
    var totalMs = Math.max(30, Math.min(5000, simTimeSec * 1000));
    var steps = Math.max(1, Math.min(30, Math.round(totalMs / 30)));
    var delayMs = Math.round(totalMs / steps);
    var dv = (v - self.value) / steps;
    var idx = 0;
    return new Promise(function(resolve){
      function stepFn(){
        if(self._aborted){ self._aborted = false; self.moving = false; resolve(); return; }
        if(idx >= steps){
          if(self._aborted){ self._aborted = false; self.moving = false; resolve(); return; }
          self.value = v; self.moving = false; self._syncState(); if(cb) cb(self.value);
          resolve();
          return;
        }
        setTimeout(function(){
          self.value += dv;
          self._syncState();
          if(cb) cb(self.value);
          idx++;
          stepFn();
        }, delayMs);
      }
      stepFn();
    });
  }

  return doBacklash().then(function(result){
    if(result === 'abort') return;
    return doMain();
  });
};

Motor.prototype._syncState = function(){
  if(!this.sync||!this.sync.stateKey)return;
  var k=this.sync.stateKey;
  if(k.charAt(0)==='_')return; // skip special keys like _dcm_theta_to_energy
  state[k]=this.value;
};

Motor.prototype.moveRel = function(dv, cb){ return this.moveTo(this.value + dv, cb); };

Motor.prototype.correctedValue = function(energy){
  var v = this.value;
  if(this.correctionPoly){
    var corr = 0;
    for(var i = 0; i < this.correctionPoly.length; i++)
      corr += this.correctionPoly[i] * Math.pow(energy, i);
    v += corr;
  }
  if(this.correctionTable){
    var t = this.correctionTable;
    v += interpLin(energy, t.energies, t.offsets);
  }
  return v;
};

Motor.prototype.toJSON = function(){
  return { id:this.id, name:this.name, unit:this.unit, pv:this.pv,
           value:this.value, min:this.min, max:this.max, step:this.step,
           resolution:this.resolution, backlash:this.backlash, speed:this.speed,
           deviceId:this.deviceId, axisKey:this.axisKey };
};

function interpLin(x, xs, ys){
  if(x <= xs[0]) return ys[0];
  if(x >= xs[xs.length-1]) return ys[ys.length-1];
  for(var i = 0; i < xs.length-1; i++){
    if(x >= xs[i] && x <= xs[i+1]){
      var f = (x - xs[i]) / (xs[i+1] - xs[i]);
      return ys[i] + f * (ys[i+1] - ys[i]);
    }
  }
  return ys[0];
}

// ========================================================================
// DEVICE_CONFIGS -- Single Source of Truth for ALL beamline hardware
// ========================================================================
// Each device config:
//   id:        Unique device group ID (used as MOTORS key)
//   label:     Human-readable name
//   pvPrefix:  EPICS PV prefix (e.g. 'BL10:M1')
//   icon:      Optional emoji for UI
//   category:  'source'|'optics'|'mono'|'aperture'|'focusing'|'sample'|'diag'
//   vendor:    Equipment manufacturer (optional)
//   model:     Equipment model number (optional)
//   axes:      { axisKey: { ...axis definition } }
//
// Each axis definition:
//   name:       Display name (auto-prefixed with device label if not explicit)
//   pvSuffix:   PV suffix -> full PV = pvPrefix + ':' + pvSuffix
//   unit, value, min, max, step, resolution, backlash, speed
//   sync:       Optional { stateKey, slider, fn } for binding to physics state
//   description: Optional tooltip text with hardware details
//
// -- Axis Naming Convention --
//   Translation:  x (lateral/horizontal), y (height/vertical), z (along-beam)
//   Rotation:     pitch (horiz axis), roll (beam axis), yaw (vert axis)
//   Fine/Piezo:   pitch_fine, roll_fine (appended '_fine')
//   Bender:       bend_u (upstream), bend_d (downstream)
//   Aperture:     hgap, vgap (gap), hcen, vcen (center)
//   Blade:        top, bottom, inboard, outboard
//   Coarse:       cx, cy, cz (coarse translation)
//   Fine:         fx, fy, fz (fine/nano translation)
//   Scan:         sx, sy (fast scan axes)
//
// -- Hardware Sources --
//   DCM:       XDS Oxford HDCM-HCCM Q11055 (Renishaw Resolute encoders, ACS SPiiEC)
//   M1/M2:     FMB Oxford HHLMS (Renishaw Resolute, PI P-843 piezo)
//   WB Slit:   JJ X-Ray Model 24053 (50mm stroke, self-locking worm, 5nm encoder)
//   KB:        JTEC JM2000-200 (Si substrate, 3 stripes Si/Rh/Pt)
//   Sample:    KOHZU coarse + PI PIMars P-563.3CD + PI P-733.2CD scanner
//   BPM:       Sydor SIDBPM403 (diamond sensor)
// ========================================================================

var DEVICE_CONFIGS = [
  // -- Source --
  {
    id: 'ivu', label: 'IVU24 Undulator', pvPrefix: 'BL10:IVU',
    icon: '', category: 'source',
    vendor: 'Korea-4GSR standard', model: 'IVU24 (24mm period, 123 periods)',
    axes: {
      targetEnergy: { name:'Target Energy', pvSuffix:'TargetE', unit:'keV', value:10.0, min:4, max:40,
             step:0.01, resolution:0.001, noSlider:true,
             sync:{ stateKey:'targetEnergy', slider:'targetESlider', fn:'setTargetEnergy' },
             description:'Target photon energy (auto-selects harmonic+gap; buttons only, no continuous-drag GPU recompute)' },
      gap: { name:'Gap', pvSuffix:'Gap', unit:'mm', value:7.0, min:5, max:25,
             step:0.1, resolution:0.01, backlash:0.05, speed:0.5,
             sync:{ stateKey:'gap', slider:'gapSlider', fn:'updateUnd' },
             description:'Undulator magnetic gap (2 motors, US+DS jaws)' },
      taperGap: { name:'Taper Gap', pvSuffix:'TaperGap', unit:'mm', value:0, min:-2, max:2,
             step:0.001, resolution:0.001, speed:0.5,
             description:'Gap taper (US-DS differential, APS convention)' },
      harmonic: { name:'Harmonic', pvSuffix:'Harmonic', unit:'', value:5, min:1, max:13,
             step:2, resolution:1,
             sync:{ stateKey:'harmonic' },
             description:'Selected undulator harmonic (odd: 1,3,5,...,13)' },
      girderX: { name:'Girder X', pvSuffix:'GirderX', unit:'mm', value:0, min:-5, max:5,
             step:0.01, resolution:0.001, speed:1,
             description:'Girder horizontal translation (5-DOF cam mover)' },
      girderY: { name:'Girder Y', pvSuffix:'GirderY', unit:'mm', value:0, min:-5, max:5,
             step:0.01, resolution:0.001, speed:1,
             description:'Girder vertical translation (5-DOF cam mover)' },
      girderPitch: { name:'Girder Pitch', pvSuffix:'GirderPitch', unit:'urad', value:0, min:-200, max:200,
             step:0.1, resolution:0.01, speed:50,
             description:'Girder pitch angle (5-DOF cam mover)' },
      girderYaw: { name:'Girder Yaw', pvSuffix:'GirderYaw', unit:'urad', value:0, min:-200, max:200,
             step:0.1, resolution:0.01, speed:50,
             description:'Girder yaw angle (5-DOF cam mover)' },
      encUS: { name:'Encoder US', pvSuffix:'EncUS', unit:'mm', value:7.0, min:5, max:25,
             step:0.001, resolution:0.0001,
             description:'Upstream linear encoder readback (Fagor SA-070)' },
      encDS: { name:'Encoder DS', pvSuffix:'EncDS', unit:'mm', value:7.0, min:5, max:25,
             step:0.001, resolution:0.0001,
             description:'Downstream linear encoder readback (Fagor SA-070)' }
    }
  },

  // -- Front-End Masks --
  {
    id: 'fmask', label: 'Fixed Mask', pvPrefix: 'BL10:FMASK',
    icon: '', category: 'optics',
    axes: {
      x:    { name:'X',     pvSuffix:'X',    unit:'mm', value:0, min:-20, max:20, step:0.01, resolution:0.005, backlash:0.005, speed:2 },
      y:    { name:'Y',     pvSuffix:'Y',    unit:'mm', value:0, min:-20, max:20, step:0.01, resolution:0.005, backlash:0.005, speed:2 },
      hgap: { name:'H-Gap', pvSuffix:'Hgap', unit:'mm', value:4.0, min:0.1, max:20, step:0.1, resolution:0.01, backlash:0.02, speed:1 },
      vgap: { name:'V-Gap', pvSuffix:'Vgap', unit:'mm', value:4.0, min:0.1, max:20, step:0.1, resolution:0.01, backlash:0.02, speed:1 }
    }
  },
  {
    id: 'mmask', label: 'Movable Mask', pvPrefix: 'BL10:MMASK',
    icon: '', category: 'optics',
    axes: {
      x:    { name:'X',     pvSuffix:'X',    unit:'mm', value:0, min:-20, max:20, step:0.01, resolution:0.005 },
      y:    { name:'Y',     pvSuffix:'Y',    unit:'mm', value:0, min:-20, max:20, step:0.01, resolution:0.005 },
      hgap: { name:'H-Gap', pvSuffix:'Hgap', unit:'mm', value:4.0, min:0.1, max:20, step:0.01, resolution:0.005 },
      vgap: { name:'V-Gap', pvSuffix:'Vgap', unit:'mm', value:4.0, min:0.1, max:20, step:0.01, resolution:0.005 }
    }
  },

  // -- White Beam Slit (JJ X-Ray Model 24053, 50mm stroke, self-locking worm) --
  {
    id: 'wbslit', label: 'WB Slit', pvPrefix: 'BL10:WBS',
    icon: '', category: 'aperture',
    vendor: 'JJ X-Ray', model: '24053',
    axes: {
      top:     { name:'Top',      pvSuffix:'Top',  unit:'mm', value:0.5,  min:-25, max:25, step:0.001, resolution:0.0002, backlash:0, speed:1,
                 description:'Top blade (50mm stroke, 5nm encoder, self-locking)' },
      bottom:  { name:'Bottom',   pvSuffix:'Bot',  unit:'mm', value:-0.5, min:-25, max:25, step:0.001, resolution:0.0002, backlash:0, speed:1,
                 description:'Bottom blade' },
      inboard: { name:'Inboard',  pvSuffix:'Inb',  unit:'mm', value:-1,   min:-25, max:25, step:0.001, resolution:0.0002, backlash:0, speed:1,
                 description:'Inboard blade' },
      outboard:{ name:'Outboard', pvSuffix:'Outb', unit:'mm', value:1,    min:-25, max:25, step:0.001, resolution:0.0002, backlash:0, speed:1,
                 description:'Outboard blade' },
      hgap:    { name:'H-Gap',    pvSuffix:'Hgap', unit:'mm', value:1.2,  min:0.01, max:48, step:0.001, resolution:0.001, backlash:0, speed:1,
                 sync:{ stateKey:'wbH', uiId:'wbH' },
                 description:'Virtual H-gap (max aperture 48mm)' },
      vgap:    { name:'V-Gap',    pvSuffix:'Vgap', unit:'mm', value:1.2,  min:0.01, max:48, step:0.001, resolution:0.001, backlash:0, speed:1,
                 sync:{ stateKey:'wbV', uiId:'wbV' },
                 description:'Virtual V-gap (max aperture 48mm)' },
      hcenter: { name:'H-Center', pvSuffix:'Hcen', unit:'mm', value:0,    min:-20, max:20, step:0.001, resolution:0.001, backlash:0, speed:1,
                 sync:{ stateKey:'wbCX' },
                 description:'Virtual H-center (computed from blades)' },
      vcenter: { name:'V-Center', pvSuffix:'Vcen', unit:'mm', value:0,    min:-20, max:20, step:0.001, resolution:0.001, backlash:0, speed:1,
                 sync:{ stateKey:'wbCY' },
                 description:'Virtual V-center (computed from blades)' }
    }
  },

  // -- Attenuator (between WB Slit and XBPM-WB, 4 filter slots) --
  {
    id: 'atten', label: 'Attenuator', pvPrefix: 'BL10:ATT',
    icon: '', category: 'optics',
    axes: {
      x: { name:'X-trans', pvSuffix:'X', unit:'mm', value:0, min:-25, max:25, step:0.01, resolution:0.005, speed:2,
           description:'Lateral translation for alignment' },
      y: { name:'Y-trans', pvSuffix:'Y', unit:'mm', value:0, min:-25, max:25, step:0.01, resolution:0.005, speed:2,
           description:'Vertical translation for alignment' }
    }
  },

  // -- M1 Mirror (FMB Oxford HHLMS, fixed curvature, Pt single coating, Renishaw Resolute encoders) --
  {
    id: 'm1', label: 'M1 Mirror', pvPrefix: 'BL10:M1',
    icon: '', category: 'optics',
    vendor: 'FMB Oxford', model: 'HHLMS',
    axes: {
      x:          { name:'x',            pvSuffix:'Tx',     unit:'mm',   value:0, min:-10, max:10, step:0.01, resolution:0.001, speed:1,
                    description:'Lateral translation (in-vacuum)' },
      y:          { name:'y',            pvSuffix:'Ty',     unit:'mm',   value:0, min:-5, max:5, step:0.001, resolution:0.001, speed:0.5,
                    description:'Height position (wedge mechanism)' },
      z:          { name:'z',            pvSuffix:'Tz',     unit:'mm',   value:0, min:-300, max:300, step:0.1, resolution:0.01, speed:2,
                    description:'Along-beam translation (RC alignment axis)' },
      pitch:      { name:'pitch',        pvSuffix:'Pitch',  unit:'mrad', value:2.5, min:-2, max:5, step:0.001, resolution:0.0001, backlash:0.002, speed:0.5,
                    sync:{ stateKey:'m1pitch', slider:'m1Slider', fn:'updateM1' },
                    description:'Pitch angle (curved granite mechanism)' },
      pitch_fine: { name:'pitch fine',   pvSuffix:'PitchF', unit:'\u03BCrad', value:0, min:-50, max:50, step:0.01, resolution:0.001, speed:100,
                    description:'Piezo fine pitch (PI P-843, 60um stroke)' },
      roll:       { name:'roll',         pvSuffix:'Roll',   unit:'mrad', value:0, min:-2, max:2, step:0.001, resolution:0.0001,
                    description:'Roll angle (MANUAL adjustment only)' },
      yaw:        { name:'yaw',          pvSuffix:'Yaw',    unit:'mrad', value:0, min:-2, max:2, step:0.001, resolution:0.0001,
                    description:'Yaw angle (MANUAL adjustment only)' }
    },
    corrections: {
      pitch: {
        type: 'table',
        energies: [5, 8, 10, 15, 20, 25, 30, 35, 40],
        offsets:  [0.008, 0.003, 0, 0, -0.002, -0.004, -0.005, -0.006, -0.007]
      }
    }
  },

  // -- DCM (XDS Oxford HDCM-HCCM Q11055, 8 motorized axes, ACS SPiiEC controller) --
  {
    id: 'dcm', label: 'DCM Si(111)', pvPrefix: 'BL10:DCM',
    icon: '', category: 'mono',
    vendor: 'XDS Oxford', model: 'HDCM-HCCM Q11055',
    axes: {
      theta:   { name:'Bragg th',       pvSuffix:'Theta',    unit:'deg',    value:11.402, min:-1, max:20, step:0.0001, resolution:0.00001, backlash:0.001, speed:0.05,
                 sync:{ stateKey:'_dcm_theta_to_energy', fn:'_dcmThetaSync' },
                 description:'Bragg angle (<=0.25\u03BCrad res, Renishaw Resolute)' },
      y1:      { name:'C1 y',         pvSuffix:'Y1',       unit:'mm',     value:0, min:-2.5, max:2.5, step:0.01, resolution:0.002, speed:0.5,
                 description:'1st crystal y-translation along surface normal (half-cut scan axis)' },
      chi1:    { name:'C1 yaw',       pvSuffix:'Chi1',     unit:'arcsec', value:0, min:-300, max:300, step:0.1, resolution:0.01, speed:1,
                 description:'1st crystal yaw alignment' },
      tx:      { name:'C1 x',         pvSuffix:'TX',       unit:'mm',     value:0, min:-12.5, max:12.5, step:0.01, resolution:0.002, speed:0.5,
                 description:'X-translation for stripe selection (<=2um res)' },
      y2:      { name:'C2 y',         pvSuffix:'Y2',       unit:'mm',     value:0, min:-25, max:25, step:0.01, resolution:0.002, speed:0.5,
                 description:'Y-translation beam offset (50mm range, <=2um res)' },
      z2:      { name:'C2 gap (x)',    pvSuffix:'Z2',       unit:'mm',     value:6.12, min:0, max:25, step:0.001, resolution:0.001, speed:0.5,
                 description:'Crystal gap perpendicular to C1 surface (<1um res, auto-tracks energy for fixed exit)' },
      dTheta2: { name:'C2 pitch',     pvSuffix:'DTheta2',  unit:'arcsec', value:0, min:-2520, max:2520, step:0.1, resolution:0.1, speed:10,
                 description:'2nd crystal pitch (+/-0.7deg, <0.5\u03BCrad res)' },
      roll2:   { name:'C2 roll',      pvSuffix:'Roll2',    unit:'arcsec', value:0, min:-2520, max:2520, step:0.1, resolution:0.1, speed:10,
                 description:'2nd crystal roll (+/-0.7deg, <0.5\u03BCrad res)' },
      dTheta2F:{ name:'C2 pitch (piezo)', pvSuffix:'DTheta2F', unit:'arcsec', value:0, min:-10.3, max:10.3, step:0.01, resolution:0.01, speed:100,
                 description:'Piezo fine pitch (100\u03BCrad range, 0.05\u03BCrad res)' }
    },
    corrections: {
      theta: { type: 'poly', coeffs: [0, 0.00003, -0.0000001] }
    }
  },

  // -- M2 Mirror (FMB Oxford HHLMS, 6 motorized + 2 manual axes, Renishaw Resolute encoders) --
  {
    id: 'm2', label: 'M2 Mirror', pvPrefix: 'BL10:M2',
    icon: '', category: 'optics',
    vendor: 'FMB Oxford', model: 'HHLMS',
    axes: {
      x:          { name:'x',            pvSuffix:'Tx',     unit:'mm',   value:0, min:-10, max:10, step:0.01, resolution:0.001, speed:1,
                    description:'Lateral translation (in-vacuum, stripe selection)' },
      y:          { name:'y',            pvSuffix:'Ty',     unit:'mm',   value:0, min:-5, max:5, step:0.001, resolution:0.001, speed:0.5,
                    description:'Height position (wedge mechanism)' },
      z:          { name:'z',            pvSuffix:'Tz',     unit:'mm',   value:0, min:-200, max:200, step:0.1, resolution:0.01, speed:2,
                    description:'Along-beam translation (RC alignment axis)' },
      pitch:      { name:'pitch',        pvSuffix:'Pitch',  unit:'mrad', value:2.5, min:-2, max:5, step:0.001, resolution:0.0001, backlash:0.002, speed:0.5,
                    sync:{ stateKey:'m2pitch', slider:'m2Slider', fn:'updateM2' },
                    description:'Pitch angle (curved granite mechanism)' },
      pitch_fine: { name:'pitch fine',   pvSuffix:'PitchF', unit:'\u03BCrad', value:0, min:-50, max:50, step:0.01, resolution:0.001, speed:100,
                    description:'Piezo fine pitch (PI P-843, 60um stroke)' },
      roll:       { name:'roll',         pvSuffix:'Roll',   unit:'mrad', value:0, min:-2, max:2, step:0.001, resolution:0.0001,
                    description:'Roll angle (MANUAL adjustment only)' },
      yaw:        { name:'yaw',          pvSuffix:'Yaw',    unit:'mrad', value:0, min:-2, max:2, step:0.001, resolution:0.0001,
                    description:'Yaw angle (MANUAL adjustment only)' },
      bend_u:     { name:'bend up',      pvSuffix:'BendU',  unit:'Nm',   value:0, min:-50, max:50, step:0.1, resolution:0.05, speed:1,
                    description:'Upstream bender (cam mechanism)' },
      bend_d:     { name:'bend dn',      pvSuffix:'BendD',  unit:'Nm',   value:0, min:-50, max:50, step:0.1, resolution:0.05, speed:1,
                    description:'Downstream bender (cam mechanism)' }
    },
    corrections: {
      pitch: {
        type: 'table',
        energies: [5, 8, 10, 15, 20, 25, 30, 35, 40],
        offsets:  [0.006, 0.002, 0, -0.001, -0.003, -0.004, -0.005, -0.006, -0.006]
      }
    }
  },

  // -- SSA --
  {
    id: 'ssa', label: 'SSA', pvPrefix: 'BL10:SSA',
    icon: '', category: 'aperture',
    axes: {
      hgap: { name:'H-Gap',    pvSuffix:'Hgap', unit:'um', value:50,  min:1, max:500, step:1, resolution:0.1, speed:50,
              sync:{ stateKey:'ssaH', uiId:'ssaH' } },
      vgap: { name:'V-Gap',    pvSuffix:'Vgap', unit:'um', value:50,  min:1, max:500, step:1, resolution:0.1, speed:50,
              sync:{ stateKey:'ssaV', uiId:'ssaV' } },
      hcen: { name:'H-Center', pvSuffix:'Hcen', unit:'um', value:0,   min:-500, max:500, step:0.5, resolution:0.1, speed:100,
              sync:{ stateKey:'ssaCX' } },
      vcen: { name:'V-Center', pvSuffix:'Vcen', unit:'um', value:0,   min:-500, max:500, step:0.5, resolution:0.1, speed:100,
              sync:{ stateKey:'ssaCY' } }
    }
  },

  // -- KB Upstream Slit (500mm upstream of KB-V, JJ X-Ray style 4-blade) --
  {
    id: 'kbslit', label: 'KB Slit', pvPrefix: 'BL10:KBS',
    icon: '', category: 'aperture',
    axes: {
      hgap: { name:'H-Gap',    pvSuffix:'Hgap', unit:'um', value:5000, min:1, max:10000, step:1, resolution:0.1, speed:50,
              sync:{ stateKey:'kbslitH', uiId:'kbslitH' } },
      vgap: { name:'V-Gap',    pvSuffix:'Vgap', unit:'um', value:5000, min:1, max:10000, step:1, resolution:0.1, speed:50,
              sync:{ stateKey:'kbslitV', uiId:'kbslitV' } },
      hcen: { name:'H-Center', pvSuffix:'Hcen', unit:'um', value:0,   min:-5000, max:5000, step:0.5, resolution:0.1, speed:100,
              sync:{ stateKey:'kbslitCX' } },
      vcen: { name:'V-Center', pvSuffix:'Vcen', unit:'um', value:0,   min:-5000, max:5000, step:0.5, resolution:0.1, speed:100,
              sync:{ stateKey:'kbslitCY' } }
    }
  },

  // -- KB Mirrors (JTEC JM2000-200, Si substrate, Pt single coating, 3.0 mrad incidence) --
  {
    id: 'kbv', label: 'KB-V Mirror (VFM)', pvPrefix: 'BL10:KBV',
    icon: '', category: 'focusing',
    vendor: 'JTEC', model: 'JM2000-200 VFM',
    axes: {
      x:      { name:'x',         pvSuffix:'X',     unit:'mm',   value:0, min:-2,  max:2,  step:0.001, resolution:0.0005, speed:0.5,
                description:'VF-X lateral position' },
      y:      { name:'y',         pvSuffix:'Y',     unit:'mm',   value:0, min:-15, max:15, step:0.002, resolution:0.001, speed:0.5,
                description:'VF-Y height position' },
      z:      { name:'z',         pvSuffix:'Z',     unit:'mm',   value:0, min:-100, max:100, step:0.01, resolution:0.001, speed:0.5,
                description:'VF-Z along-beam position (RC alignment axis)' },
      pitch:  { name:'pitch',   pvSuffix:'Pitch',  unit:'mrad', value:3.0, min:-2, max:5, step:0.0005, resolution:0.0001, backlash:0.001, speed:0.2,
                sync:{ stateKey:'kbvpitch', fn:'updateKBV' },
                description:'VF-th pitch angle (3.0 mrad nominal, 0.5\u03BCrad slope error)' }
    }
  },
  {
    id: 'kbh', label: 'KB-H Mirror (HFM)', pvPrefix: 'BL10:KBH',
    icon: '', category: 'focusing',
    vendor: 'JTEC', model: 'JM2000-200 HFM',
    axes: {
      x:      { name:'x',         pvSuffix:'X',     unit:'mm',   value:0, min:-15, max:15, step:0.002, resolution:0.001, speed:0.5,
                description:'HF-X lateral position' },
      y:      { name:'y',         pvSuffix:'Y',     unit:'mm',   value:0, min:-2,  max:2,  step:0.001, resolution:0.0005, speed:0.5,
                description:'HF-Y height position' },
      z:      { name:'z',         pvSuffix:'Z',     unit:'mm',   value:0, min:-100, max:100, step:0.01, resolution:0.001, speed:0.5,
                description:'HF-Z along-beam position (RC alignment axis)' },
      pitch:  { name:'pitch',   pvSuffix:'Pitch',  unit:'mrad', value:3.0, min:-2, max:5, step:0.0005, resolution:0.0001, backlash:0.001, speed:0.2,
                sync:{ stateKey:'kbhpitch', fn:'updateKBH' },
                description:'HF-th pitch angle (3.0 mrad nominal, 0.5\u03BCrad slope error)' }
    }
  },

  // -- Zone Plate --
  {
    id: 'zp', label: 'Zone Plate', pvPrefix: 'BL10:ZP',
    icon: '', category: 'focusing',
    axes: {
      x: { name:'X', pvSuffix:'X', unit:'um', value:0, min:-2000, max:2000, step:0.05, resolution:0.01 },
      y: { name:'Y', pvSuffix:'Y', unit:'um', value:0, min:-2000, max:2000, step:0.05, resolution:0.01 },
      z: { name:'Z (focus)', pvSuffix:'Z', unit:'um', value:0, min:-5000, max:5000, step:0.1, resolution:0.05 }
    }
  },

  // -- Sample Stage (KOHZU coarse + PI PIMars nano + PI scanner + PI rotation) --
  {
    id: 'sample', label: 'Sample Stage', pvPrefix: 'BL10:SAM',
    icon: '', category: 'sample',
    vendor: 'KOHZU/PI/SmarAct',
    axes: {
      cx:  { name:'Coarse X', pvSuffix:'CX',    unit:'mm',  value:0, min:-25,  max:25,  step:0.001, resolution:0.0005, speed:2, backlash:0.003,
             description:'KOHZU MVXA07A linear stage' },
      cy:  { name:'Coarse Y', pvSuffix:'CY',    unit:'mm',  value:0, min:-25,  max:25,  step:0.001, resolution:0.0005, speed:2, backlash:0.003,
             description:'KOHZU MVXA07A linear stage' },
      cz:  { name:'Coarse Z', pvSuffix:'CZ',    unit:'mm',  value:0, min:-12,  max:12,  step:0.001, resolution:0.0005, speed:1, backlash:0.002,
             description:'KOHZU MVZA10A vertical stage' },
      th:  { name:'th rotation', pvSuffix:'Theta', unit:'deg', value:0, min:-180, max:180, step:0.001, resolution:0.018, speed:200,
             description:'PI L-611.90AD rotation (360deg, 200deg/s, 20000 cts/rev)' },
      phi: { name:'phi tilt',     pvSuffix:'Phi',   unit:'deg', value:0, min:-5,   max:5,   step:0.001, resolution:0.0002, speed:2,
             description:'SmarAct tilt stage (~1nm closed-loop)' },
      fx:  { name:'Fine X',   pvSuffix:'FX',    unit:'um',  value:0, min:-150, max:150, step:0.0001, resolution:0.0001, speed:50,
             description:'PI P-563.3CD PIMars nano XYZ (300um range, sub-nm)' },
      fy:  { name:'Fine Y',   pvSuffix:'FY',    unit:'um',  value:0, min:-150, max:150, step:0.0001, resolution:0.0001, speed:50,
             description:'PI P-563.3CD PIMars nano XYZ (300um range, sub-nm)' },
      fz:  { name:'Fine Z',   pvSuffix:'FZ',    unit:'um',  value:0, min:-150, max:150, step:0.0001, resolution:0.0001, speed:50,
             description:'PI P-563.3CD PIMars nano XYZ (300um range, sub-nm)' },
      sx:  { name:'Scan X',   pvSuffix:'SX',    unit:'um',  value:0, min:-50,  max:50,  step:0.0001, resolution:0.0001, speed:100,
             description:'PI P-733.2CD scanner (100um range, sub-nm)' },
      sy:  { name:'Scan Y',   pvSuffix:'SY',    unit:'um',  value:0, min:-50,  max:50,  step:0.0001, resolution:0.0001, speed:100,
             description:'PI P-733.2CD scanner (100um range, sub-nm)' }
    }
  },

  // -- Detector --
  {
    id: 'det', label: 'Detector', pvPrefix: 'BL10:DET',
    icon: '', category: 'diag',
    axes: {
      x: { name:'X', pvSuffix:'X', unit:'mm', value:0, min:-50, max:50,   step:0.01, resolution:0.005, speed:1,
           description:'Detector lateral position' },
      y: { name:'Y', pvSuffix:'Y', unit:'mm', value:0, min:-50, max:50,   step:0.01, resolution:0.005, speed:1,
           description:'Detector vertical position' },
      z: { name:'Z', pvSuffix:'Z', unit:'mm', value:0, min:0,   max:5000, step:1,    resolution:0.1, speed:5,
           description:'Detector distance (sample-to-detector)' }
    }
  }
];

// ========================================================================
// FACTORY: Build MOTORS object from DEVICE_CONFIGS
// ========================================================================
var MOTORS = {};
var DEVICE_REGISTRY = {};  // id -> config reference
var PV_TO_MOTOR = {};      // pvName -> {deviceId, axisKey, motor}

function buildMotorsFromConfig(){
  // Clear existing
  Object.keys(MOTORS).forEach(function(k) { delete MOTORS[k]; });
  Object.keys(PV_TO_MOTOR).forEach(function(k) { delete PV_TO_MOTOR[k]; });

  DEVICE_CONFIGS.forEach(function(dev) {
    DEVICE_REGISTRY[dev.id] = dev;
    MOTORS[dev.id] = {};

    Object.keys(dev.axes).forEach(function(axKey) {
      var ax = dev.axes[axKey];
      var motorId = dev.id + '_' + axKey;
      var pvName  = dev.pvPrefix + ':' + ax.pvSuffix;
      var displayName = ax.name; // Keep it short; device label shown in group header

      var motor = new Motor({
        id: motorId,
        name: displayName,
        unit: ax.unit || 'mm',
        value: (ax.value != null) ? ax.value : 0,
        min: (ax.min != null) ? ax.min : -1e6,
        max: (ax.max != null) ? ax.max : 1e6,
        step: ax.step || 0.001,
        resolution: ax.resolution || 0.0001,
        backlash: ax.backlash || 0,
        speed: ax.speed || 1,
        pv: pvName,
        deviceId: dev.id,
        axisKey: axKey,
        sync: ax.sync || null,
        description: ax.description || ''
      });

      MOTORS[dev.id][axKey] = motor;

      // Register PV -> Motor mapping (for EPICS reverse lookup)
      PV_TO_MOTOR[pvName] = { deviceId: dev.id, axisKey: axKey, motor: motor };
    });

    // Apply corrections
    if(dev.corrections){
      Object.keys(dev.corrections).forEach(function(axKey) {
        var motor = MOTORS[dev.id][axKey];
        if(!motor) return;
        var corr = dev.corrections[axKey];
        if(corr.type === 'table'){
          motor.correctionTable = { energies: corr.energies, offsets: corr.offsets };
        } else if(corr.type === 'poly'){
          motor.correctionPoly = corr.coeffs;
        }
      });
    }
  });

  var totalMotors = Object.values(MOTORS).reduce(function(s, g) { return s + Object.keys(g).length; }, 0);
  var totalPVs = Object.keys(PV_TO_MOTOR).length;
  // Debounce log: multiple rapid calls during init only show final count
  if (buildMotorsFromConfig._logTimer) clearTimeout(buildMotorsFromConfig._logTimer);
  buildMotorsFromConfig._logTimer = setTimeout(function() {
    var m = Object.values(MOTORS).reduce(function(s, g) { return s + Object.keys(g).length; }, 0);
    var p = Object.keys(PV_TO_MOTOR).length;
    log('info', 'DeviceConfig: ' + DEVICE_CONFIGS.length + ' devices, ' + m + ' motors, ' + p + ' PVs');
  }, 100);
}

// ========================================================================
// DEVICE MANAGEMENT API -- Add/Remove/Rename at runtime
// ========================================================================

/**
 * Add a new device at runtime.
 * @param {Object} config - Device config (same format as DEVICE_CONFIGS entries)
 * @returns {boolean} success
 */
function addDevice(config){
  if(!config.id || !config.axes || !config.pvPrefix){
    log('err', 'addDevice: id, pvPrefix, axes required');
    return false;
  }
  if(DEVICE_REGISTRY[config.id]){
    log('warn', 'addDevice: device ' + config.id + ' already exists, use removeDevice first');
    return false;
  }
  // Add to configs
  DEVICE_CONFIGS.push(config);
  DEVICE_REGISTRY[config.id] = config;
  MOTORS[config.id] = {};

  Object.keys(config.axes).forEach(function(axKey) {
    var ax = config.axes[axKey];
    var motorId = config.id + '_' + axKey;
    var pvName = config.pvPrefix + ':' + ax.pvSuffix;

    var motor = new Motor({
      id: motorId, name: ax.name, unit: ax.unit || 'mm',
      value: (ax.value != null) ? ax.value : 0, min: (ax.min != null) ? ax.min : -1e6, max: (ax.max != null) ? ax.max : 1e6,
      step: ax.step || 0.001, resolution: ax.resolution || 0.0001,
      backlash: ax.backlash || 0, speed: ax.speed || 1,
      pv: pvName, deviceId: config.id, axisKey: axKey,
      sync: ax.sync || null, description: ax.description || ''
    });
    MOTORS[config.id][axKey] = motor;
    PV_TO_MOTOR[pvName] = { deviceId: config.id, axisKey: axKey, motor: motor };
  });

  log('info', 'Device added: ' + config.id + ' (' + Object.keys(config.axes).length + ' axes, prefix=' + config.pvPrefix + ')');
  // Rebuild EPICS PV registry if available
  if(typeof buildPVRegistry === 'function') buildPVRegistry();
  return true;
}

/**
 * Remove a device at runtime.
 */
function removeDevice(deviceId){
  if(!MOTORS[deviceId]){ log('warn', 'removeDevice: ' + deviceId + ' not found'); return false; }
  // Remove PV mappings
  Object.values(MOTORS[deviceId]).forEach(function(m) { delete PV_TO_MOTOR[m.pv]; });
  delete MOTORS[deviceId];
  delete DEVICE_REGISTRY[deviceId];
  var idx = -1;
  for(var i = 0; i < DEVICE_CONFIGS.length; i++){
    if(DEVICE_CONFIGS[i].id === deviceId){ idx = i; break; }
  }
  if(idx >= 0) DEVICE_CONFIGS.splice(idx, 1);
  log('info', 'Device removed: ' + deviceId);
  if(typeof buildPVRegistry === 'function') buildPVRegistry();
  return true;
}

/**
 * Add a motor axis to an existing device.
 * Example: addMotorAxis('m1', 'stripe', { name:'Stripe Sel', pvSuffix:'Stripe', unit:'#', value:1, min:1, max:3, step:1 })
 */
function addMotorAxis(deviceId, axisKey, axisCfg){
  var dev = DEVICE_REGISTRY[deviceId];
  if(!dev){ log('err', 'addMotorAxis: device ' + deviceId + ' not found'); return false; }
  if(MOTORS[deviceId][axisKey]){ log('warn', 'Axis ' + axisKey + ' already exists'); return false; }

  dev.axes[axisKey] = axisCfg;
  var motorId = deviceId + '_' + axisKey;
  var pvName = dev.pvPrefix + ':' + axisCfg.pvSuffix;
  var motor = new Motor({
    id: motorId, name: axisCfg.name, unit: axisCfg.unit || 'mm',
    value: (axisCfg.value != null) ? axisCfg.value : 0, min: (axisCfg.min != null) ? axisCfg.min : -1e6, max: (axisCfg.max != null) ? axisCfg.max : 1e6,
    step: axisCfg.step || 0.001, resolution: axisCfg.resolution || 0.0001,
    backlash: axisCfg.backlash || 0, speed: axisCfg.speed || 1,
    pv: pvName, deviceId: deviceId, axisKey: axisKey, sync: axisCfg.sync || null
  });
  MOTORS[deviceId][axisKey] = motor;
  PV_TO_MOTOR[pvName] = { deviceId: deviceId, axisKey: axisKey, motor: motor };
  log('info', 'Axis added: ' + deviceId + '.' + axisKey + ' -> ' + pvName);
  if(typeof buildPVRegistry === 'function') buildPVRegistry();
  return true;
}

/**
 * Rename a PV. Updates Motor, PV_TO_MOTOR, and PV_REGISTRY.
 * Example: renamePV('BL10:M1:Pitch', 'BL10:HFM:Pitch')
 */
function renamePV(oldPV, newPV){
  var entry = PV_TO_MOTOR[oldPV];
  if(!entry){ log('err', 'renamePV: ' + oldPV + ' not found'); return false; }
  entry.motor.pv = newPV;
  PV_TO_MOTOR[newPV] = entry;
  delete PV_TO_MOTOR[oldPV];
  // Update device config
  var dev = DEVICE_REGISTRY[entry.deviceId];
  if(dev && dev.axes[entry.axisKey]) dev.axes[entry.axisKey].pvSuffix = newPV.split(':').pop();
  log('info', 'PV renamed: ' + oldPV + ' -> ' + newPV);
  if(typeof buildPVRegistry === 'function') buildPVRegistry();
  return true;
}

/**
 * Change PV prefix for entire device.
 * Example: changePVPrefix('m1', 'BL10:HFM')  -> all M1 PVs become BL10:HFM:*
 */
function changePVPrefix(deviceId, newPrefix){
  var dev = DEVICE_REGISTRY[deviceId];
  if(!dev){ log('err', 'changePVPrefix: device ' + deviceId + ' not found'); return false; }
  var oldPrefix = dev.pvPrefix;
  dev.pvPrefix = newPrefix;
  // Update all motors in this device
  Object.keys(MOTORS[deviceId]).forEach(function(axKey) {
    var m = MOTORS[deviceId][axKey];
    var oldPV = m.pv;
    var suffix = dev.axes[axKey].pvSuffix;
    var newPV = newPrefix + ':' + suffix;
    m.pv = newPV;
    delete PV_TO_MOTOR[oldPV];
    PV_TO_MOTOR[newPV] = { deviceId: deviceId, axisKey: axKey, motor: m };
  });
  log('info', 'PV prefix changed: ' + deviceId + ' ' + oldPrefix + ' -> ' + newPrefix);
  if(typeof buildPVRegistry === 'function') buildPVRegistry();
  return true;
}

/**
 * Get a flat list of all motors across all devices.
 */
function getAllMotors(){
  var result = [];
  Object.keys(MOTORS).forEach(function(devId) {
    Object.values(MOTORS[devId]).forEach(function(m) { if(m && m.id) result.push(m); });
  });
  return result;
}

/**
 * Find motor by PV name.
 */
function findMotorByPV(pvName){
  return PV_TO_MOTOR[pvName] || null;
}

/**
 * Export entire device configuration as JSON (for save/load).
 */
function exportDeviceConfig(){
  return JSON.stringify(DEVICE_CONFIGS, null, 2);
}

/**
 * Import device configuration from JSON string.
 */
function importDeviceConfig(jsonStr){
  try {
    var configs = JSON.parse(jsonStr);
    if(!Array.isArray(configs)) throw new Error('Expected array');
    DEVICE_CONFIGS.length = 0;
    configs.forEach(function(c) { DEVICE_CONFIGS.push(c); });
    buildMotorsFromConfig();
    log('info', 'Device config imported: ' + configs.length + ' devices');
    return true;
  } catch(e){
    log('err', 'Import failed: ' + e.message);
    return false;
  }
}

/**
 * Print device summary to console.
 */
function printDeviceSummary(){
  var total = 0;
  DEVICE_CONFIGS.forEach(function(dev) {
    var n = Object.keys(dev.axes).length;
    total += n;
    console.log((dev.icon||'.') + ' ' + dev.id + ' ' + dev.label + ' ' + dev.pvPrefix + ' ' + n + ' axes');
    Object.keys(dev.axes).forEach(function(k) {
      var ax = dev.axes[k];
      var pv = dev.pvPrefix + ':' + ax.pvSuffix;
      console.log('    ' + k + ' -> ' + pv + ' [' + ax.unit + '] ' + ax.min + '..' + ax.max);
    });
  });
  console.log('Total: ' + DEVICE_CONFIGS.length + ' devices, ' + total + ' motor axes, ' + Object.keys(PV_TO_MOTOR).length + ' PVs');
}

// ========================================================================
// initMotors -- now just calls buildMotorsFromConfig
// ========================================================================
function initMotors(){
  buildMotorsFromConfig();
  initMaskMotors();
}

function initMaskMotors(){ /* mask state initialized in mask_calc.js */ }

// ========================================================================
// syncMotorToState -- Declarative sync driven by motor.sync config
// ========================================================================
// Special sync handlers for non-trivial mappings
var SYNC_HANDLERS = {
  '_dcmThetaSync': function(value){
    // Convert theta to energy: E = hc/(2d*sin(theta))
    var thRad = value * Math.PI / 180;
    if(Math.abs(thRad) < 0.001) return; // Skip near-zero theta
    var d = D_SI[state.crystal || '111'];
    var E = HC / (2 * d * Math.sin(thRad));
    if(E > 3 && E < 50){
      // Sync undulator gap+harmonic AND DCM energy together.
      // Without gap sync, undulator peak != DCM energy -> ~1000x flux drop
      // via envelope detuning (same pattern as commit 0617530).
      if(typeof setTargetEnergy === 'function'){
        setTargetEnergy(E);
      } else {
        state.energy = E;
        var el = document.getElementById('energySlider'); if(el) el.value = E;
        updateEnergy(E);
      }
    }
  }
};

// Debounced physics update: leading+trailing throttle (150ms)
// First call executes immediately, subsequent calls within 150ms are merged
// In Real/Hybrid mode: only update SVG layout, skip MC ray tracing
var _syncPhysicsTimer = null;
var _syncPhysicsPending = false;
function _debouncedPhysicsUpdate() {
  if (_syncPhysicsTimer) { _syncPhysicsPending = true; return; }
  _runPhysicsOrLayout();
  _syncPhysicsTimer = setTimeout(function() {
    _syncPhysicsTimer = null;
    if (_syncPhysicsPending) {
      _syncPhysicsPending = false;
      _runPhysicsOrLayout();
    }
  }, 150);
}
// Real/Hybrid mode: debounced MC ray trace after motor movement completes
var _realModeMCTimer = null;
function _runPhysicsOrLayout() {
  var epMode = (typeof EPICS_STATE !== 'undefined') ? EPICS_STATE.mode : '';
  if (epMode === 'real' || epMode === 'hybrid') {
    // 1. Immediate SVG layout update (position feedback)
    if (typeof renderLayout === 'function') try { renderLayout(); } catch(e) {}
    // 2. MC ray trace with 500ms debounce (runs once after movement stops)
    if (_realModeMCTimer) clearTimeout(_realModeMCTimer);
    _realModeMCTimer = setTimeout(function() {
      _realModeMCTimer = null;
      if (typeof updateOptics === 'function') {
        try { updateOptics(); } catch(e) {}
      }
    }, 500);
  } else {
    // Virtual/Sim/Disconnected: full physics update including MC
    if (typeof updateOptics === 'function') updateOptics();
  }
}

function syncMotorToState(groupId, motorId, value){
  // Invalidate MC ray trace cache -- motor position affects beam
  if(typeof _mcSampleCache !== 'undefined') _mcSampleCache = null;

  // 1. Mask sync
  if(groupId === 'fmask' || groupId === 'mmask'){
    var ms = maskState[groupId];
    if(ms){
      if(motorId.indexOf('_hgap') >= 0 || motorId.indexOf('_hg') >= 0) ms.aperH = value;
      if(motorId.indexOf('_vgap') >= 0 || motorId.indexOf('_vg') >= 0) ms.aperV = value;
    }
  }

  // 2. Find motor and apply sync config
  var grp = MOTORS[groupId];
  if(!grp) return;
  var motor = null;
  var keys = Object.keys(grp);
  for(var _ki = 0; _ki < keys.length; _ki++){
    var key = keys[_ki];
    if(grp[key].id === motorId){ motor = grp[key]; break; }
  }
  if(!motor || !motor.sync) {
    // No sync config -- just refresh beam state (debounced)
    _debouncedPhysicsUpdate();
    return;
  }

  var sync = motor.sync;

  // 3. Special handler
  if(sync.fn && SYNC_HANDLERS[sync.fn]){
    SYNC_HANDLERS[sync.fn](value);
  }

  // 4. stateKey binding: state[key] = value
  if(sync.stateKey && sync.stateKey[0] !== '_'){
    state[sync.stateKey] = value;
    // Track if user manually changes SSA during KB alignment
    // Skip programmatic changes (flagged by _kbAlignSsaProgrammatic)
    if((sync.stateKey === 'ssaH' || sync.stateKey === 'ssaV') && state.aligning && !window._kbAlignSsaProgrammatic){
      window._kbAlignSsaUserChanged = true;
    }
  }

  // 5. Slider binding: document.getElementById(slider).value = value
  if(sync.slider){
    var el = document.getElementById(sync.slider);
    if(el) el.value = value;
  }

  // 6. Input/display binding: document.getElementById(uiId).value = value
  if(sync.uiId){
    var el2 = document.getElementById(sync.uiId);
    if(el2) el2.value = value;
  }

  // 7. Function call: window[fn](value)
  if(sync.fn && !SYNC_HANDLERS[sync.fn] && typeof window[sync.fn] === 'function'){
    window[sync.fn](value);
  }

  // 8. Refresh beam state (debounced)
  // updateOptics() internally calls renderLayout() + updateLiveBeamInfo()
  _debouncedPhysicsUpdate();
}

// ========================================================================
// Legacy motor functions (for modal component view compatibility)
// ========================================================================
function motorSet(compId, mtrId, val){
  var m = findMotor(mtrId); if(!m) return;
  m.value = val; m.target = val;
}
function findMotor(mtrId){
  var gids = Object.keys(MOTORS);
  for(var _gi = 0; _gi < gids.length; _gi++){
    var gid = gids[_gi];
    var grp = MOTORS[gid];
    var keys = Object.keys(grp);
    for(var _ki = 0; _ki < keys.length; _ki++){
      var key = keys[_ki];
      if(grp[key].id === mtrId) return grp[key];
    }
  }
  return null;
}

// ========================================================================
// Correction System
// ========================================================================
function buildCorrectionLUT(motor, scanData){
  var energies = scanData.map(function(d) { return d.energy; });
  var offsets = scanData.map(function(d) { return d.offset; });
  motor.correctionTable = { energies: energies, offsets: offsets };
  log('info', 'LUT built for ' + motor.name + ': ' + energies.length + ' pts');
}

function buildCorrectionPoly(motor, scanData, order){
  if(order === undefined) order = 3;
  var n = scanData.length;
  if(n < order+1){ log('warn', 'Not enough data for poly fit'); return; }
  var X = [], Y = [];
  scanData.forEach(function(d) { X.push(d.energy); Y.push(d.offset); });
  var coeffs = polyFit(X, Y, order);
  motor.correctionPoly = coeffs;
  log('info', 'Poly correction for ' + motor.name + ': order=' + order);
}

function polyFit(xs, ys, order){
  var n = xs.length;
  var m = order + 1;
  var A = Array(m).fill(0).map(function() { return Array(m+1).fill(0); });
  for(var i = 0; i < m; i++){
    for(var j = 0; j < m; j++){
      for(var k = 0; k < n; k++) A[i][j] += Math.pow(xs[k], i+j);
    }
    for(var k = 0; k < n; k++) A[i][m] += ys[k] * Math.pow(xs[k], i);
  }
  for(var i = 0; i < m; i++){
    var mx = i;
    for(var j = i+1; j < m; j++) if(Math.abs(A[j][i]) > Math.abs(A[mx][i])) mx = j;
    var tmp = A[i]; A[i] = A[mx]; A[mx] = tmp;
    if(Math.abs(A[i][i]) < 1e-15) continue;
    for(var j = i+1; j < m; j++){
      var f = A[j][i] / A[i][i];
      for(var k = i; k <= m; k++) A[j][k] -= f * A[i][k];
    }
  }
  var c = Array(m).fill(0);
  for(var i = m-1; i >= 0; i--){
    c[i] = A[i][m];
    for(var j = i+1; j < m; j++) c[i] -= A[i][j] * c[j];
    c[i] /= (A[i][i] || 1);
  }
  return c;
}

function mirrorEnergyCorrection(mirrorMotors, energyRange){
  var pitchMotor = mirrorMotors.pitch;
  if(!pitchMotor || !pitchMotor.correctionTable) return [];
  var result = [];
  for(var e = energyRange[0]; e <= energyRange[1]; e += 0.5){
    result.push({ energy: e, correction: pitchMotor.correctedValue(e) - pitchMotor.value });
  }
  return result;
}

// ========================================================================

// ESM bridge: expose module-scoped vars to globalThis
if(typeof DEVICE_CONFIGS!=="undefined")globalThis.DEVICE_CONFIGS=DEVICE_CONFIGS;
if(typeof DEVICE_REGISTRY!=="undefined")globalThis.DEVICE_REGISTRY=DEVICE_REGISTRY;
if(typeof MOTORS!=="undefined")globalThis.MOTORS=MOTORS;
if(typeof Motor!=="undefined")globalThis.Motor=Motor;
if(typeof PV_TO_MOTOR!=="undefined")globalThis.PV_TO_MOTOR=PV_TO_MOTOR;
if(typeof SYNC_HANDLERS!=="undefined")globalThis.SYNC_HANDLERS=SYNC_HANDLERS;
if(typeof addDevice!=="undefined")globalThis.addDevice=addDevice;
if(typeof addMotorAxis!=="undefined")globalThis.addMotorAxis=addMotorAxis;
if(typeof buildCorrectionLUT!=="undefined")globalThis.buildCorrectionLUT=buildCorrectionLUT;
if(typeof buildCorrectionPoly!=="undefined")globalThis.buildCorrectionPoly=buildCorrectionPoly;
if(typeof buildMotorsFromConfig!=="undefined")globalThis.buildMotorsFromConfig=buildMotorsFromConfig;
if(typeof changePVPrefix!=="undefined")globalThis.changePVPrefix=changePVPrefix;
if(typeof exportDeviceConfig!=="undefined")globalThis.exportDeviceConfig=exportDeviceConfig;
if(typeof findMotor!=="undefined")globalThis.findMotor=findMotor;
if(typeof findMotorByPV!=="undefined")globalThis.findMotorByPV=findMotorByPV;
if(typeof getAllMotors!=="undefined")globalThis.getAllMotors=getAllMotors;
if(typeof importDeviceConfig!=="undefined")globalThis.importDeviceConfig=importDeviceConfig;
if(typeof initMaskMotors!=="undefined")globalThis.initMaskMotors=initMaskMotors;
if(typeof initMotors!=="undefined")globalThis.initMotors=initMotors;
if(typeof interpLin!=="undefined")globalThis.interpLin=interpLin;
if(typeof mirrorEnergyCorrection!=="undefined")globalThis.mirrorEnergyCorrection=mirrorEnergyCorrection;
if(typeof motorSet!=="undefined")globalThis.motorSet=motorSet;
if(typeof polyFit!=="undefined")globalThis.polyFit=polyFit;
if(typeof printDeviceSummary!=="undefined")globalThis.printDeviceSummary=printDeviceSummary;
if(typeof removeDevice!=="undefined")globalThis.removeDevice=removeDevice;
if(typeof renamePV!=="undefined")globalThis.renamePV=renamePV;
if(typeof syncMotorToState!=="undefined")globalThis.syncMotorToState=syncMotorToState;
if(typeof SIM_INTEGRATION_MS!=="undefined")globalThis.SIM_INTEGRATION_MS=SIM_INTEGRATION_MS;
if(typeof SIM_SPEED_FACTOR!=="undefined")globalThis.SIM_SPEED_FACTOR=SIM_SPEED_FACTOR;
if(typeof _debouncedPhysicsUpdate!=="undefined")globalThis._debouncedPhysicsUpdate=_debouncedPhysicsUpdate;
if(typeof _kbAlignSsaUserChanged!=="undefined")globalThis._kbAlignSsaUserChanged=_kbAlignSsaUserChanged;
if(typeof _realModeMCTimer!=="undefined")globalThis._realModeMCTimer=_realModeMCTimer;
if(typeof _runPhysicsOrLayout!=="undefined")globalThis._runPhysicsOrLayout=_runPhysicsOrLayout;
if(typeof _syncPhysicsPending!=="undefined")globalThis._syncPhysicsPending=_syncPhysicsPending;
if(typeof _syncPhysicsTimer!=="undefined")globalThis._syncPhysicsTimer=_syncPhysicsTimer;
if(typeof axisKey!=="undefined")globalThis.axisKey=axisKey;
