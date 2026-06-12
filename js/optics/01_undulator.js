'use strict';
// ===== optics/01_undulator.js — IVU Physics (validated SRCalc) =====
// @module optics/01_undulator
// @exports besselJ, calcB0, calcBrt, calcE1, calcK, calcPtotal, coupFn, findHarmonics, onAxisFlux, resonanceEnergy, selectBest, solveGap, undulatorSinc2
// Extracted from 02_physics.js (DDD Phase 2)

function calcB0(g){var r=g/LAMBDA_U;return HALB_A*Math.exp(HALB_B*r+HALB_C*r*r);}
// Deflection parameter K = 0.9341 * B0[T] * (LAMBDA_U[mm]/10) from the peak field B0.
function calcK(B0){return 0.9341*B0*(LAMBDA_U/10);}
// First-harmonic resonance energy E1 = 0.9498*E_RING^2/((LAMBDA_U/10)*(1+K^2/2)) in keV from K.
function calcE1(K){return 0.9498*E_RING*E_RING/((LAMBDA_U/10)*(1+K*K/2));}
function calcPtotal(B0){return 633*E_RING*E_RING*B0*B0*L_UND*I_RING_A;} // Watts
// Energy-angle coupling (Kim 1989): resonance energy at observation angle theta
// E_res(theta) = n*E1 / (1 + gamma^2*theta^2/(1+K^2/2))
function resonanceEnergy(E1,K,theta,n){n=n||1;return n*E1/(1+GAMMA_E*GAMMA_E*theta*theta/(1+K*K/2));}
// sinc^2 spectral function: exact undulator spectral shape (Spectra convention)
function undulatorSinc2(E,Eres){var x=Math.PI*N_PERIODS*(E/Eres-1);return Math.abs(x)<1e-10?1:Math.pow(Math.sin(x)/x,2);}

