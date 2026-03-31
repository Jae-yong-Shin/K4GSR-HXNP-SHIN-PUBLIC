'use strict';
// ===== optics/01_undulator.js — IVU Physics (validated SRCalc) =====
// @module optics/01_undulator
// @exports besselJ, calcB0, calcBrt, calcE1, calcK, calcPtotal, coupFn, findHarmonics, onAxisFlux, resonanceEnergy, selectBest, solveGap, undulatorSinc2
// Extracted from 02_physics.js (DDD Phase 2)

function calcB0(g){var r=g/LAMBDA_U;return HALB_A*Math.exp(HALB_B*r+HALB_C*r*r);}
function calcK(B0){return 0.9341*B0*(LAMBDA_U/10);}
function calcE1(K){return 0.9498*E_RING*E_RING/((LAMBDA_U/10)*(1+K*K/2));}
function calcPtotal(B0){return 633*E_RING*E_RING*B0*B0*L_UND*I_RING_A;} // Watts
// Energy-angle coupling (Kim 1989): resonance energy at observation angle theta
// E_res(theta) = n*E1 / (1 + gamma^2*theta^2/(1+K^2/2))
function resonanceEnergy(E1,K,theta,n){n=n||1;return n*E1/(1+GAMMA_E*GAMMA_E*theta*theta/(1+K*K/2));}
// sinc^2 spectral function: exact undulator spectral shape (Spectra convention)
function undulatorSinc2(E,Eres){var x=Math.PI*N_PERIODS*(E/Eres-1);return Math.abs(x)<1e-10?1:Math.pow(Math.sin(x)/x,2);}

function besselJ(n,x){if(Math.abs(x)<1e-10)return n===0?1:0;var s=0,fM=1,fN=1;for(var i=1;i<=n;i++)fN*=i;for(var m=0;m<30;m++){if(m>0){fM*=m;fN*=(m+n);}var t=Math.pow(-1,m)/fM/fN*Math.pow(x/2,2*m+n);s+=t;if(Math.abs(t)<1e-15*Math.abs(s||1))break;}return s;}
function coupFn(K,n){var xi=K*K/(4+2*K*K);var j1=besselJ(Math.floor((n-1)/2),n*xi),j2=besselJ(Math.floor((n+1)/2),n*xi);var JJ=j1-j2;return n*n*K*K*JJ*JJ/Math.pow(1+K*K/2,2);}
function onAxisFlux(K,n){return 1.431e14*N_PERIODS*I_RING_A*coupFn(K,n);}
// Brilliance = Flux / (4pi^2 Sigma_x Sigma_x' Sigma_y Sigma_y')  [ph/s/0.1%BW/mm^2/mrad^2]
// Uses photonSrc() for convolved electron+photon beam sizes (Tanaka-Kitamura)
function calcBrt(K,n){
  n=n||(state.harmonic||1);
  var E1=calcE1(K),flux=onAxisFlux(K,n);
  if(typeof photonSrc!=='function') return flux*1e-4; // fallback
  var ps=photonSrc(n*E1);
  // Sx,Sy in m -> mm; Sxp,Syp in rad -> mrad
  var vol=4*Math.PI*Math.PI*(ps.Sx*1e3)*(ps.Sxp*1e3)*(ps.Sy*1e3)*(ps.Syp*1e3);
  return vol>1e-30?flux/vol:0;
}

// === Harmonic auto-selection ===
function solveGap(B0t){var lo=4,hi=30;for(var i=0;i<50;i++){var m=(lo+hi)/2;calcB0(m)>B0t?lo=m:hi=m;}return(lo+hi)/2;}
function findHarmonics(Et){
  var res=[],lc=LAMBDA_U/10;
  for(var n=1;n<=15;n+=2){
    var E1n=Et/n,K2=2*(0.9498*E_RING*E_RING/(lc*E1n)-1);
    if(K2<0.01||K2>25)continue;var K=Math.sqrt(K2),B0=K/(0.9341*lc),gap=solveGap(B0);
    if(gap<4.5||gap>30)continue;
    res.push({n:n,K:K,B0:B0,gap:gap,E1:E1n,flux:onAxisFlux(K,n),Fn:coupFn(K,n)});
  }return res.sort(function(a,b){return a.n-b.n;});
}
function selectBest(Et){var h=findHarmonics(Et);return h.length?h[0]:null;}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof besselJ!=="undefined")globalThis.besselJ=besselJ;
if(typeof calcB0!=="undefined")globalThis.calcB0=calcB0;
if(typeof calcBrt!=="undefined")globalThis.calcBrt=calcBrt;
if(typeof calcE1!=="undefined")globalThis.calcE1=calcE1;
if(typeof calcK!=="undefined")globalThis.calcK=calcK;
if(typeof calcPtotal!=="undefined")globalThis.calcPtotal=calcPtotal;
if(typeof coupFn!=="undefined")globalThis.coupFn=coupFn;
if(typeof findHarmonics!=="undefined")globalThis.findHarmonics=findHarmonics;
if(typeof onAxisFlux!=="undefined")globalThis.onAxisFlux=onAxisFlux;
if(typeof resonanceEnergy!=="undefined")globalThis.resonanceEnergy=resonanceEnergy;
if(typeof selectBest!=="undefined")globalThis.selectBest=selectBest;
if(typeof solveGap!=="undefined")globalThis.solveGap=solveGap;
if(typeof undulatorSinc2!=="undefined")globalThis.undulatorSinc2=undulatorSinc2;
