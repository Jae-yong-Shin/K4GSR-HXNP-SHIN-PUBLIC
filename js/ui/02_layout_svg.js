// ===== layout.js =====
// ===== layout.js — Fixed-exit DCM + drag-to-reposition =====
// @module ui/02_layout_svg
// @exports COL_DCM, COL_FOCUS, COL_FOCUSED, COL_MIRROR, COL_MONO, COL_WB, D2R, DEFAULT_VISUAL_SX, H_DCM_PX, ICON_DRAG_LOCKED, _drag, _svgAtten, _svgBpm, _svgDcm, _svgDet, ...
// Color coding:
//   Mirror (M1/M2):   #60a0e0 (sky blue)
//   DCM crystals:     #b878e0 (purple)
//   White beam:       #ffa040 (amber)
//   Mono beam (C2→):  #00d890 (emerald green)
//   Focus optics:     #e0a050 (warm gold)
//   Focused beam:     #80f0c0 (mint)

var D2R=Math.PI/180, R2D=180/Math.PI;
// DCM crystal vertical offset in pixels (8); also drives the c1->c2 gap L = H_DCM_PX/sin(2*thetaB).
var H_DCM_PX = 8;

// Sky-blue hex '#60a0e0' used as the default stroke color for M1/M2 mirror glyphs.
var COL_MIRROR='#60a0e0', COL_MIRROR_HL='#a0e0ff';
// Purple hex '#b878e0' for DCM crystal glyphs and the dcm_between beam segment color.
var COL_DCM='#b878e0', COL_DCM_FILL='#2a1840';
// Amber hex '#ffa040' for the white (pre-mono) beam state and source line color.
var COL_WB='#ffa040';
// Emerald hex '#00d890' for the monochromatic (post-DCM) beam state segment color.
var COL_MONO='#00d890', COL_MONO_DIM='rgba(0,216,144,.5)';
// Warm-gold hex '#e0a050' for focus optics (KB/ZP/CRL) glyphs and the focus convergence dot.
var COL_FOCUS='#e0a050', COL_FOCUS_FILL='#2a2010';
// Mint hex '#80f0c0' for the focused-beam state (post focus optic) lines, glow, and highlight stroke.
var COL_FOCUSED='#80f0c0';

// ========== Visual position overrides ==========
// state.visualSx[id] = pixel x  (purely visual, physics unchanged)
// Persisted in localStorage key 'bl_visualSx'

// Default visual positions (user-tuned pixel layout for front-end optics)
var DEFAULT_VISUAL_SX={wbslit:230,atten:286,xbpm_wb:363,m1:383,xbpm_m1:426,dcm:462,xbpm1:500,m2:536};

// Seed state.visualSx from defaults, then overlay any user overrides parsed from localStorage 'bl_visualSx'.
function loadVisualSx(){
  // Start from defaults, then overlay any user-saved overrides
  state.visualSx=Object.assign({},DEFAULT_VISUAL_SX);
  try{
    var s=localStorage.getItem('bl_visualSx');
    if(s){Object.assign(state.visualSx,JSON.parse(s));}
  }catch(e){}
}
// Auto-load on script parse (before first renderLayout call)
loadVisualSx();
// Persist state.visualSx as JSON into localStorage key 'bl_visualSx', ignoring storage errors.
function saveVisualSx(){
  try{localStorage.setItem('bl_visualSx',JSON.stringify(state.visualSx));}catch(e){}
}
// Restore state.visualSx to defaults, delete the localStorage override, re-render the layout, and log it.
function resetVisualSx(){
  state.visualSx=Object.assign({},DEFAULT_VISUAL_SX);
  try{localStorage.removeItem('bl_visualSx');}catch(e){}
  renderLayout();
  log('info','Layout positions reset to default');
}

// ========== Drag system ==========
var _drag=null; // {id, startMouseX, startSx, moved}

// Convert a mouse event's client coords into SVG user coords via the #blSvg screen CTM (inverse e/a, f/d).
function svgPt(evt){
  var svg=document.getElementById('blSvg');
  var ctm=svg.getScreenCTM();
  if(!ctm)return{x:evt.clientX,y:evt.clientY};
  return{x:(evt.clientX-ctm.e)/ctm.a, y:(evt.clientY-ctm.f)/ctm.d};
}

// Icon drag lock — prevents accidental visual-only repositioning that
// desynchronises layout from physics.  Set to false to allow drag.
var ICON_DRAG_LOCKED = false;