// Integer-order Bessel function J_n(x) via the power series; returns 1/0 at x~0 for n=0/n!=0.
function besselJ(n,x){if(Math.abs(x)<1e-10)return n===0?1:0;var s=0,fM=1,fN=1;for(var i=1;i<=n;i++)fN*=i;for(var m=0;m<30;m++){if(m>0){fM*=m;fN*=(m+n);}var t=Math.pow(-1,m)/fM/fN*Math.pow(x/2,2*m+n);s+=t;if(Math.abs(t)<1e-15*Math.abs(s||1))break;}return s;}
// Planar-undulator coupling factor F_n(K)=n^2 K^2 (J difference)^2/(1+K^2/2)^2 for odd harmonic n.
function coupFn(K,n){var xi=K*K/(4+2*K*K);var j1=besselJ(Math.floor((n-1)/2),n*xi),j2=besselJ(Math.floor((n+1)/2),n*xi);var JJ=j1-j2;return n*n*K*K*JJ*JJ/Math.pow(1+K*K/2,2);}
// Filament on-axis flux 1.431e14*N_PERIODS*I[A]*F_n(K) in ph/s/0.1%BW (no beam-size effects).
function onAxisFlux(K,n){return 1.431e14*N_PERIODS*I_RING_A*coupFn(K,n);}
// === On-axis flux-density suppression by energy spread + emittance (Tanaka 2014) ===
// Tanaka, Phys. Rev. ST-AB 17, 060702 (2014), Eq.(22)-(24): the n-th harmonic
// single-electron on-axis intensity, averaged over the electron-beam angular
// divergence (sigma_e') AND relative energy spread (sigma_delta):
//   S_full(n) = < sinc^2( pi[ (thx^2+thy^2)/(4 sigma_nr'^2) - 2 n N eta ] ) >
// with the natural (diffraction-limited) divergence  sigma_nr' = sqrt(lambda_n/2L)
// and eta=(gamma-gamma0)/gamma0 (sigma=sigma_delta).  Off-axis electrons red-shift
// their harmonic away from the on-axis peak, and energy spread smears it; both
// suppress the on-axis flux density of high harmonics.  Validated vs spectra_solver:
// on-axis flux density AND brilliance within <=17% up to n=11 (K=1.87), NO tuning.
// Far-field angle-dependent amplitude |fxy|^2 of a planar undulator (Kx=0,
// Ky=K) at observation angle theta (gt = gamma*theta) and azimuth phi, odd
// harmonic nh. PHYSICS SOURCE: the published Bessel-series expressions for
// f_x, f_y — K.-J. Kim, AIP Conf. Proc. 184, 565 (1989); T. Tanaka &
// H. Kitamura, J. Synchrotron Rad. 8, 1221 (2001) [SPECTRA code paper];
// T. Tanaka, J. Synchrotron Rad. 28, 1267 (2021). This is an INDEPENDENT
// ES5 implementation of those published equations; the SPECTRA program
// (undulator_fxy_far.cpp f_LinearFxy) was used as the VALIDATION REFERENCE
// to confirm series handling and convergence (on-axis flux density within
// <=1% to n=11 vs spectra_solver) — no SPECTRA source code is included or
// redistributed here. On-axis (gt=0) it equals coupFn(K,nh) exactly;
// off-axis it falls below coupFn, which suppresses the emittance red-shift
// shoulder missing from the constant-amplitude model.
function _cdiv(a, b){ var q = Math.floor(Math.abs(a)/Math.abs(b)); return ((a<0)!==(b<0)) ? -q : q; }
// Signed Bessel helper applying J_-m = (-1)^m J_m so negative orders are handled in the f_LinearFxy sum.
function _jnS(m, x){ return m >= 0 ? besselJ(m, x) : (((-m)%2===0?1:-1) * besselJ(-m, x)); }
// SPECTRA far-field |fxy|^2 angular amplitude at gamma*theta and azimuth phi for odd nh; equals F_n(K) on-axis.
function fLinFxy2(K, nh, gt, phi){
  var gsi = nh/(1 + K*K/2 + gt*gt), z = K*K*gsi/4, u = Math.cos(phi), v = Math.sin(phi);
  var x = 2*gt*K*gsi*u, INF = 1e-30, fx0, fy0, s1, s2, m, ia, ib, nn, bjx, bjz1, bjz2, ds1, ds2, ssum, dssum, fds, ds1a;
  if(Math.abs(x) > 1e-3){                 // off-axis (odd nh)
    s1 = INF; s2 = INF; ssum = INF; ds1a = s1; m = 1;
    while(m < 200){
      ia = _cdiv(2*m-1-nh, 2); ib = _cdiv(-2*m+1-nh, 2);
      bjz1 = _jnS(ia, z); bjz2 = _jnS(ib, z); nn = 2*m-1; bjx = _jnS(nn, x);
      ds1 = bjx*(bjz1-bjz2); ds2 = bjx*(ia*bjz1-ib*bjz2);
      s1 += ds1; s2 += ds2;
      dssum = Math.abs(bjx)+Math.abs(bjz1)+Math.abs(bjz2); ssum += Math.abs(dssum);
      fds = (dssum+ds1a)/ssum; ds1a = dssum;
      fds = Math.max(fds, Math.abs(ds1/(s1+INF)), Math.abs(ds2/(s2+INF))); m++;
      if(fds <= 1e-9) break;
    }
    fx0 = -(nh*s1+2*s2)/gt/u + 2*gt*gsi*s1*u; fy0 = 2*s1*gt*v*gsi;
  } else {                                // near axis (odd nh)
    var naa = _cdiv(-nh-1, 2), nbb = _cdiv(-nh+1, 2);
    s1 = _jnS(1, x)*(_jnS(nbb, z)-_jnS(naa, z)); s2 = _jnS(naa, z)+_jnS(nbb, z);
    fx0 = gsi*(2*s1*gt*u - K*s2); fy0 = 2*gsi*s1*gt*v;
  }
  return fx0*fx0 + fy0*fy0;
}
// Auto-sampling: grid sizes adapted to harmonic n so the energy-spread sinc^2
// (oscillation period 1/(2nN) in delta) and the angular profile are resolved at
// EVERY harmonic (Nyquist). nE grows with n (faster eta oscillation); nA covers the
// e-beam angular range in units of the natural divergence s0=sqrt(lambda_n/2L).
function _undGrids(K, n){
  var s0 = Math.sqrt((HC/(n*calcE1(K)))*1e-10/(2*L_UND));
  var thmax = 5*Math.max(SIG_EXP, SIG_EYP)/(2*s0);
  return { nA: Math.min(81, Math.max(41, Math.ceil(12*thmax)|1)),
           nE: Math.max(31, Math.ceil(80*n*N_PERIODS*E_SPREAD)|1) };
}
// Memo map keyed by K(4dp)_n holding computed energy-spread+emittance on-axis suppression factors.
var _esSuppCache = {};
// On-axis flux-density suppression factor from beam divergence and energy spread by phase-space sinc^2 integration; cached.
function eSpreadAngleSupp(K, n) {
  var key = K.toFixed(4) + '_' + n;
  if (_esSuppCache[key] !== undefined) return _esSuppCache[key];
  var En = calcE1(K) * n;
  var s0 = Math.sqrt((HC / En) * 1e-10 / (2 * L_UND));   // natural divergence (rad)
  var f4 = 4 * s0 * s0, twoNN = 2 * n * N_PERIODS;
  function gw(sig, m) {  // uniform Gaussian-weighted nodes on +/-5 sigma
    var v = [], w = [], s = 0, j, x, ww;
    for (j = 0; j < m; j++) { x = (-5 + 10 * j / (m - 1)) * sig; ww = Math.exp(-x * x / (2 * sig * sig)); v.push(x); w.push(ww); s += ww; }
    for (j = 0; j < m; j++) w[j] /= s;
    return { v: v, w: w };
  }
  var gr = _undGrids(K, n), nA = gr.nA, nEt = gr.nE, ia, ib, ie;  // auto-sampling per harmonic
  var gx = gw(SIG_EXP, nA), gy = gw(SIG_EYP, nA), ge = gw(E_SPREAD, nEt);
  var cf = coupFn(K, n), acc = 0, wab, r2, x, sc, gt, th2;
  for (ia = 0; ia < nA; ia++) {
    for (ib = 0; ib < nA; ib++) {
      th2 = gx.v[ia] * gx.v[ia] + gy.v[ib] * gy.v[ib];
      gt = GAMMA_E * Math.sqrt(th2);            // gamma*theta for angle amplitude
      wab = gx.w[ia] * gy.w[ib] *
            (cf > 1e-300 ? fLinFxy2(K, n, gt, Math.atan2(gy.v[ib], gx.v[ia])) / cf : 1);
      r2 = th2 / f4;                            // theta_hat^2
      for (ie = 0; ie < nEt; ie++) {
        x = Math.PI * (r2 - twoNN * ge.v[ie]);
        sc = (x > -1e-9 && x < 1e-9) ? 1 : Math.sin(x) / x;
        acc += wab * ge.w[ie] * sc * sc;
      }
    }
  }
  _esSuppCache[key] = acc;
  return acc;
}
// On-axis angular flux density (Kim 1989), energy-spread + emittance suppressed:
//   FD0 = 1.744e14 * N^2 * E[GeV]^2 * I[A] * Fn(K) * S_full(n)  [ph/s/mrad^2/0.1%BW]
function onAxisFluxDensity(K, n) {
  n = n || 1;
  return 1.744e14 * N_PERIODS * N_PERIODS * E_RING * E_RING * I_RING_A
         * coupFn(K, n) * eSpreadAngleSupp(K, n);
}
// === On-axis angular flux-density SPECTRUM (Tanaka-Kitamura finite-beam) ===
// Numerical phase-space convolution of the single-electron undulator harmonic
// (filament coupling onAxisFlux(K,n), sinc^2 lineshape) over the electron-beam
// energy spread AND angular divergence -- the same physics SPECTRA evaluates.
// Each electron (energy offset delta, angle theta) emits its n-th harmonic at
//   E_n = n*E1*(1+delta)^2 / (1 + gamma^2*theta^2/(1+K^2/2)),
// so energy spread (symmetric) and emittance (one-sided angular red-shift) are
// captured jointly (not as a separable product), which reproduces SPECTRA's
// harmonic-intensity envelope (significant peaks within a few % over K=1-2.5).
// @param {number[]} energies - photon energies (keV), ASCENDING
// @param {number} [K] - deflection parameter (default from current gap)
// @returns {number[]} on-axis angular flux density (arb., normalisable)
function undulatorSpectrum(energies,K){
  if(K===undefined||K===null)K=calcK(calcB0(state.gap));
  var E1=calcE1(K),H=1+K*K/2,N=N_PERIODS,sd=E_SPREAD,g2=GAMMA_E*GAMMA_E;
  var COEF=1.744e14*N*N*E_RING*E_RING*I_RING_A; // Kim on-axis flux-density coefficient
  function _grid(sig,m){var v=[],w=[],s=0,j;for(j=0;j<m;j++){var x=(-5+10*j/(m-1))*sig,ww=Math.exp(-x*x/(2*sig*sig));v.push(x);w.push(ww);s+=ww;}for(j=0;j<m;j++)w[j]/=s;return {v:v,w:w};}
  var nE=energies.length,out=new Array(nE),i;for(i=0;i<nE;i++)out[i]=0;
  function _lb(val){var lo=0,hi=nE;while(lo<hi){var m=(lo+hi)>>1;if(energies[m]<val)lo=m+1;else hi=m;}return lo;}
  var Emax=energies[nE-1];
  for(var n=1;n<=199&&n*E1<Emax*1.1;n+=2){
    var gr=_undGrids(K,n),gd=_grid(sd,gr.nE),gx=_grid(SIG_EXP,gr.nA),gy=_grid(SIG_EYP,gr.nA);
    var En0=n*E1,piNn=Math.PI*n*N,bw=7.0/(n*N),a,b,id,thx,thy,th2,gt,redA,amp,wab;
    for(a=0;a<gx.v.length;a++){thx=gx.v[a];
      for(b=0;b<gy.v.length;b++){thy=gy.v[b];th2=thx*thx+thy*thy;
        // angle-dependent flux-density amplitude (SPECTRA f_LinearFxy); falls off-axis
        gt=GAMMA_E*Math.sqrt(th2);redA=1/(1+g2*th2/H);
        amp=COEF*fLinFxy2(K,n,gt,Math.atan2(thy,thx));wab=gx.w[a]*gy.w[b];
        for(id=0;id<gd.v.length;id++){
          var En=En0*(1+gd.v[id])*(1+gd.v[id])*redA,wgt=amp*wab*gd.w[id];
          var lo=_lb(En*(1-bw)),hi=_lb(En*(1+bw));
          for(i=lo;i<hi;i++){var x=piNn*(energies[i]/En-1);
            out[i]+=wgt*(x>-1e-10&&x<1e-10?1:Math.pow(Math.sin(x)/x,2));}
        }
      }
    }
  }
  return out;
}
// === Acceptance partial flux (Table 3 §3.3) ===
// Integrates the angle-dependent on-axis flux density over a rectangular
// observation aperture of ±halfH_urad (horizontal) by ±halfV_urad (vertical),
// with full electron-beam phase-space convolution (sigma_x', sigma_y',
// energy spread). When halfV_urad is omitted, it defaults to halfH_urad,
// reproducing the legacy square-aperture call (e.g. ±20 µrad = 40 µrad square).
// Returns the PEAK of the partial-flux spectrum (slightly red-shifted from n*E1),
// matching SPECTRA's `pflux` output. Units: ph/s/0.1%BW.
// Validated vs SPECTRA Table 3 (K=1.87, n=3..11): <=2.0%.
var _accFluxCache = {};
// Peak partial flux (ph/s/0.1%BW) through a +/-halfH x +/-halfV urad aperture via full phase-space convolution; cached.
function fluxAcceptance(K, n, halfH_urad, halfV_urad) {
  if (halfH_urad === undefined) halfH_urad = 20;
  if (halfV_urad === undefined) halfV_urad = halfH_urad;
  var key = K.toFixed(4) + '_' + n + '_' + halfH_urad.toFixed(2) + 'x' + halfV_urad.toFixed(2);
  if (_accFluxCache[key] !== undefined) return _accFluxCache[key];
  var E1 = calcE1(K), En0 = n * E1;
  var H = 1 + K * K / 2, g2 = GAMMA_E * GAMMA_E;
  var N = N_PERIODS, sd = E_SPREAD, piNn = Math.PI * n * N;
  var bw = 7.0 / (n * N);
  var COEF = 1.744e14 * N * N * E_RING * E_RING * I_RING_A;
  function _grid(sig, m) {
    var v = [], w = [], s = 0, j, x, ww;
    for (j = 0; j < m; j++) { x = (-5 + 10 * j / (m - 1)) * sig; ww = Math.exp(-x * x / (2 * sig * sig)); v.push(x); w.push(ww); s += ww; }
    for (j = 0; j < m; j++) w[j] /= s;
    return { v: v, w: w };
  }
  var gr = _undGrids(K, n);
  var gd = _grid(sd, gr.nE);
  var gx = _grid(SIG_EXP, gr.nA);
  var gy = _grid(SIG_EYP, gr.nA);
  var halfRadH = halfH_urad * 1e-6;
  var halfRadV = halfV_urad * 1e-6;
  var nObs = 21;                                  // observation-angle grid (21x21) -- needed for n=3 <=2% (n=3 was 3.0% at 13x13)
  var dObsH = (2 * halfRadH) / (nObs - 1);
  var dObsV = (2 * halfRadV) / (nObs - 1);
  var dOmegaMrad2 = (dObsH * 1e3) * (dObsV * 1e3); // mrad^2 per pixel
  var nEgrid = 41;                                // energy grid around resonance
  var Elo = En0 * (1 - bw * 2.0), Ehi = En0 * (1 + bw * 0.5);
  var Egrid = new Array(nEgrid), dE = (Ehi - Elo) / (nEgrid - 1), ig;
  for (ig = 0; ig < nEgrid; ig++) Egrid[ig] = Elo + ig * dE;
  var pflux = new Array(nEgrid); for (ig = 0; ig < nEgrid; ig++) pflux[ig] = 0;
  var ox, oy, a, b, id, Ox, Oy, thx, thy, psix, psiy, psi2, gt, redA, amp, wab, En, wgt, xs, sc2;
  for (ox = 0; ox < nObs; ox++) {
    Ox = -halfRadH + ox * dObsH;
    for (oy = 0; oy < nObs; oy++) {
      Oy = -halfRadV + oy * dObsV;
      for (a = 0; a < gx.v.length; a++) {
        thx = gx.v[a];
        for (b = 0; b < gy.v.length; b++) {
          thy = gy.v[b];
          psix = Ox - thx; psiy = Oy - thy; psi2 = psix * psix + psiy * psiy;
          gt = GAMMA_E * Math.sqrt(psi2);
          redA = 1 / (1 + g2 * psi2 / H);
          amp = COEF * fLinFxy2(K, n, gt, Math.atan2(psiy, psix));
          wab = gx.w[a] * gy.w[b] * dOmegaMrad2;
          for (id = 0; id < gd.v.length; id++) {
            En = En0 * (1 + gd.v[id]) * (1 + gd.v[id]) * redA;
            wgt = amp * wab * gd.w[id];
            for (ig = 0; ig < nEgrid; ig++) {
              xs = piNn * (Egrid[ig] / En - 1);
              sc2 = (xs > -1e-10 && xs < 1e-10) ? 1 : Math.pow(Math.sin(xs) / xs, 2);
              pflux[ig] += wgt * sc2;
            }
          }
        }
      }
    }
  }
  var peak = 0, k; for (k = 0; k < nEgrid; k++) if (pflux[k] > peak) peak = pflux[k];
  _accFluxCache[key] = peak;
  return peak;
}
// Brilliance = on-axis flux density / (2pi Sigma_x Sigma_y)   [ph/s/mm^2/mrad^2/0.1%BW]
// (equivalent to Flux/(4pi^2 Sx Sx' Sy Sy') but evaluated via the energy-spread-
// suppressed on-axis flux density FD0, so high harmonics are not over-estimated.)
// Sx,Sy from photonSrc (diffraction limit + electron-beam size, both match SPECTRA).
// Validated vs spectra_solver: within <=17% up to n=11 (was up to 48x too high before).
function calcBrt(K,n){
  n=n||(state.harmonic||1);
  var FD0=onAxisFluxDensity(K,n);
  if(typeof photonSrc!=='function') return FD0*1e-4; // fallback
  var ps=photonSrc(n*calcE1(K));
  var sz=2*Math.PI*(ps.Sx*1e3)*(ps.Sy*1e3); // Sx,Sy m -> mm
  return sz>1e-30?FD0/sz:0;
}

