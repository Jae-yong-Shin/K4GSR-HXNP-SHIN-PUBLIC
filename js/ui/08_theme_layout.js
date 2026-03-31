'use strict';
// ===== ui/08_theme_layout.js — Theme, Layout & MC Rays Settings =====
// @module ui/08_theme_layout
// @exports setMCGrid, setMCRays, setUILayout, setUITheme, toggleModeMenu
// Extracted from 14_v435_final.js (DDD Phase 5b)
// Provides: setUITheme, setUILayout, setMCRays, toggleModeMenu

// === UI Theme & Layout Mode System ===
(function(){
  var THEMES = [
    {id:'light',   label:'Light (Default)',    desc:'Clean white background'},
    {id:'dark',    label:'Dark',               desc:'High contrast dark theme'},
    {id:'dark2',   label:'Dark 2',             desc:'Muted dark theme'},
    {id:'deuter',  label:'Deuteranopia',       desc:'Red-green color blind safe'},
    {id:'protan',  label:'Protanopia',         desc:'Red blind safe'},
    {id:'tritan',  label:'Tritanopia',         desc:'Blue-yellow color blind safe'}
  ];
  var LAYOUTS = [
    {id:'standard', label:'Standard',  desc:'Full panel layout (320px sidebar)'},
    {id:'wide',     label:'Wide View', desc:'Hide sidebar, maximize beamline view'},
    {id:'compact',  label:'Compact',   desc:'Narrow sidebar (220px)'},
    {id:'focus',    label:'Focus',     desc:'Beamline only, hide all panels'}
  ];

  var curTheme = 'light';
  var curLayout = 'standard';

  function applyTheme(id) {
    THEMES.forEach(function(t) { document.body.classList.remove('theme-' + t.id); });
    if (id !== 'light') document.body.classList.add('theme-' + id);
    curTheme = id;
    try { localStorage.setItem('bl10_theme', id); } catch(e){}
    renderModeMenu();
  }

  function applyLayout(id) {
    LAYOUTS.forEach(function(l) { document.body.classList.remove('layout-' + l.id); });
    if (id !== 'standard') document.body.classList.add('layout-' + id);
    curLayout = id;
    try { localStorage.setItem('bl10_layout', id); } catch(e){}
    renderModeMenu();
  }

  function renderModeMenu() {
    var el = document.getElementById('modeMenu');
    if (!el) return;
    var h = '<h5>' + _t('hdr_theme') + '</h5>';
    THEMES.forEach(function(t) {
      var act = (t.id === curTheme) ? ' active' : '';
      h += '<div class="mode-opt' + act + '" onclick="setUITheme(\'' + t.id + '\')">' +
        '<span class="dot"></span>' +
        '<div><div style="font-weight:500">' + _t('theme_' + t.id) + '</div>' +
        '<div style="font-size:8px;color:var(--t3)">' + _t('themedesc_' + t.id) + '</div></div></div>';
    });
    h += '<h5>' + _t('hdr_layout') + '</h5>';
    LAYOUTS.forEach(function(l) {
      var act = (l.id === curLayout) ? ' active' : '';
      h += '<div class="mode-opt' + act + '" onclick="setUILayout(\'' + l.id + '\')">' +
        '<span class="dot"></span>' +
        '<div><div style="font-weight:500">' + _t('layout_' + l.id) + '</div>' +
        '<div style="font-size:8px;color:var(--t3)">' + _t('layoutdesc_' + l.id) + '</div></div></div>';
    });
    // --- MC Ray Count ---
    h += '<h5>' + _t('hdr_mcrays') + '</h5>';
    var RAY_OPTS = [
      {v:10000,  label:'10K',  descKey:'mcrays_fast'},
      {v:50000,  label:'50K',  descKey:'mcrays_normal'},
      {v:100000, label:'100K', descKey:'mcrays_default'},
      {v:200000, label:'200K', descKey:'mcrays_precise'},
      {v:500000, label:'500K', descKey:'mcrays_best'}
    ];
    RAY_OPTS.forEach(function(r) {
      var act = (MC_NRAYS === r.v) ? ' active' : '';
      h += '<div class="mode-opt' + act + '" onclick="setMCRays(' + r.v + ')">' +
        '<span class="dot"></span>' +
        '<div><div style="font-weight:500">' + r.label + '</div>' +
        '<div style="font-size:8px;color:var(--t3)">' + _t(r.descKey) + '</div></div></div>';
    });

    // --- Grid Resolution ---
    h += '<h5>' + _t('hdr_grid') + '</h5>';
    var GRID_OPTS = [
      {v:51,  label:'Standard (51)',  descKey:'grid_standard'},
      {v:201, label:'High-res (201)', descKey:'grid_highres'}
    ];
    GRID_OPTS.forEach(function(g) {
      var act = (MC_GRID === g.v) ? ' active' : '';
      h += '<div class="mode-opt' + act + '" onclick="setMCGrid(' + g.v + ')">' +
        '<span class="dot"></span>' +
        '<div><div style="font-weight:500">' + g.label + '</div>' +
        '<div style="font-size:8px;color:var(--t3)">' + _t(g.descKey) + '</div></div></div>';
    });

    el.innerHTML = h;
  }

  window.setMCRays = function(n) {
    MC_NRAYS = n;
    try { localStorage.setItem('bl10_mcrays', String(n)); } catch(e){}
    renderModeMenu();
    log('info', 'MC rays \u2192 ' + n.toLocaleString());
    // Re-run simulation to reflect new ray count
    if (typeof updateOptics === 'function') updateOptics();
  };

  window.setMCGrid = function(g) {
    MC_GRID = g;
    try { localStorage.setItem('bl10_mcgrid', String(g)); } catch(e){}
    renderModeMenu();
    log('info', 'MC grid \u2192 ' + g + 'x' + g);
    if (typeof updateOptics === 'function') updateOptics();
  };

  window.setUITheme = function(id) { applyTheme(id); };
  window.setUILayout = function(id) { applyLayout(id); };
  window.toggleModeMenu = function() {
    var el = document.getElementById('modeMenu');
    if (!el) return;
    var isOpen = el.classList.contains('open');
    el.classList.toggle('open');
    if (!isOpen) {
      renderModeMenu();
      // Close on outside click
      setTimeout(function() {
        function closeMenu(e) {
          if (!el.contains(e.target) && e.target.id !== 'modeSelectorBtn') {
            el.classList.remove('open');
            document.removeEventListener('click', closeMenu);
          }
        }
        document.addEventListener('click', closeMenu);
      }, 10);
    }
  };

  // Keyboard shortcut: Ctrl+Shift+T = cycle theme, Ctrl+Shift+L = cycle layout
  document.addEventListener('keydown', function(e) {
    if (e.ctrlKey && e.shiftKey && e.key === 'T') {
      e.preventDefault();
      var idx = THEMES.findIndex(function(t) { return t.id === curTheme; });
      applyTheme(THEMES[(idx + 1) % THEMES.length].id);
    }
    if (e.ctrlKey && e.shiftKey && e.key === 'L') {
      e.preventDefault();
      var idx = LAYOUTS.findIndex(function(l) { return l.id === curLayout; });
      applyLayout(LAYOUTS[(idx + 1) % LAYOUTS.length].id);
    }
  });

  // Restore saved preferences
  try {
    var saved = localStorage.getItem('bl10_theme');
    if (saved && THEMES.some(function(t){return t.id===saved;})) applyTheme(saved);
    var savedL = localStorage.getItem('bl10_layout');
    if (savedL && LAYOUTS.some(function(l){return l.id===savedL;})) applyLayout(savedL);
    var savedR = localStorage.getItem('bl10_mcrays');
    if (savedR) { var nr = parseInt(savedR, 10); if (nr > 0) MC_NRAYS = nr; }
    var savedG = localStorage.getItem('bl10_mcgrid');
    if (savedG) { var ng = parseInt(savedG, 10); if (ng > 10) MC_GRID = ng; }
  } catch(e){}

  renderModeMenu();
  console.log('[V4.36] Theme & layout mode system loaded');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof setMCGrid!=="undefined")globalThis.setMCGrid=setMCGrid;
if(typeof setMCRays!=="undefined")globalThis.setMCRays=setMCRays;
if(typeof setUILayout!=="undefined")globalThis.setUILayout=setUILayout;
if(typeof setUITheme!=="undefined")globalThis.setUITheme=setUITheme;
if(typeof toggleModeMenu!=="undefined")globalThis.toggleModeMenu=toggleModeMenu;