// ========== SVG Context Menu (right-click) ==========
(function(){
  var _ctxMenu = null;
  function _hideCtx(){ if(_ctxMenu&&_ctxMenu.parentNode) _ctxMenu.parentNode.removeChild(_ctxMenu); _ctxMenu=null; }

  function _showCtx(evt){
    evt.preventDefault();
    _hideCtx();
    var m = document.createElement('div');
    m.style.cssText = 'position:fixed;z-index:99999;background:var(--s1,#22252b);border:1px solid var(--s2,#2a2d35);border-radius:6px;padding:4px 0;min-width:180px;box-shadow:0 4px 16px rgba(0,0,0,.4);font:12px/1.6 system-ui,sans-serif;color:var(--t1,#e8eaed)';
    m.style.left = evt.clientX + 'px';
    m.style.top = evt.clientY + 'px';

    // 1) Drag lock toggle
    var lockLabel = ICON_DRAG_LOCKED ? '[x] Unlock icon drag' : '[ ] Lock icon drag';
    var d1 = document.createElement('div');
    d1.textContent = lockLabel;
    d1.style.cssText = 'padding:5px 14px;cursor:pointer;white-space:nowrap';
    d1.onmouseenter = function(){ d1.style.background='var(--ac,#4db8ff)'; d1.style.color='#000'; };
    d1.onmouseleave = function(){ d1.style.background=''; d1.style.color=''; };
    d1.onclick = function(){
      ICON_DRAG_LOCKED = !ICON_DRAG_LOCKED;
      log('info', 'Icon drag ' + (ICON_DRAG_LOCKED ? 'LOCKED' : 'UNLOCKED'));
      _hideCtx();
    };
    m.appendChild(d1);

    // 2) Reset positions
    var d2 = document.createElement('div');
    d2.textContent = 'Reset icon positions';
    d2.style.cssText = 'padding:5px 14px;cursor:pointer;white-space:nowrap';
    d2.onmouseenter = function(){ d2.style.background='var(--ac,#4db8ff)'; d2.style.color='#000'; };
    d2.onmouseleave = function(){ d2.style.background=''; d2.style.color=''; };
    d2.onclick = function(){
      resetVisualSx();
      log('info', 'Icon positions reset to default');
      _hideCtx();
    };
    m.appendChild(d2);

    document.body.appendChild(m);
    _ctxMenu = m;

    // Clamp to viewport
    var r = m.getBoundingClientRect();
    if(r.right > window.innerWidth) m.style.left = (window.innerWidth - r.width - 4) + 'px';
    if(r.bottom > window.innerHeight) m.style.top = (window.innerHeight - r.height - 4) + 'px';
  }

  document.addEventListener('click', function(){ _hideCtx(); });

  // Attach to SVG after DOM ready
  function _attachCtx(){
    var svg = document.getElementById('blSvg');
    if(svg){ svg.addEventListener('contextmenu', _showCtx); }
    else { setTimeout(_attachCtx, 200); }
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', _attachCtx);
  else _attachCtx();
})();

// On mousedown: if locked open the component modal, else record drag start (id, mouse x, current sx) and bind move/up.
function dragStart(evt,id){
  evt.preventDefault();
  evt.stopPropagation();
  if(ICON_DRAG_LOCKED){
    // Locked: treat as click only (open component modal)
    showComp(id);
    return;
  }
  var pt=svgPt(evt);
  // Find current sx of this component
  var comps=computeLayout();
  var c=comps.find(function(c){return c.id===id;});
  if(!c)return;
  _drag={id:id, startMouseX:pt.x, startSx:c.sx, moved:false};
  document.addEventListener('mousemove',dragMove);
  document.addEventListener('mouseup',dragEnd);
}

// During drag: set moved once |dx|>2px, then write clamped pixel x (20..1160) to state.visualSx and re-render.
function dragMove(evt){
  if(!_drag)return;
  evt.preventDefault();
  var pt=svgPt(evt);
  var dx=pt.x-_drag.startMouseX;
  if(Math.abs(dx)>2) _drag.moved=true;
  if(!_drag.moved) return;
  var newX=Math.max(20,Math.min(1160,_drag.startSx+dx));
  state.visualSx[_drag.id]=newX;
  renderLayout();
}

// On mouseup: unbind handlers; if not moved open modal, else save positions, log, and console-dump DEFAULT_VISUAL_SX.
function dragEnd(evt){
  if(!_drag)return;
  document.removeEventListener('mousemove',dragMove);
  document.removeEventListener('mouseup',dragEnd);
  if(!_drag.moved){
    // It was a click, not a drag → open modal
    showComp(_drag.id);
  } else {
    saveVisualSx();
    log('info',_drag.id+' repositioned (visual)');
    // Print current positions for easy copy
    var keys=Object.keys(state.visualSx).sort(function(a,b){return state.visualSx[a]-state.visualSx[b];});
    var parts=keys.map(function(k){return k+':'+Math.round(state.visualSx[k]);});
    console.log('DEFAULT_VISUAL_SX={'+parts.join(',')+'}');
  }
  _drag=null;
}

// ========== Layout computation ==========

function computeLayout(){
  var sorted=CD.map(function(c){var o={};for(var k in c){o[k]=c[k];}o.pos=state.positions[c.id];return o;}).sort(function(a,b){return a.pos-b.pos;});
  // Default pixel positions from physics
  sorted.forEach(function(c){var p=c.pos;
    if(p<=24)c.sx=35+(p/24)*160;
    else if(p<=34)c.sx=195+((p-24)/10)*280;
    else if(p<=60)c.sx=500+((p-34)/26)*100;
    else if(p<=145)c.sx=620+((p-60)/85)*80;
    else c.sx=720+((p-145)/10)*330;
  });
  // Minimum spacing for defaults
  for(var i=1;i<sorted.length;i++)
    if(sorted[i].sx-sorted[i-1].sx<34)sorted[i].sx=sorted[i-1].sx+34;
  var mx=1140;
  if(sorted[sorted.length-1].sx>mx){
    var sc=(mx-35)/(sorted[sorted.length-1].sx-35);
    sorted.forEach(function(c){c.sx=35+(c.sx-35)*sc;});
  }
  // Apply visual overrides
  if(state.visualSx){
    sorted.forEach(function(c){
      if(state.visualSx[c.id]!==undefined) c.sx=state.visualSx[c.id];
    });
  }
  return sorted;
}

// ========== Generic beam deflection model ==========

// Build beam deflection nodes from sorted component list.
// Returns [{x, y, angle_deg, beamState, id, tp, pitch, rotC1, rotC2, c1X, yC1, c2X, yC2}]
// beamState: 'white' | 'mono' | 'dcm_between' | 'focused'
// view: 'top' or 'side' — only mirrors with matching deflView contribute angle
function buildBeamDeflection(comps, yBaseline, view){
  var vw=view||'top';
  var nodes=[];
  var cumAngle=0; // cumulative beam angle in degrees
  var beamSt='white';
  var thBrad=braggAngle(state.energy);
  var thBdeg=isNaN(thBrad)?11:thBrad*R2D;
  var lastX=0, lastY=yBaseline;
  var sorted=comps.slice().sort(function(a,b){return a.sx-b.sx;});

  // Source node
  var src=null;
  for(var si=0;si<sorted.length;si++){if(sorted[si].tp==='source'){src=sorted[si];break;}}
  if(src){
    nodes.push({x:src.sx,y:yBaseline,angle:0,beamState:'white',id:src.id,tp:src.tp});
    lastX=src.sx; lastY=yBaseline;
  }

  for(var i=0;i<sorted.length;i++){
    var c=sorted[i];
    if(c.tp==='source') continue;
    var opt=c.optics||{};

    // DCM: insert two crystal sub-nodes (only in top view)
    if(opt.monochromatize&&beamSt==='white'){
      if(vw==='top'){
        var c1Off=opt.c1OffsetPx||-H_DCM_PX;
        var c1X=c.sx+c1Off;
        var yC1=lastY+(c1X-lastX)*Math.tan(cumAngle*D2R);
        var angleAtC1=cumAngle;
        var angleBetween=cumAngle+2*thBdeg;
        var sin2thB=Math.sin(2*thBdeg*D2R);
        var L_c1c2=sin2thB>0.02?H_DCM_PX/sin2thB:H_DCM_PX/0.02;
        var c2X=c1X+L_c1c2*Math.cos(angleBetween*D2R);
        var yC2=yC1+L_c1c2*Math.sin(angleBetween*D2R);

        var prevPitch=0;
        for(var pi=nodes.length-1;pi>=0;pi--){
          if(nodes[pi].pitch!==undefined){prevPitch=nodes[pi].pitch;break;}
        }
        var rotC1val=-90+prevPitch+thBdeg;
        var rotC2val=-90+prevPitch+thBdeg;

        nodes.push({x:c1X,y:yC1,angle:angleBetween,beamState:'white',
          id:c.id+'_c1',tp:'dcm_c1',parentId:c.id,rotC1:rotC1val});
        cumAngle=angleBetween-2*thBdeg;
        nodes.push({x:c2X,y:yC2,angle:cumAngle,beamState:'dcm_between',
          id:c.id+'_c2',tp:'dcm_c2',parentId:c.id,rotC2:rotC2val,
          c1X:c1X,yC1:yC1,c2X:c2X,yC2:yC2,thBdeg:thBdeg});
        beamSt='mono';
        lastX=c2X; lastY=yC2;
        nodes.push({x:c.sx,y:lastY+(c.sx-lastX)*Math.tan(cumAngle*D2R),angle:cumAngle,
          beamState:'mono',id:c.id,tp:'dcm_box',parentId:c.id});
      } else {
        // Side view: DCM is passive, just transition beam state
        beamSt='mono';
        var passY=lastY+(c.sx-lastX)*Math.tan(cumAngle*D2R);
        nodes.push({x:c.sx,y:passY,angle:cumAngle,beamState:beamSt,
          id:c.id,tp:c.tp});
        lastX=c.sx; lastY=passY;
      }
      continue;
    }

    // Mirror deflection — only if this mirror's deflView matches current view
    if(opt.pitchKey){
      var pitch=state[opt.pitchKey]||0;
      var newY=lastY+(c.sx-lastX)*Math.tan(cumAngle*D2R);
      var dv=opt.deflView||'top';
      if(dv===vw){
        // This mirror deflects in this view
        cumAngle+=(opt.deflFactor||0)*pitch;
      }
      if(opt.focus&&beamSt==='mono') beamSt='focused';
      nodes.push({x:c.sx,y:newY,angle:cumAngle,beamState:beamSt,
        id:c.id,tp:c.tp,pitch:pitch});
      lastX=c.sx; lastY=newY;
      continue;
    }

    // Focus optic: transition mono -> focused
    if(opt.focus&&beamSt==='mono'){
      beamSt='focused';
    }

    // Passive device: track position on beam
    var passY2=lastY+(c.sx-lastX)*Math.tan(cumAngle*D2R);
    nodes.push({x:c.sx,y:passY2,angle:cumAngle,beamState:beamSt,
      id:c.id,tp:c.tp});
    lastX=c.sx; lastY=passY2;
  }
  return nodes;
}

// Build beamY(x) function from deflection nodes
function makeBeamYFn(nodes,yBaseline){
  // Filter to deflection-relevant nodes (exclude dcm_box which is for side-view only)
  var pts=[];
  for(var i=0;i<nodes.length;i++){
    if(nodes[i].tp!=='dcm_box') pts.push(nodes[i]);
  }
  pts.sort(function(a,b){return a.x-b.x;});
  return function beamY(x){
    if(pts.length===0) return yBaseline;
    if(x<=pts[0].x) return pts[0].y;
    for(var i=0;i<pts.length-1;i++){
      if(x<=pts[i+1].x){
        return pts[i].y+(x-pts[i].x)*Math.tan(pts[i].angle*D2R);
      }
    }
    var last=pts[pts.length-1];
    return last.y+(x-last.x)*Math.tan(last.angle*D2R);
  };
}

// ========== Type-based device SVG renderers ==========

// Source/undulator SVG (variant C): translucent amber housing + a compact
// magnet girder (3 alternating N/S pole pairs, --ac/--rd) with the white beam
// passing through the magnet gap. Same signature/footprint as before.
function _svgSource(x,yT,yS){
  function one(yC){
    var s='';
    s+='<rect x="'+(x-11)+'" y="'+(yC-14)+'" width="22" height="28" rx="2" fill="rgba(255,179,64,0.10)" stroke="var(--am)" stroke-width="1"/>';
    var i,px,cT,cB;
    for(i=0;i<3;i++){
      px=x-8+i*5.7;
      cT=(i%2===0)?'var(--ac)':'var(--rd)';
      cB=(i%2===0)?'var(--rd)':'var(--ac)';
      s+='<rect x="'+px+'" y="'+(yC-11)+'" width="4.5" height="6.5" fill="'+cT+'" opacity="0.85"/>';
      s+='<rect x="'+px+'" y="'+(yC+4.5)+'" width="4.5" height="6.5" fill="'+cB+'" opacity="0.85"/>';
    }
    s+='<line x1="'+(x-11)+'" y1="'+yC+'" x2="'+(x+11)+'" y2="'+yC+'" stroke="var(--ac)" stroke-width="1.2" stroke-dasharray="2,1.5" opacity="0.85"/>';
    return s;
  }
  return {top:one(yT), side:one(yS)};
}
// Return top/side SVG for a mask/shutter as a 6x20px slab, gray for 'mask' else tan, centered on the beam y.
function _svgMask(x,tyC,syC,tp){
  var mc=tp==='mask'?'#808080':'#a08060';
  return {
    top:'<rect x="'+(x-3)+'" y="'+(tyC-10)+'" width="6" height="20" rx="1" fill="var(--s3)" stroke="'+mc+'" stroke-width=".7"/>',
    side:'<rect x="'+(x-3)+'" y="'+(syC-10)+'" width="6" height="20" rx="1" fill="var(--s3)" stroke="'+mc+'" stroke-width=".7"/>'
  };
}
// Slit SVG (variant C): translucent housing + two 4-jaw blocks above/below the
// beam, with the beam passing through the central gap. stroke color overridable
// (default amber); optional fillR overrides the housing fill (used by SSA with a
// --pr override). When fillR is absent the default amber-tinted fill is used, so
// existing call sites that pass only `color` keep their previous behavior.
function _svgSlit(x,tyC,syC,color,fillR){
  var sc=color||'var(--am)';
  var fl=fillR||'rgba(255,179,64,0.08)';
  function one(yC){
    var s='';
    s+='<rect x="'+(x-8)+'" y="'+(yC-13)+'" width="16" height="26" rx="2" fill="'+fl+'" stroke="'+sc+'" stroke-width="0.9"/>';
    s+='<rect x="'+(x-6)+'" y="'+(yC-9)+'" width="12" height="6" rx="1" fill="var(--s3)" stroke="'+sc+'" stroke-width="0.8"/>';
    s+='<rect x="'+(x-6)+'" y="'+(yC+3)+'" width="12" height="6" rx="1" fill="var(--s3)" stroke="'+sc+'" stroke-width="0.8"/>';
    s+='<line x1="'+(x-8)+'" y1="'+yC+'" x2="'+(x+8)+'" y2="'+yC+'" stroke="var(--ac)" stroke-width="1.2" stroke-dasharray="2,1.5" opacity="0.85"/>';
    return s;
  }
  return {top:one(tyC), side:one(syC)};
}
// Ion-chamber SVG: gas-filled chamber box with two parallel HV collection
// plates above/below the beam, an HV lead on top, and the beam passing
// through (transmissive device). Width 18px, centered on the beam y.
function _svgIC(x,tyC,syC){
  function one(yC){
    return '' +
      // chamber body (gas volume, slightly translucent green fill)
      '<rect x="'+(x-9)+'" y="'+(yC-12)+'" width="18" height="24" rx="2" ' +
        'fill="rgba(64,216,154,0.10)" stroke="var(--gn)" stroke-width="1"/>' +
      // HV collection plates (top anode / bottom cathode)
      '<rect x="'+(x-7)+'" y="'+(yC-9)+'" width="14" height="2.5" rx="0.5" ' +
        'fill="var(--am)" opacity="0.9"/>' +
      '<rect x="'+(x-7)+'" y="'+(yC+6.5)+'" width="14" height="2.5" rx="0.5" ' +
        'fill="var(--am)" opacity="0.9"/>' +
      // HV lead wire + terminal dot on top
      '<line x1="'+x+'" y1="'+(yC-12)+'" x2="'+x+'" y2="'+(yC-17)+'" ' +
        'stroke="var(--am)" stroke-width="1"/>' +
      '<circle cx="'+x+'" cy="'+(yC-18)+'" r="1.6" fill="var(--am)"/>' +
      // beam passes through (transmissive): dashed beam segment inside
      '<line x1="'+(x-9)+'" y1="'+yC+'" x2="'+(x+9)+'" y2="'+yC+'" ' +
        'stroke="var(--ac)" stroke-width="1.2" stroke-dasharray="2,1.5" opacity="0.85"/>' +
      // ionization hint: two tiny +/- marks between the plates
      '<text x="'+(x-5)+'" y="'+(yC-2.5)+'" font-size="5" fill="var(--am)" opacity="0.8">+</text>' +
      '<text x="'+(x+2)+'" y="'+(yC+5.5)+'" font-size="5" fill="var(--am)" opacity="0.8">-</text>';
  }
  return { top: one(tyC), side: one(syC) };
}
// Generic mirror SVG (variant C). deflView='top'(default) or 'side' controls
// which view shows the pitch tilt. The deflecting view draws a translucent
// mirror tank + tilted substrate (curved=elliptical KB hint) + footprint dot;
// the non-deflecting view draws the tank seen edge-on as a flat optical bar.
// Optional fillR overrides the tank fill; curved=true draws an elliptical
// substrate (KB). Extra trailing args default so existing M1/M2 call sites
// (_svgMirror(x,tyC,syC,rot)) keep working unchanged.
function _svgMirror(x,tyC,syC,rot,col,colHL,colFill,deflView,fillR,curved){
  col=col||COL_MIRROR; colHL=colHL||COL_MIRROR_HL; colFill=colFill||'#1a2a40';
  fillR=fillR||'rgba(96,160,224,0.07)';
  var dv=deflView||'top';
  function tilt(yC){
    var s='';
    s+='<rect x="'+(x-14)+'" y="'+(yC-14)+'" width="28" height="28" rx="3" fill="'+fillR+'" stroke="'+col+'" stroke-width="0.7"/>';
    if(curved){
      s+='<path d="M '+x+' '+(yC-12)+' Q '+(x+3)+' '+yC+' '+x+' '+(yC+12)+'" fill="none" stroke="'+col+'" stroke-width="3.5" stroke-linecap="round" transform="rotate('+rot+','+x+','+yC+')"/>';
    } else {
      s+='<line x1="'+x+'" y1="'+(yC-12)+'" x2="'+x+'" y2="'+(yC+12)+'" stroke="'+col+'" stroke-width="3.5" stroke-linecap="round" transform="rotate('+rot+','+x+','+yC+')"/>';
    }
    s+='<circle cx="'+x+'" cy="'+yC+'" r="1.8" fill="var(--t1)" opacity="0.85"/>';
    return s;
  }
  function flat(yC){
    var s='';
    s+='<rect x="'+(x-14)+'" y="'+(yC-8)+'" width="28" height="16" rx="2" fill="'+fillR+'" stroke="'+col+'" stroke-width="0.7"/>';
    s+='<rect x="'+(x-11)+'" y="'+(yC-1.8)+'" width="22" height="3.6" rx="1" fill="var(--s3)" stroke="'+col+'" stroke-width="0.8"/>';
    return s;
  }
  if(dv==='side') return {top:flat(tyC), side:tilt(syC)};
  return {top:tilt(tyC), side:flat(syC)};
}
// DCM SVG (variant C): top view draws a translucent vacuum vessel enclosing the
// two tilted purple crystals (from dcm_c1/c2 nodes); side view draws a
// translucent purple Si vessel with through-beam stubs entering/exiting.
function _svgDcm(x,syC,nodes){
  // Find DCM crystal nodes for top view
  var c1n=null,c2n=null;
  for(var i=0;i<nodes.length;i++){
    if(nodes[i].tp==='dcm_c1') c1n=nodes[i];
    if(nodes[i].tp==='dcm_c2') c2n=nodes[i];
  }
  var ti='';
  if(c1n&&c2n){
    ti+='<rect x="'+(c1n.x-10)+'" y="'+(c1n.y-13)+'" width="'+(c2n.x-c1n.x+20)+'" height="'+(c2n.y-c1n.y+26)+'" rx="3" fill="rgba(160,140,255,0.05)" stroke="var(--pr)" stroke-width="0.7"/>';
    ti+='<line x1="'+c1n.x+'" y1="'+(c1n.y-10)+'" x2="'+c1n.x+'" y2="'+(c1n.y+10)+'" stroke="'+COL_DCM+'" stroke-width="3.5" stroke-linecap="round" transform="rotate('+c1n.rotC1+','+c1n.x+','+c1n.y+')"/>';
    ti+='<line x1="'+c2n.x+'" y1="'+(c2n.y-10)+'" x2="'+c2n.x+'" y2="'+(c2n.y+10)+'" stroke="'+COL_DCM+'" stroke-width="3.5" stroke-linecap="round" transform="rotate('+c2n.rotC2+','+c2n.x+','+c2n.y+')"/>';
  }
  var si='';
  si+='<rect x="'+(x-13)+'" y="'+(syC-9)+'" width="26" height="18" rx="2" fill="rgba(160,140,255,0.08)" stroke="'+COL_DCM+'" stroke-width="0.8"/>';
  si+='<text x="'+x+'" y="'+(syC+3)+'" text-anchor="middle" fill="'+COL_DCM+'" font-size="7" font-family="var(--mn)">Si</text>';
  si+='<line x1="'+(x-13)+'" y1="'+syC+'" x2="'+(x-7)+'" y2="'+syC+'" stroke="var(--ac)" stroke-width="1" stroke-dasharray="2,1.5" opacity="0.6"/>';
  si+='<line x1="'+(x+7)+'" y1="'+syC+'" x2="'+(x+13)+'" y2="'+syC+'" stroke="var(--ac)" stroke-width="1" stroke-dasharray="2,1.5" opacity="0.6"/>';
  return {top:ti, side:si};
}
// XBPM SVG (variant C): translucent green ring with four diagonal pickup blades
// pointing toward the center, plus a beam dot where the beam passes through.
function _svgBpm(x,tyC,syC){
  function one(yC){
    var s='';
    s+='<circle cx="'+x+'" cy="'+yC+'" r="7.5" fill="rgba(64,216,154,0.08)" stroke="var(--gn)" stroke-width="1"/>';
    s+='<line x1="'+(x+3.9)+'" y1="'+(yC-3.9)+'" x2="'+(x+1.4)+'" y2="'+(yC-1.4)+'" stroke="var(--gn)" stroke-width="1.8" stroke-linecap="round"/>';
    s+='<line x1="'+(x-3.9)+'" y1="'+(yC-3.9)+'" x2="'+(x-1.4)+'" y2="'+(yC-1.4)+'" stroke="var(--gn)" stroke-width="1.8" stroke-linecap="round"/>';
    s+='<line x1="'+(x+3.9)+'" y1="'+(yC+3.9)+'" x2="'+(x+1.4)+'" y2="'+(yC+1.4)+'" stroke="var(--gn)" stroke-width="1.8" stroke-linecap="round"/>';
    s+='<line x1="'+(x-3.9)+'" y1="'+(yC+3.9)+'" x2="'+(x-1.4)+'" y2="'+(yC+1.4)+'" stroke="var(--gn)" stroke-width="1.8" stroke-linecap="round"/>';
    s+='<circle cx="'+x+'" cy="'+yC+'" r="1.2" fill="var(--ac)" opacity="0.9"/>';
    return s;
  }
  return {top:one(tyC), side:one(syC)};
}
// Attenuator SVG (variant C): translucent housing + a pivot at top with one
// absorber paddle inserted into the beam; the beam is drawn full before the
// paddle and dimmed (attenuated) after it.
function _svgAtten(x,tyC,syC){
  function one(yC){
    var s='';
    s+='<rect x="'+(x-9)+'" y="'+(yC-13)+'" width="18" height="26" rx="2" fill="rgba(77,184,255,0.07)" stroke="var(--ac)" stroke-width="0.9"/>';
    s+='<circle cx="'+x+'" cy="'+(yC-9)+'" r="1.5" fill="var(--t2)"/>';
    s+='<line x1="'+x+'" y1="'+(yC-7.5)+'" x2="'+x+'" y2="'+(yC-3)+'" stroke="var(--am)" stroke-width="1"/>';
    s+='<rect x="'+(x-2)+'" y="'+(yC-3)+'" width="4" height="8" rx="0.8" fill="var(--am)" opacity="0.9"/>';
    s+='<line x1="'+(x-9)+'" y1="'+yC+'" x2="'+(x-2)+'" y2="'+yC+'" stroke="var(--ac)" stroke-width="1.2" stroke-dasharray="2,1.5" opacity="0.85"/>';
    s+='<line x1="'+(x+2)+'" y1="'+yC+'" x2="'+(x+9)+'" y2="'+yC+'" stroke="var(--ac)" stroke-width="1.2" stroke-dasharray="2,1.5" opacity="0.35"/>';
    return s;
  }
  return {top:one(tyC), side:one(syC)};
}
// Return KB-V optic SVG: if KB, a focus-colored side-deflecting mirror at rot=-90+pitch; else ZP rings or CRL lens stack.
function _svgKbv(x,tyC,syC,isKB,fm,pitch){
  pitch=pitch||0;
  if(isKB){
    // KB-V (variant C): elliptical KB mirror (curved substrate) in the focus
    // color, deflecting in side view. Same shape language as M1/M2 but bent.
    var rot=-90+pitch;
    return _svgMirror(x,tyC,syC,rot,COL_FOCUS,COL_FOCUSED,'#1a2a20','side','rgba(224,160,80,0.07)',true);
  }
  // Alternative focus optics (ZP/CRL) shown at KB-V position
  var ti='',si='';
  if(fm==='zp'){
    var zp='';
    var rs=[12,9,6]; var ws=['.6','.8','1.2']; var ops=['.4','.6','.8'];
    for(var zi=0;zi<rs.length;zi++){
      zp+='<circle cx="'+x+'" cy="__Y__" r="'+rs[zi]+'" fill="none" stroke="'+COL_FOCUS+'" stroke-width="'+ws[zi]+'" opacity="'+ops[zi]+'"/>';
    }
    zp+='<circle cx="'+x+'" cy="__Y__" r="3" fill="'+COL_FOCUS+'" opacity=".3"/>';
    zp+='<circle cx="'+x+'" cy="__Y__" r="1" fill="'+COL_FOCUS+'" opacity=".9"/>';
    ti=zp.replace(/__Y__/g,tyC);
    si=zp.replace(/__Y__/g,syC);
  } else {
    var lT='',lS='';var n=4,sp=5;
    for(var ci=0;ci<n;ci++){
      var lx=x-(n-1)*sp/2+ci*sp;
      lT+='<path d="M'+(lx-3)+','+(tyC-10)+' Q'+lx+','+(tyC-4)+' '+(lx+3)+','+(tyC-10)+' L'+(lx+3)+','+(tyC+10)+' Q'+lx+','+(tyC+4)+' '+(lx-3)+','+(tyC+10)+' Z" fill="'+COL_FOCUS_FILL+'" stroke="'+COL_FOCUS+'" stroke-width=".7"/>';
      lS+='<path d="M'+(lx-3)+','+(syC-10)+' Q'+lx+','+(syC-4)+' '+(lx+3)+','+(syC-10)+' L'+(lx+3)+','+(syC+10)+' Q'+lx+','+(syC+4)+' '+(lx-3)+','+(syC+10)+' Z" fill="'+COL_FOCUS_FILL+'" stroke="'+COL_FOCUS+'" stroke-width=".7"/>';
    }
    ti=lT; si=lS;
  }
  return {top:ti,side:si};
}
// KB-H optic SVG (variant C): elliptical KB mirror (curved substrate) in the
// focus color, deflecting in top view; tilted to rot=-90+pitch (degrees).
function _svgKbh(x,tyC,syC,pitch){
  pitch=pitch||0;
  var rot=-90+pitch;
  return _svgMirror(x,tyC,syC,rot,COL_FOCUS,COL_FOCUSED,'#1a2a20','top','rgba(224,160,80,0.07)',true);
}
// Sample SVG (variant C): a pin standing on a goniometer stage, with the sample
// tip at beam height and the beam passing through it.
function _svgSample(x,tyC,syC){
  function one(yC){
    var s='';
    s+='<rect x="'+(x-7)+'" y="'+(yC+6)+'" width="14" height="4" rx="1" fill="var(--s3)" stroke="var(--pk)" stroke-width="0.7"/>';
    s+='<line x1="'+x+'" y1="'+(yC+6)+'" x2="'+x+'" y2="'+(yC+1.5)+'" stroke="var(--pk)" stroke-width="1"/>';
    s+='<circle cx="'+x+'" cy="'+yC+'" r="2.2" fill="var(--pk)"/>';
    s+='<line x1="'+(x-8)+'" y1="'+yC+'" x2="'+(x+8)+'" y2="'+yC+'" stroke="var(--ac)" stroke-width="1" stroke-dasharray="2,1.5" opacity="0.7"/>';
    return s;
  }
  return {top:one(tyC), side:one(syC)};
}
// Detector SVG (variant B = A internals + exterior realism): a translucent
// pixel-array sensor face (with pixel grid + module gaps and a beam impact dot),
// a flange body behind it, plus cooling fins, a mounting post/foot, and a signal
// cable. The detector is the only component using variant B so it reads as the
// visually heaviest endpoint of the beamline.
function _svgDet(x,tyC,syC){
  function one(yC){
    var s='';
    // flange body (behind the sensor face)
    s+='<rect x="'+(x+4)+'" y="'+(yC-10)+'" width="8" height="20" rx="1.5" fill="var(--s2)" stroke="var(--pr)" stroke-width="0.7" opacity="0.9"/>';
    // sensor face
    s+='<rect x="'+(x-8)+'" y="'+(yC-14)+'" width="12" height="28" rx="1.5" fill="rgba(160,140,255,0.10)" stroke="var(--pr)" stroke-width="1"/>';
    // pixel grid + module gaps
    s+='<line x1="'+(x-2)+'" y1="'+(yC-14)+'" x2="'+(x-2)+'" y2="'+(yC+14)+'" stroke="var(--pr)" stroke-width="0.5" opacity="0.45"/>';
    s+='<line x1="'+(x-8)+'" y1="'+(yC-7)+'" x2="'+(x+4)+'" y2="'+(yC-7)+'" stroke="var(--pr)" stroke-width="0.5" opacity="0.45"/>';
    s+='<line x1="'+(x-8)+'" y1="'+(yC+7)+'" x2="'+(x+4)+'" y2="'+(yC+7)+'" stroke="var(--pr)" stroke-width="0.5" opacity="0.45"/>';
    s+='<line x1="'+(x-8)+'" y1="'+yC+'" x2="'+(x+4)+'" y2="'+yC+'" stroke="var(--pr)" stroke-width="0.9" opacity="0.7"/>';
    // incoming beam stops at the face + impact dot
    s+='<line x1="'+(x-14)+'" y1="'+yC+'" x2="'+(x-8)+'" y2="'+yC+'" stroke="var(--ac)" stroke-width="1.2" stroke-dasharray="2,1.5" opacity="0.85"/>';
    s+='<circle cx="'+(x-8)+'" cy="'+yC+'" r="1.5" fill="var(--ac)" opacity="0.85"/>';
    // --- variant B exterior realism ---
    // cooling fins on body
    s+='<line x1="'+(x+12)+'" y1="'+(yC-6)+'" x2="'+(x+14.5)+'" y2="'+(yC-6)+'" stroke="var(--pr)" stroke-width="0.7" opacity="0.7"/>';
    s+='<line x1="'+(x+12)+'" y1="'+(yC-2)+'" x2="'+(x+14.5)+'" y2="'+(yC-2)+'" stroke="var(--pr)" stroke-width="0.7" opacity="0.7"/>';
    s+='<line x1="'+(x+12)+'" y1="'+(yC+2)+'" x2="'+(x+14.5)+'" y2="'+(yC+2)+'" stroke="var(--pr)" stroke-width="0.7" opacity="0.7"/>';
    // mounting post + foot
    s+='<line x1="'+(x+8)+'" y1="'+(yC+10)+'" x2="'+(x+8)+'" y2="'+(yC+16)+'" stroke="var(--t3)" stroke-width="1.4"/>';
    s+='<rect x="'+(x+4)+'" y="'+(yC+16)+'" width="8" height="2.5" rx="0.8" fill="var(--s2)" stroke="var(--t3)" stroke-width="0.6"/>';
    // signal cable
    s+='<path d="M '+(x+12)+' '+(yC+7)+' Q '+(x+16)+' '+(yC+9)+' '+(x+16)+' '+(yC+14)+'" fill="none" stroke="var(--t3)" stroke-width="0.8"/>';
    return s;
  }
  return {top:one(tyC), side:one(syC)};
}

// Dispatch: render SVG for a single device by type
function renderDeviceSVG(c,x,tyC,syC,yT,nodes,isKB,fm){
  var svgOpt=c.svg||{};
  switch(c.tp){
    case 'source': return _svgSource(x,yT,syC);
    case 'mask': case 'shutter': return _svgMask(x,tyC,syC,c.tp);
    case 'ic': return _svgIC(x,tyC,syC);
    case 'slit': return _svgSlit(x,tyC,syC,svgOpt.colorOverride);
    case 'hmirror':{
      var pitch=0; var opt=c.optics||{};
      if(opt.pitchKey) pitch=state[opt.pitchKey]||0;
      var rot=-90+pitch;
      return _svgMirror(x,tyC,syC,rot);
    }
    case 'dcm': return _svgDcm(x,syC,nodes);
    case 'bpm': return _svgBpm(x,tyC,syC);
    case 'atten': return _svgAtten(x,tyC,syC);
    case 'kbv': {
      var kbpitch=0; var kbopt=c.optics||{};
      if(kbopt.pitchKey) kbpitch=state[kbopt.pitchKey]||0;
      return _svgKbv(x,tyC,syC,isKB,fm,kbpitch);
    }
    case 'kbh': {
      var kbpitch2=0; var kbopt2=c.optics||{};
      if(kbopt2.pitchKey) kbpitch2=state[kbopt2.pitchKey]||0;
      return _svgKbh(x,tyC,syC,kbpitch2);
    }
    case 'sample': return _svgSample(x,tyC,syC);
    case 'det': return _svgDet(x,tyC,syC);
    default: return {top:'',side:''};
  }
}

// Get display label for a device
function getDeviceLabel(c,isKB,fm){
  if(c.tp==='kbv'&&!isKB) return fm==='zp'?'ZP':'CRL';
  if(c.tp==='kbh'&&!isKB) return '';
  return c.name;
}

// ========== Render ==========

function renderLayout(){
  var comps=computeLayout();
  var cm={};comps.forEach(function(c){cm[c.id]=c;});
  var tG=document.getElementById('topComp'),sG=document.getElementById('sideComp');
  var tB=document.getElementById('topBeam'),sB=document.getElementById('sideBeam');
  var dG=document.getElementById('distLabels');
  tG.innerHTML='';sG.innerHTML='';dG.innerHTML='';tB.innerHTML='';sB.innerHTML='';

  var yT=82, yS=290;
  var fm=state.focusMode||'kb', isKB=fm==='kb';

  // Build separate deflection models for top and side views
  var nodesTop=buildBeamDeflection(comps,yT,'top');
  var nodesSide=buildBeamDeflection(comps,yS,'side');
  var beamYTop=makeBeamYFn(nodesTop,yT);
  var beamYSide=makeBeamYFn(nodesSide,yS);

  // Render each component
  comps.forEach(function(c){
    var x=c.sx, tyC=beamYTop(x), syC=beamYSide(x);
    var svgOpt=c.svg||{};

    // Skip kbh in non-KB focus mode
    if(c.tp==='kbh'&&!isKB) return;

    var rendered=renderDeviceSVG(c,x,tyC,syC,yT,nodesTop,isKB,fm);
    var ti=rendered.top, si=rendered.side;
    var label=getDeviceLabel(c,isKB,fm);

    tG.innerHTML+='<g class="comp-g" onmousedown="dragStart(event,\''+c.id+'\')">'+
      '<rect class="hit" x="'+(x-18)+'" y="'+(Math.min(tyC,yT)-22)+'" width="36" height="60" fill="transparent" stroke="transparent" rx="3"/>'+
      ti+'<text class="comp-name" x="'+x+'" y="'+(Math.min(tyC,yT)-17)+'" text-anchor="middle">'+label+'</text></g>';
    sG.innerHTML+='<g class="comp-g" onmousedown="dragStart(event,\''+c.id+'\')">'+
      '<rect class="hit" x="'+(x-18)+'" y="'+(Math.min(syC,yS)-22)+'" width="36" height="60" fill="transparent" stroke="transparent" rx="3"/>'+
      si+'<text class="comp-name" x="'+x+'" y="'+(Math.min(syC,yS)-17)+'" text-anchor="middle">'+label+'</text></g>';

    // Distance labels: svg.showDist flag (generic, no hardcoded ID list)
    if(svgOpt.showDist){
      dG.innerHTML+='<text x="'+x+'" y="385" class="dist-label" text-anchor="middle">'+c.pos+'m</text>';
    }
  });

  drawBeamPath(cm,yT,yS,nodesTop,nodesSide,beamYTop,beamYSide,isKB,fm);
}

// ========== Generic beam path drawing ==========

function drawBeamPath(cm,yT,yS,nodesTop,nodesSide,beamYTop,beamYSide,isKB,fm){
  var tB=document.getElementById('topBeam'),sB=document.getElementById('sideBeam');
  var ok=!isNaN(braggAngle(state.energy));
  var t='',s='';

  // Find source and detector for baseline
  var srcX=0,detX=0;
  for(var id in cm){
    if(cm[id].tp==='source') srcX=cm[id].sx;
    if(cm[id].tp==='det') detX=cm[id].sx;
  }

  // Baseline reference lines
  t+='<line x1="'+(srcX-5)+'" y1="'+yT+'" x2="'+(detX+15)+'" y2="'+yT+'" stroke="#203040" stroke-width=".4" stroke-dasharray="4,8"/>';
  s+='<line x1="'+(srcX-5)+'" y1="'+yS+'" x2="'+(detX+15)+'" y2="'+yS+'" stroke="#203040" stroke-width=".4" stroke-dasharray="4,8"/>';

  // Color map
  var stCol={white:COL_WB,mono:COL_MONO,dcm_between:COL_DCM,focused:COL_FOCUSED};

  // Helper: filter nodes for beam path (skip dcm_box)
  function filterBP(nodes){
    var arr=[];
    for(var i=0;i<nodes.length;i++){if(nodes[i].tp!=='dcm_box') arr.push(nodes[i]);}
    arr.sort(function(a,b){return a.x-b.x;});
    return arr;
  }

  var bpTop=filterBP(nodesTop);
  var bpSide=filterBP(nodesSide);

  // White beam fan from source to first slit
  var firstSlitT=null, firstSlitS=null;
  for(var fi=0;fi<bpTop.length;fi++){if(bpTop[fi].tp==='slit'){firstSlitT=bpTop[fi];break;}}
  for(var fi2=0;fi2<bpSide.length;fi2++){if(bpSide[fi2].tp==='slit'){firstSlitS=bpSide[fi2];break;}}
  if(firstSlitT){
    t+='<polygon points="'+srcX+','+yT+' '+firstSlitT.x+','+(yT-5)+' '+firstSlitT.x+','+(yT+5)+'" fill="url(#gWB)" opacity=".25"/>';
  }
  if(firstSlitS){
    s+='<polygon points="'+srcX+','+yS+' '+firstSlitS.x+','+(yS-5)+' '+firstSlitS.x+','+(yS+5)+'" fill="url(#gWB)" opacity=".25"/>';
  }

  if(ok){
    // ====== TOP VIEW: draw segments between consecutive nodes ======
    for(var i=0;i<bpTop.length-1;i++){
      var n0=bpTop[i],n1=bpTop[i+1];
      var col=stCol[n0.beamState]||COL_WB;
      var w=n0.beamState==='mono'?2.0:1.5;
      var op=n0.beamState==='focused'?0.8:0.6;

      if(n0.beamState==='mono'&&n1.beamState==='focused'){
        t+='<polygon points="'+n0.x+','+n0.y+' '+n1.x+','+(n1.y-4)+' '+n1.x+','+(n1.y+4)+'" fill="'+COL_MONO_DIM+'" opacity=".12"/>';
      }
      if(n0.beamState==='focused'&&n1.tp!=='det'){
        t+='<polygon points="'+n0.x+','+(n0.y-4)+' '+n1.x+','+n1.y+' '+n0.x+','+(n0.y+4)+'" fill="'+COL_FOCUSED+'" opacity=".12"/>';
        col=COL_FOCUSED; op=0.8;
      }

      var filter=(n0.beamState==='focused')?' filter="url(#gl)"':'';
      t+='<line x1="'+n0.x+'" y1="'+n0.y+'" x2="'+n1.x+'" y2="'+n1.y+'" stroke="'+col+'" stroke-width="'+w+'" opacity="'+op+'"'+filter+'/>';

      if(n1.tp!=='dcm_c1'&&n1.tp!=='source'&&n1.tp!=='bpm'){
        var dotCol=stCol[n1.beamState]||col;
        var dotR=n1.tp==='sample'?3.5:(n1.tp==='hmirror'?3:2.5);
        var dotFilter=n1.tp==='sample'?' filter="url(#glS)"':'';
        var dotOp=n1.tp==='sample'?'.9':'.7';
        t+='<circle cx="'+n1.x+'" cy="'+n1.y+'" r="'+dotR+'" fill="'+dotCol+'" opacity="'+dotOp+'"'+dotFilter+'/>';
      }
    }

    // Detector scatter fan (top)
    var sampNodeT=null,detNodeT=null;
    for(var di=0;di<bpTop.length;di++){
      if(bpTop[di].tp==='sample') sampNodeT=bpTop[di];
      if(bpTop[di].tp==='det') detNodeT=bpTop[di];
    }
    if(sampNodeT&&detNodeT){
      t+='<polygon points="'+sampNodeT.x+','+sampNodeT.y+' '+detNodeT.x+','+(detNodeT.y-10)+' '+detNodeT.x+','+(detNodeT.y+10)+'" fill="var(--pr2)" opacity=".15"/>';
    }

    // DCM annotations (if DCM present in top view)
    var c1n=null,c2n=null;
    for(var ai=0;ai<nodesTop.length;ai++){
      if(nodesTop[ai].tp==='dcm_c1') c1n=nodesTop[ai];
      if(nodesTop[ai].tp==='dcm_c2') c2n=nodesTop[ai];
    }
    if(c1n&&c2n){
      var thBdeg=c2n.thBdeg||11;
      var thAnn=braggAngle(state.energy);
      var gapMm=isNaN(thAnn)?'-':dcmGap(thAnn).toFixed(1);
      var afterDcmY=c2n.y;
      for(var mi=0;mi<bpTop.length;mi++){
        if(bpTop[mi].tp==='hmirror'&&bpTop[mi].x>c2n.x){afterDcmY=bpTop[mi].y;break;}
      }
    }

    // ====== SIDE VIEW: beam with KB-V deflection ======
    for(var j=0;j<bpSide.length-1;j++){
      var sn0=bpSide[j],sn1=bpSide[j+1];
      var sCol=stCol[sn0.beamState]||COL_WB;
      var sW=sn0.beamState==='mono'?2.5:1.5;
      var sOp=sn0.beamState==='mono'?'.9':'.6';

      if(sn0.beamState==='mono'&&sn1.beamState==='focused'){
        s+='<polygon points="'+sn0.x+','+sn0.y+' '+sn1.x+','+(sn1.y-4)+' '+sn1.x+','+(sn1.y+4)+'" fill="'+COL_MONO_DIM+'" opacity=".12"/>';
      }
      if(sn0.beamState==='focused'&&sn1.tp!=='det'){
        s+='<polygon points="'+sn0.x+','+(sn0.y-4)+' '+sn1.x+','+sn1.y+' '+sn0.x+','+(sn0.y+4)+'" fill="'+COL_FOCUSED+'" opacity=".12"/>';
        sCol=COL_FOCUSED; sOp='.8';
      }

      var sFilter=(sn0.beamState==='focused')?' filter="url(#gl)"':'';
      s+='<line x1="'+sn0.x+'" y1="'+sn0.y+'" x2="'+sn1.x+'" y2="'+sn1.y+'" stroke="'+sCol+'" stroke-width="'+sW+'" opacity="'+sOp+'"'+sFilter+'/>';

      if(sn1.tp==='slit'||sn1.tp==='sample'){
        var sDotCol=stCol[sn1.beamState]||sCol;
        var sDotR=sn1.tp==='sample'?3.5:2.5;
        var sDotF=sn1.tp==='sample'?' filter="url(#glS)"':'';
        s+='<circle cx="'+sn1.x+'" cy="'+sn1.y+'" r="'+sDotR+'" fill="'+sDotCol+'" opacity=".7"'+sDotF+'/>';
      }
      if(sn1.beamState==='focused'&&sn0.beamState==='mono'){
        s+='<circle cx="'+sn1.x+'" cy="'+sn1.y+'" r="2.5" fill="'+COL_FOCUS+'" opacity=".7"/>';
      }
    }

    // Detector scatter fan (side)
    var sampNodeS=null,detNodeS=null;
    for(var di2=0;di2<bpSide.length;di2++){
      if(bpSide[di2].tp==='sample') sampNodeS=bpSide[di2];
      if(bpSide[di2].tp==='det') detNodeS=bpSide[di2];
    }
    if(sampNodeS&&detNodeS){
      s+='<polygon points="'+sampNodeS.x+','+sampNodeS.y+' '+detNodeS.x+','+(detNodeS.y-10)+' '+detNodeS.x+','+(detNodeS.y+10)+'" fill="var(--pr2)" opacity=".15"/>';
    }
  }

  tB.innerHTML=t; sB.innerHTML=s;
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof H_DCM_PX!=="undefined")globalThis.H_DCM_PX=H_DCM_PX;
if(typeof ICON_DRAG_LOCKED!=="undefined")globalThis.ICON_DRAG_LOCKED=ICON_DRAG_LOCKED;
if(typeof buildBeamDeflection!=="undefined")globalThis.buildBeamDeflection=buildBeamDeflection;
if(typeof computeLayout!=="undefined")globalThis.computeLayout=computeLayout;
if(typeof dragEnd!=="undefined")globalThis.dragEnd=dragEnd;
if(typeof dragMove!=="undefined")globalThis.dragMove=dragMove;
if(typeof dragStart!=="undefined")globalThis.dragStart=dragStart;
if(typeof drawBeamPath!=="undefined")globalThis.drawBeamPath=drawBeamPath;
if(typeof getDeviceLabel!=="undefined")globalThis.getDeviceLabel=getDeviceLabel;
if(typeof loadVisualSx!=="undefined")globalThis.loadVisualSx=loadVisualSx;
if(typeof makeBeamYFn!=="undefined")globalThis.makeBeamYFn=makeBeamYFn;
if(typeof null!=="undefined")globalThis.null=null;
if(typeof renderDeviceSVG!=="undefined")globalThis.renderDeviceSVG=renderDeviceSVG;
if(typeof renderLayout!=="undefined")globalThis.renderLayout=renderLayout;
if(typeof resetVisualSx!=="undefined")globalThis.resetVisualSx=resetVisualSx;
if(typeof saveVisualSx!=="undefined")globalThis.saveVisualSx=saveVisualSx;
if(typeof svgPt!=="undefined")globalThis.svgPt=svgPt;
if(typeof COL_DCM!=="undefined")globalThis.COL_DCM=COL_DCM;
if(typeof COL_DCM_FILL!=="undefined")globalThis.COL_DCM_FILL=COL_DCM_FILL;
if(typeof COL_FOCUS!=="undefined")globalThis.COL_FOCUS=COL_FOCUS;
if(typeof COL_FOCUSED!=="undefined")globalThis.COL_FOCUSED=COL_FOCUSED;
if(typeof COL_FOCUS_FILL!=="undefined")globalThis.COL_FOCUS_FILL=COL_FOCUS_FILL;
if(typeof COL_MIRROR!=="undefined")globalThis.COL_MIRROR=COL_MIRROR;
if(typeof COL_MIRROR_HL!=="undefined")globalThis.COL_MIRROR_HL=COL_MIRROR_HL;
if(typeof COL_MONO!=="undefined")globalThis.COL_MONO=COL_MONO;
if(typeof COL_MONO_DIM!=="undefined")globalThis.COL_MONO_DIM=COL_MONO_DIM;
if(typeof COL_WB!=="undefined")globalThis.COL_WB=COL_WB;
if(typeof D2R!=="undefined")globalThis.D2R=D2R;
if(typeof DEFAULT_VISUAL_SX!=="undefined")globalThis.DEFAULT_VISUAL_SX=DEFAULT_VISUAL_SX;
if(typeof R2D!=="undefined")globalThis.R2D=R2D;
if(typeof _drag!=="undefined")globalThis._drag=_drag;
if(typeof _svgAtten!=="undefined")globalThis._svgAtten=_svgAtten;
if(typeof _svgBpm!=="undefined")globalThis._svgBpm=_svgBpm;
if(typeof _svgDcm!=="undefined")globalThis._svgDcm=_svgDcm;
if(typeof _svgDet!=="undefined")globalThis._svgDet=_svgDet;
if(typeof _svgKbh!=="undefined")globalThis._svgKbh=_svgKbh;
if(typeof _svgKbv!=="undefined")globalThis._svgKbv=_svgKbv;
if(typeof _svgMask!=="undefined")globalThis._svgMask=_svgMask;
if(typeof _svgMirror!=="undefined")globalThis._svgMirror=_svgMirror;
if(typeof _svgSample!=="undefined")globalThis._svgSample=_svgSample;
if(typeof _svgSlit!=="undefined")globalThis._svgSlit=_svgSlit;
if(typeof _svgSource!=="undefined")globalThis._svgSource=_svgSource;
if(typeof startMouseX!=="undefined")globalThis.startMouseX=startMouseX;