// === Harmonic auto-selection ===
function solveGap(B0t){var lo=4,hi=30;for(var i=0;i<50;i++){var m=(lo+hi)/2;calcB0(m)>B0t?lo=m:hi=m;}return(lo+hi)/2;}
// Temporary emergency mitigation (v4.37.4): the synchronous fluxAcceptance() inside
// findHarmonics() was taking 18–34s per harmonic (~280s for 8 harmonics on cold cache),
// freezing the UI on every initial page load and on every WB-slit / target-energy
// change. Until the 3-layer fallback lands (precompute lookup → WebGPU compute →
// Web Worker), this revert restores the v4.36 fast path (onAxisFlux, sub-ms) so the
// page is responsive again. The harmonic panel still reads "Flux(WB)" and the WB
// readout line still reflects state.wbH/wbV, but the displayed flux values are the
// on-axis filament approximation rather than the WB-acceptance integral. Cached
// fluxAcceptance values, if already in _accFluxCache (e.g. from validation runs),
// are preferred over the fast path.
function findHarmonics(Et){
  var res=[],lc=LAMBDA_U/10;
  // WB-slit opening (mm) → half-angle aperture (µrad) at WBSLIT_DIST_M.
  var WBSLIT_DIST_M = 27.8;
  var wbH = (typeof state !== 'undefined' && state.wbH > 0) ? state.wbH : 1.2;
  var wbV = (typeof state !== 'undefined' && state.wbV > 0) ? state.wbV : 1.2;
  var halfH_urad = (wbH * 0.5) / WBSLIT_DIST_M * 1e3;
  var halfV_urad = (wbV * 0.5) / WBSLIT_DIST_M * 1e3;
  for(var n=1;n<=15;n+=2){
    var E1n=Et/n,K2=2*(0.9498*E_RING*E_RING/(lc*E1n)-1);
    if(K2<0.01||K2>25)continue;var K=Math.sqrt(K2),B0=K/(0.9341*lc),gap=solveGap(B0);
    if(gap<4.5||gap>30)continue;
    var cacheKey = K.toFixed(4) + '_' + n + '_' + halfH_urad.toFixed(2) + 'x' + halfV_urad.toFixed(2);
    var flux;
    if (typeof _accFluxCache !== 'undefined' && _accFluxCache[cacheKey] !== undefined) {
      flux = _accFluxCache[cacheKey];
    } else {
      // SPECTRA-acceptance lookup first (Layer 1, instant once table fetched).
      // Restores the physically correct partial flux that the v4.37.4
      // emergency revert dropped: the Kim filament onAxisFlux fallback is
      // zero-emittance/zero-spread and overestimates the WB-acceptance flux
      // by 2.0x (n=3) to 3.2x (n=7) at 10 keV, AND mis-ranks harmonics
      // (picks n=7 as max-flux when the SPECTRA convolution says n=3/5).
      // That wrong seed propagated into sourceFlux -> photonFlux/propagateBeam
      // (flux decomposition 2026-06-10). Falls back to onAxisFlux until the
      // lookup table loads, or for non-default WB apertures (lookup returns
      // null outside +/-2% of the tabulated 21.6 urad half-angle).
      var _lkp = (typeof fluxAcceptanceLookup === 'function')
               ? fluxAcceptanceLookup(K, n, halfH_urad, halfV_urad) : null;
      if (_lkp !== null && _lkp !== undefined) {
        flux = _lkp;
        if (typeof _accFluxCache !== 'undefined') _accFluxCache[cacheKey] = _lkp;
      } else {
        flux = onAxisFlux(K, n);  // fast fallback (sub-ms) — see comment above
      }
    }
    res.push({n:n,K:K,B0:B0,gap:gap,E1:E1n,flux:flux,Fn:coupFn(K,n)});
  }return res.sort(function(a,b){return a.n-b.n;});
}
// Pick the best harmonic for target energy Et: returns the first (lowest-n) entry from findHarmonics, or null.
function selectBest(Et){var h=findHarmonics(Et);return h.length?h[0]:null;}

// === 3-layer fallback for harmonic flux (Phase 4) ===
// Layer 1: lookup table (instant, default WB only)            -- 04_flux_acceptance_lookup.js
// Layer 2: WebGPU compute shader (~1-2 s, custom WB if GPU)   -- 03_webgpu_flux_acceptance.js
// Layer 3: Web Worker CPU (~5-30 s background, no GPU)        -- 05_flux_acceptance_worker_host.js
//
// All three layers return the same physical quantity: peak partial flux
// through the WB-slit angular acceptance, in ph/s/0.1%BW.
//
// findHarmonicsAsync returns IMMEDIATELY with the onAxisFlux fast-path so the
// caller can render a panel without blocking; refined harmonic flux values
// are pushed asynchronously via onRefined(harms, layerName) — once after the
// lookup pass (Layer 1), once after the GPU pass (Layer 2), and once after the
// Worker pass (Layer 3) for any harmonics still unresolved. The caller is
// expected to re-render the table on each callback. If Layer 1 satisfies all
// harmonics (default WB on every entry), Layers 2 and 3 are skipped.
//
// onRefined signature: function(harms, layerName)
//   harms      -- the same array returned synchronously, with x.flux updated
//                 in place where the layer produced a value
//   layerName  -- 'lookup' | 'gpu' | 'worker' (which layer just finished)
// Result cache: same (Et, halfH, halfV) returns the cached harms array +
// fires onRefined immediately with the last layer that produced it. This
// avoids re-running GPU / lookup / worker when only the user-selected
// harmonic n changes (state.gap moves but Et/halfH/halfV stay the same,
// so findHarmonics() returns the same array of n=1..15 entries).
// Cache size bounded to 64 entries (LRU); cleared by user changing wbH/wbV
// or target energy, both of which produce a new key.
var _harmAsyncCache = {};
// Insertion-order key list backing the async-harmonic cache for LRU eviction at the 64-entry cap.
var _harmAsyncCacheOrder = [];
var _HARM_CACHE_MAX = 64;
// Build the async-harmonic cache key by joining Et(4dp) and halfH/halfV urad (3dp) with pipes.
function _harmCacheKey(Et, halfH_urad, halfV_urad) {
  return Et.toFixed(4) + '|' + halfH_urad.toFixed(3) + '|' + halfV_urad.toFixed(3);
}
// Store a deep copy of the harmonics array plus its layer tag and timestamp, evicting the oldest past the cap.
function _harmCachePut(key, harms, layer) {
  if (_harmAsyncCache[key] === undefined) {
    _harmAsyncCacheOrder.push(key);
    if (_harmAsyncCacheOrder.length > _HARM_CACHE_MAX) {
      var evict = _harmAsyncCacheOrder.shift();
      delete _harmAsyncCache[evict];
    }
  }
  _harmAsyncCache[key] = {
    // store a deep-enough copy so later in-place mutations don't poison cache
    harms: harms.map(function(h){return {n:h.n,K:h.K,B0:h.B0,gap:h.gap,E1:h.E1,flux:h.flux,Fn:h.Fn};}),
    layer: layer,
    ts: Date.now()
  };
}
// Return harmonics synchronously (onAxisFlux fast path) then refine flux via GPU/lookup/worker layers through onRefined; cached.
function findHarmonicsAsync(Et, halfH_urad, halfV_urad, onRefined) {
  // Cache fast-path: same (Et, halfH, halfV) -> return cached harms + replay
  // the cached layer tag via onRefined on the next microtask. Skips all
  // GPU/lookup/worker work when only state.gap (active harmonic) changed.
  var _cacheKey = _harmCacheKey(Et, halfH_urad, halfV_urad);
  var _cached = _harmAsyncCache[_cacheKey];
  if (_cached) {
    var _cachedHarmsCopy = _cached.harms.map(function(h){return {n:h.n,K:h.K,B0:h.B0,gap:h.gap,E1:h.E1,flux:h.flux,Fn:h.Fn};});
    if (typeof onRefined === 'function' && _cached.layer) {
      var _cachedLayer = _cached.layer;
      setTimeout(function() {
        try { onRefined(_cachedHarmsCopy, _cachedLayer); } catch (e) { /* swallow */ }
      }, 0);
    }
    return _cachedHarmsCopy;
  }
  // 1. Synchronous: onAxisFlux fast-path (sub-ms) so the caller can render now.
  var harms = findHarmonics(Et);
  if (typeof onRefined !== 'function') return harms;

  // Per-harmonic tag: false until a higher-fidelity layer has filled it in.
  var resolved = new Array(harms.length);
  for (var i = 0; i < harms.length; i++) resolved[i] = false;

  // Lookup pass (now Layer 2, runs AFTER GPU). Synchronous if the table is
  // already in memory; if not, wait up to 2 s for the fetch via watchdog.
  function _runLookupPass() {
    if (typeof fluxAcceptanceLookup !== 'function') return false;
    var anyHit = false;
    for (var j = 0; j < harms.length; j++) {
      if (resolved[j]) continue;
      var x = harms[j];
      var v = fluxAcceptanceLookup(x.K, x.n, halfH_urad, halfV_urad);
      if (v !== null && v !== undefined && isFinite(v)) {
        x.flux = v;
        resolved[j] = true;
        anyHit = true;
      }
    }
    return anyHit;
  }

  // GPU pass (Layer 1, runs first). For any harmonic still unresolved, call
  // fluxAcceptanceGPU sequentially (the WGSL kernel itself splits the outer
  // (a,b) loop across 8 dispatches under the Windows 2 s TDR; parallel GPU
  // calls would still serialise on the queue, and serialising here keeps
  // cache locality across the (K, n) sweep).
  //
  // Per-call single-shot flag so each findHarmonicsAsync invocation owns its
  // own chain (no module-scope leakage between calls).
  var _gpuStarted = false;
  function _startGpuOnce() {
    if (_gpuStarted) return;
    _gpuStarted = true;
    _runGpuPass();
  }
  function _checkCanGpu() {
    return (typeof fluxAcceptanceGPU === 'function') &&
           (typeof window !== 'undefined') && window._GPU &&
           window._GPU.supported === true &&
           window._GPU.device &&
           !(window._GPU.adapter_info && window._GPU.adapter_info.isFallbackAdapter);
  }
  // After lookup/worker resolves, keep polling for GPU readiness for up to
  // ~5 s. If GPU detection completes asynchronously after the initial pass
  // (common on first page load — WebGPU adapter request is async), upgrade
  // the displayed flux to the GPU-computed value once the device is ready.
  var _gpuUpgradeRetries = 10;
  function _maybeUpgradeToGpu() {
    if (_checkCanGpu()) {
      // Reset resolved[] so the GPU pass overwrites every harmonic with the
      // higher-fidelity value (lookup/worker hits are replaced by GPU).
      for (var j = 0; j < resolved.length; j++) resolved[j] = false;
      _runGpuPass();
      return;
    }
    if (_gpuUpgradeRetries-- > 0) {
      setTimeout(_maybeUpgradeToGpu, 500);
    }
  }
  function _runGpuPass() {
    var anyPending = false;
    for (var j = 0; j < harms.length; j++) if (!resolved[j]) { anyPending = true; break; }
    if (!anyPending) {
      // Already fully resolved by GPU; re-render with [gpu] tag and stop.
      return;
    }

    var canGpu = _checkCanGpu();
    if (!canGpu) {
      _runLookupStage();
      // GPU not ready now; schedule a polling re-try so a late-completing
      // WebGPU probe can upgrade lookup/worker values to [gpu] values.
      setTimeout(_maybeUpgradeToGpu, 500);
      return;
    }

    var idx = 0;
    var anyGpuHit = false;
    function _next() {
      while (idx < harms.length && resolved[idx]) idx++;
      if (idx >= harms.length) {
        if (anyGpuHit) {
          _harmCachePut(_cacheKey, harms, 'gpu');
          try { onRefined(harms, 'gpu'); } catch (e) { /* swallow */ }
        }
        _runLookupStage();
        return;
      }
      var jLocal = idx;
      var x = harms[jLocal];
      fluxAcceptanceGPU(x.K, x.n, halfH_urad, halfV_urad).then(function (v) {
        if (isFinite(v) && v > 0) { x.flux = v; resolved[jLocal] = true; anyGpuHit = true; }
        idx = jLocal + 1;
        _next();
      }, function (err) {
        // GPU failure for this harmonic — leave it pending and continue.
        idx = jLocal + 1;
        _next();
      });
    }
    _next();
  }

  // Lookup STAGE wrapper: tries _runLookupPass right away; if the table is
  // still loading, waits on fluxAcceptanceLookupReady() with a 2 s watchdog
  // (v4.37.15 guard, now applied to the lookup stage inside the chain).
  function _runLookupStage() {
    var hit = _runLookupPass();
    if (hit) {
      _harmCachePut(_cacheKey, harms, 'lookup');
      try { onRefined(harms, 'lookup'); } catch (e) { /* swallow */ }
    }
    var anyPending = false;
    for (var j = 0; j < harms.length; j++) if (!resolved[j]) { anyPending = true; break; }
    if (!anyPending) { _runWorkerPass(); return; }

    if (typeof fluxAcceptanceLookupReady === 'function') {
      var _workerStarted = false;
      function _startWorkerOnce() {
        if (_workerStarted) return;
        _workerStarted = true;
        _runWorkerPass();
      }
      var _readyPromise;
      try { _readyPromise = fluxAcceptanceLookupReady(); }
      catch (e) { _readyPromise = null; }
      if (_readyPromise && typeof _readyPromise.then === 'function') {
        _readyPromise.then(function (ok) {
          if (ok) {
            var hit2 = _runLookupPass();
            if (hit2) {
              _harmCachePut(_cacheKey, harms, 'lookup');
              try { onRefined(harms, 'lookup'); } catch (e) { /* swallow */ }
            }
          }
          _startWorkerOnce();
        }, function () { _startWorkerOnce(); });
        // 2 s watchdog: if the ready-promise has not settled by now, advance
        // to Layer 3 anyway.
        setTimeout(_startWorkerOnce, 2000);
      } else {
        _startWorkerOnce();
      }
    } else {
      _runWorkerPass();
    }
  }

  // Worker pass (Layer 3). Catches the no-GPU + no-lookup cases.
  // Batched in one postMessage to avoid 8 round-trips.
  function _runWorkerPass() {
    var pending = [];
    var pendingIdx = [];
    for (var j = 0; j < harms.length; j++) {
      if (!resolved[j]) { pending.push({ K: harms[j].K, n: harms[j].n }); pendingIdx.push(j); }
    }
    if (pending.length === 0) return;
    if (typeof fluxAcceptanceWorkerHarmonics !== 'function') return;
    fluxAcceptanceWorkerHarmonics(pending, halfH_urad, halfV_urad).then(function (results) {
      if (!results || !results.length) return;
      var anyHit = false;
      for (var k = 0; k < results.length; k++) {
        var jIdx = pendingIdx[k];
        var v = results[k].flux;
        if (isFinite(v) && v > 0) { harms[jIdx].flux = v; resolved[jIdx] = true; anyHit = true; }
      }
      if (anyHit) {
        _harmCachePut(_cacheKey, harms, 'worker');
        try { onRefined(harms, 'worker'); } catch (e) { /* swallow */ }
      }
    }, function (err) {
      // Worker failed — Layer 3 was the last fallback; the onAxisFlux
      // fast-path values stay visible.
    });
  }

  // Kick off the async chain after the sync return so the caller's [fast]
  // render commits first.
  setTimeout(_startGpuOnce, 0);

  return harms;
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof besselJ!=="undefined")globalThis.besselJ=besselJ;
if(typeof calcB0!=="undefined")globalThis.calcB0=calcB0;
if(typeof calcBrt!=="undefined")globalThis.calcBrt=calcBrt;
if(typeof calcE1!=="undefined")globalThis.calcE1=calcE1;
if(typeof calcK!=="undefined")globalThis.calcK=calcK;
if(typeof calcPtotal!=="undefined")globalThis.calcPtotal=calcPtotal;
if(typeof coupFn!=="undefined")globalThis.coupFn=coupFn;
if(typeof findHarmonics!=="undefined")globalThis.findHarmonics=findHarmonics;
if(typeof findHarmonicsAsync!=="undefined")globalThis.findHarmonicsAsync=findHarmonicsAsync;
if(typeof onAxisFlux!=="undefined")globalThis.onAxisFlux=onAxisFlux;
if(typeof onAxisFluxDensity!=="undefined")globalThis.onAxisFluxDensity=onAxisFluxDensity;
if(typeof eSpreadAngleSupp!=="undefined")globalThis.eSpreadAngleSupp=eSpreadAngleSupp;
if(typeof fLinFxy2!=="undefined")globalThis.fLinFxy2=fLinFxy2;
if(typeof undulatorSpectrum!=="undefined")globalThis.undulatorSpectrum=undulatorSpectrum;
if(typeof resonanceEnergy!=="undefined")globalThis.resonanceEnergy=resonanceEnergy;
if(typeof selectBest!=="undefined")globalThis.selectBest=selectBest;
if(typeof solveGap!=="undefined")globalThis.solveGap=solveGap;
if(typeof undulatorSinc2!=="undefined")globalThis.undulatorSinc2=undulatorSinc2;
if(typeof fluxAcceptance!=="undefined")globalThis.fluxAcceptance=fluxAcceptance;
