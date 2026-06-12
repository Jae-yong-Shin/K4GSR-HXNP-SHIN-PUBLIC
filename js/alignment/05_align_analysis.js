'use strict';
// ===== alignment/05_align_analysis.js -- Alignment Analysis Tools + Engine =====
// @module alignment/05_align_analysis
// @exports _aat, _aatBuild, _aatCalcDeriv, _aatCalcSmooth, _aatCalcStats, _aatCopy, _aatDrawCanvas, _aatDrawStats, _aatDrawTable, _aatFWxM, _aatFWxMcoord, _aatFitBoxErf, _aatFitErf, _aatFitPoly, _aatRefresh, ...
// Extracted from 14_v435_final.js (DDD Phase 5e)
// Data Analysis Tool UI (toggleAlignAnalysis, erf fit, box-erf fit, polynomial fit,
//   statistics, FWHM/FW25%/FW75%, centroid, multi-series canvas rendering)
// Analysis Engine (sgSmooth, numDeriv, solveLinear, gaussianFit, lorentzianFit,
//   analyzeAlignScan dispatcher, alignCentroid, alignGaussianFit, alignHalfBeam,
//   alignRockingCurve, _prevRunMirrorAlign override)
// Dependencies: log, state, _lastAlignResult, erf_a (from physics/),
//   _makePopupResizable, MIRROR_ALIGN_SEQ, runMirrorAlign

// ===================================================================
// Data Analysis Tool -- comprehensive interactive data analysis UI
// Inspired by Shadow4 plot tools (histo1, plotxy, statistics)
// ===================================================================
(function(){

var _aat={raw:null,show:{raw:true,smooth:false,deriv:false,fit:false},
  logY:false,sgHW:2,fitType:'gauss',fitResult:null,smoothed:null,
  derivative:null,stats:null,overlay:null};

// -- Entry point --
window.toggleAlignAnalysis=function(){
  if(_aat.overlay){_aat.overlay.remove();_aat.overlay=null;return;}
  var res=window._lastAlignResult;
  if(!res||!res.positions||!res.signals||res.positions.length<3){
    log('warn','No scan data for analysis');return;
  }
  _aat.raw={pos:res.positions.slice(),sig:res.signals.slice(),
    method:res.method||'',beamPos:res.beamPos?res.beamPos.slice():null};
  _aat.activeSig=_aat.raw.sig.slice();
  _aat.yLabel='Signal';
  _aat.fitResult=null;_aat.smoothed=null;_aat.derivative=null;
  _aat.show={raw:true,smooth:false,deriv:false,fit:false};
  _aat.logY=false;
  _aatBuild();_aatRefresh();
};

// -- Build UI --
function _aatBuild(){
  var ov=document.createElement('div');ov.id='aatOverlay';
  ov.style.cssText='position:fixed;top:0;left:0;width:100%;height:100%;'
    +'background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center';
  var pop=document.createElement('div');
  pop.style.cssText='background:var(--bg,#0d1117);border:1px solid var(--b1,#21262d);'
    +'border-radius:8px;padding:14px 18px;width:480px;max-width:92vw;max-height:90vh;'
    +'overflow:auto;box-shadow:0 12px 40px rgba(0,0,0,0.5);color:var(--t1,#e6edf3);font-family:var(--mn,monospace);zoom:var(--ui-zoom,1.8)';
  var h='';
  // Title bar
  h+='<div style="display:flex;align-items:center;margin-bottom:8px">'
    +'<span style="font-size:13px;font-weight:600;flex:1">Data Analysis Tool</span>'
    +'<span style="font-size:9px;color:var(--t3,#8b949e);margin-right:12px">'
    +_aat.raw.pos.length+' pts | '+(_aat.raw.method||'scan')+'</span>'
    +'<button id="aatClose" style="background:none;border:none;color:var(--t3);font-size:18px;cursor:pointer;padding:2px 6px">&times;</button></div>';
  // Toolbar row 0: Data source selector (Intensity vs Centroid)
  var _hasBeamPos=(_aat.raw.beamPos&&_aat.raw.beamPos.length>0);
  if(_hasBeamPos){
    h+='<div style="display:flex;gap:4px;align-items:center;margin-bottom:5px">'
      +'<span style="font-size:8px;color:var(--t3);min-width:46px">Data:</span>'
      +'<select id="aatDataSrc" style="font-size:9px;padding:2px 4px;background:var(--s2,#161b22);color:var(--t1);border:1px solid var(--b1);border-radius:3px">'
      +'<option value="intensity">Intensity (signal)</option>'
      +'<option value="centroid">Centroid (beam position)</option></select></div>';
  }
  // Toolbar row 1: Display toggles + Scale
  h+='<div style="display:flex;gap:4px;align-items:center;margin-bottom:5px;flex-wrap:wrap">'
    +'<span style="font-size:8px;color:var(--t3);min-width:46px">Display:</span>'
    +_aatTBtn('aatRaw','Raw',true)+_aatTBtn('aatSmooth','Smooth',false)
    +_aatTBtn('aatDeriv','d/dx',false)+_aatTBtn('aatFit','Fit',false)
    +'<span style="margin-left:16px;font-size:8px;color:var(--t3)">Scale:</span>'
    +_aatTBtn('aatLin','Linear',true)+_aatTBtn('aatLog','Log',false)+'</div>';
  // Toolbar row 2: Smooth + Fit controls
  h+='<div style="display:flex;gap:4px;align-items:center;margin-bottom:8px;flex-wrap:wrap">'
    +'<span style="font-size:8px;color:var(--t3);min-width:46px">Smooth:</span>'
    +'<select id="aatSgWin" style="font-size:9px;padding:2px 4px;background:var(--s2,#161b22);color:var(--t1);border:1px solid var(--b1);border-radius:3px">'
    +'<option value="2">SG-5</option><option value="3" selected>SG-7</option><option value="4">SG-9</option><option value="5">SG-11</option></select>'
    +'<span style="margin-left:16px;font-size:8px;color:var(--t3)">Fit:</span>'
    +'<select id="aatFitType" style="font-size:9px;padding:2px 4px;background:var(--s2);color:var(--t1);border:1px solid var(--b1);border-radius:3px">'
    +'<option value="gauss">Gaussian (LM)</option><option value="lorentz">Lorentzian (LM)</option>'
    +'<option value="erf">erf / Sigmoid (LM)</option><option value="boxerf">Box-erf (WB half-cut)</option>'
    +'<option value="poly3">Polynomial-3</option><option value="poly5">Polynomial-5</option></select>'
    +'<button id="aatFitBtn" style="font-size:9px;padding:3px 14px;background:var(--ac,#58a6ff);color:#000;border:none;border-radius:3px;cursor:pointer;font-weight:600">Fit!</button>'
    +'<span style="flex:1"></span>'
    +'<button id="aatCopyBtn" style="font-size:9px;padding:3px 10px;background:var(--s2);color:var(--t3);border:1px solid var(--b1);border-radius:3px;cursor:pointer">Copy TSV</button></div>';
  // Main area: Canvas + Stats
  h+='<div style="display:flex;gap:10px">'
    +'<div style="flex:1;min-width:0">'
    +'<canvas id="aatCanvas" width="600" height="340" style="width:100%;height:340px;border:1px solid var(--b1);border-radius:4px;background:var(--s0,#080c14)"></canvas></div>'
    +'<div id="aatStats" style="width:200px;min-width:200px;font-size:9px;line-height:1.7;'
    +'overflow-y:auto;max-height:340px"></div></div>';
  // Data table (collapsible)
  h+='<details style="margin-top:8px">'
    +'<summary style="font-size:9px;color:var(--t3);cursor:pointer;user-select:none">Data Table</summary>'
    +'<div id="aatTable" style="max-height:200px;overflow-y:auto;margin-top:4px"></div></details>';
  pop.setAttribute('data-popup-box','1');
  pop.innerHTML=h;ov.appendChild(pop);document.body.appendChild(ov);
  // Style title bar for drag-to-move
  var aatHdr=pop.firstElementChild;
  if(aatHdr){aatHdr.style.cssText+= ';cursor:move;user-select:none;background:var(--s1,#151f2e);border-bottom:1px solid var(--b0);border-radius:8px 8px 0 0;padding:8px 18px';}
  window._makePopupResizable(pop, {minWidth:500, dragEl:aatHdr});
  // ResizeObserver: auto-resize canvas when popup size changes
  if(typeof ResizeObserver!=='undefined'){
    var _aatLastW=0,_aatLastH=0;
    var aatRO=new ResizeObserver(function(){
      var cv2=document.getElementById('aatCanvas');if(!cv2)return;
      var cw=cv2.clientWidth,ch=cv2.clientHeight;
      if(cw>0&&ch>0&&(cw!==_aatLastW||ch!==_aatLastH)){
        _aatLastW=cw;_aatLastH=ch;
        _aatRefresh();
      }
    });
    aatRO.observe(pop);
  }
  _aat.overlay=ov;
  // Events
  document.getElementById('aatClose').onclick=function(){ov.remove();_aat.overlay=null;};
  ov.addEventListener('mousedown',function(e){if(e.target===ov){ov.remove();_aat.overlay=null;}});
  document.getElementById('aatRaw').onclick=function(){_aat.show.raw=!_aat.show.raw;_aatTC(this,_aat.show.raw);_aatRefresh();};
  document.getElementById('aatSmooth').onclick=function(){_aat.show.smooth=!_aat.show.smooth;_aatTC(this,_aat.show.smooth);_aatRefresh();};
  document.getElementById('aatDeriv').onclick=function(){_aat.show.deriv=!_aat.show.deriv;_aatTC(this,_aat.show.deriv);_aatRefresh();};
  document.getElementById('aatFit').onclick=function(){_aat.show.fit=!_aat.show.fit;_aatTC(this,_aat.show.fit);_aatRefresh();};
  document.getElementById('aatLin').onclick=function(){_aat.logY=false;_aatTC(this,true);_aatTC(document.getElementById('aatLog'),false);_aatRefresh();};
  document.getElementById('aatLog').onclick=function(){_aat.logY=true;_aatTC(this,true);_aatTC(document.getElementById('aatLin'),false);_aatRefresh();};
  document.getElementById('aatSgWin').onchange=function(){_aat.sgHW=parseInt(this.value);_aat.smoothed=null;_aat.derivative=null;_aatRefresh();};
  document.getElementById('aatFitBtn').onclick=function(){
    _aat.fitType=document.getElementById('aatFitType').value;
    _aatRunFit();_aat.show.fit=true;_aatTC(document.getElementById('aatFit'),true);_aatRefresh();
  };
  document.getElementById('aatCopyBtn').onclick=_aatCopy;
  var _srcSel=document.getElementById('aatDataSrc');
  if(_srcSel) _srcSel.onchange=function(){
    if(this.value==='centroid'&&_aat.raw.beamPos){
      _aat.activeSig=_aat.raw.beamPos.slice();
      _aat.yLabel='Centroid (mm)';
    } else {
      _aat.activeSig=_aat.raw.sig.slice();
      _aat.yLabel='Signal';
    }
    _aat.smoothed=null;_aat.derivative=null;_aat.fitResult=null;
    _aatRefresh();
  };
}
function _aatTBtn(id,label,on){
  var bg=on?'background:var(--ac,#58a6ff);color:#000':'background:var(--s2,#161b22);color:var(--t3,#8b949e)';
  return '<button id="'+id+'" style="font-size:9px;padding:3px 10px;border:1px solid var(--b1,#21262d);border-radius:3px;cursor:pointer;'+bg+'">'+label+'</button>';
}
function _aatTC(el,on){if(!el)return;el.style.background=on?'var(--ac,#58a6ff)':'var(--s2,#161b22)';el.style.color=on?'#000':'var(--t3,#8b949e)';}

// -- Refresh all --
function _aatRefresh(){_aatCalcSmooth();_aatCalcDeriv();_aatCalcStats();_aatDrawCanvas();_aatDrawStats();_aatDrawTable();}

// -- Smoothing --
function _aatCalcSmooth(){
  if(_aat.smoothed)return;
  _aat.smoothed=window.sgSmooth?window.sgSmooth(_aat.activeSig||_aat.raw.sig,_aat.sgHW):(_aat.activeSig||_aat.raw.sig).slice();
}

// -- Derivative --
function _aatCalcDeriv(){
  if(_aat.derivative)return;
  var src=_aat.show.smooth?_aat.smoothed:(_aat.activeSig||_aat.raw.sig);
  _aat.derivative=window.numDeriv?window.numDeriv(_aat.raw.pos,src,!_aat.show.smooth):null;
}

// -- Fitting --
function _aatRunFit(){
  var xs=_aat.raw.pos;
  var ys=_aat.show.smooth?_aat.smoothed:(_aat.activeSig||_aat.raw.sig);
  var tp=_aat.fitType;
  _aat.fitResult=null;
  if(tp==='gauss'&&window.gaussianFit){
    _aat.fitResult=window.gaussianFit(xs,ys,{smooth:false});
    if(_aat.fitResult)_aat.fitResult.type='Gaussian (LM)';
  }else if(tp==='lorentz'&&window.lorentzianFit){
    _aat.fitResult=window.lorentzianFit(xs,ys,{smooth:false});
    if(_aat.fitResult)_aat.fitResult.type='Lorentzian (LM)';
  }else if(tp==='erf'){
    _aat.fitResult=_aatFitErf(xs,ys);
    if(_aat.fitResult)_aat.fitResult.type='erf / Sigmoid (LM)';
  }else if(tp==='poly3'){
    _aat.fitResult=_aatFitPoly(xs,ys,3);
    if(_aat.fitResult)_aat.fitResult.type='Polynomial-3';
  }else if(tp==='poly5'){
    _aat.fitResult=_aatFitPoly(xs,ys,5);
    if(_aat.fitResult)_aat.fitResult.type='Polynomial-5';
  }else if(tp==='boxerf'){
    _aat.fitResult=_aatFitBoxErf(xs,ys);
    if(_aat.fitResult)_aat.fitResult.type='Box-erf (WB)';
  }
}

// erf fit: S(x) = A + B * erf((x-c)/(sig*sqrt2)), LM optimization
function _aatFitErf(xs,ys){
  var n=xs.length;if(n<4)return null;
  var sorted=ys.slice().sort(function(a,b){return a-b;});
  var lo=sorted[Math.floor(n*0.1)],hi=sorted[Math.floor(n*0.9)];
  var A=(lo+hi)/2,B=(hi-lo)/2;if(Math.abs(B)<1e-30)return null;
  var sign=(ys[n-1]>ys[0])?1:-1;
  // center from derivative peak
  var dy=window.numDeriv?window.numDeriv(xs,ys,true):null;
  var center=xs[Math.floor(n/2)];
  if(dy){var mxD=0,iM=0;for(var i=0;i<dy.length;i++){var av=Math.abs(dy[i]);if(av>mxD){mxD=av;iM=i;}}center=xs[iM];}
  var sigma=(xs[n-1]-xs[0])/10;
  var p=[A,B*sign,center,sigma],lam=0.01;
  function model(x,pp){return pp[0]+pp[1]*erf_a((x-pp[2])/(Math.abs(pp[3])*1.4142));}
  for(var iter=0;iter<30;iter++){
    var J=[],r=[];var chi=0;
    for(var i2=0;i2<n;i2++){var m=model(xs[i2],p);r.push(ys[i2]-m);chi+=(ys[i2]-m)*(ys[i2]-m);
      var row=[];for(var k=0;k<4;k++){var dp=p.slice();var hh=Math.max(Math.abs(p[k])*1e-5,1e-10);dp[k]+=hh;row.push((model(xs[i2],dp)-m)/hh);}J.push(row);}
    var JtJ=[],Jtr=[];
    for(var k2=0;k2<4;k2++){JtJ[k2]=[];var s=0;for(var i3=0;i3<n;i3++)s+=J[i3][k2]*r[i3];Jtr[k2]=s;
      for(var j=0;j<4;j++){var ss=0;for(var i4=0;i4<n;i4++)ss+=J[i4][k2]*J[i4][j];JtJ[k2][j]=ss;}JtJ[k2][k2]+=lam*(JtJ[k2][k2]+1e-6);}
    var dp2=window.solveLinear?window.solveLinear(JtJ,Jtr):null;if(!dp2)break;
    var pN=p.map(function(v,i5){return v+dp2[i5];});
    var chi2=0;for(var i6=0;i6<n;i6++){var d=ys[i6]-model(xs[i6],pN);chi2+=d*d;}
    if(chi2<chi){p=pN;lam*=0.3;}else{lam*=5;if(lam>1e8)break;}
  }
  var ssRes=0,ssTot=0,yMean=0;
  for(var i7=0;i7<n;i7++)yMean+=ys[i7];yMean/=n;
  for(var i8=0;i8<n;i8++){var m2=model(xs[i8],p);ssRes+=(ys[i8]-m2)*(ys[i8]-m2);ssTot+=(ys[i8]-yMean)*(ys[i8]-yMean);}
  // Dense fit curve (10x data points) for smooth display
  var nDense=Math.max(n*10,200),fitCurve=new Array(nDense),fitCurveX=new Array(nDense);
  var xSpan=xs[n-1]-xs[0];
  for(var i9=0;i9<nDense;i9++){var xd=xs[0]+xSpan*i9/(nDense-1);fitCurveX[i9]=xd;fitCurve[i9]=model(xd,p);}
  return{amplitude:p[1],center:p[2],sigma:Math.abs(p[3]),fwhm:2.355*Math.abs(p[3]),background:p[0],
    r2:ssTot>0?1-ssRes/ssTot:0,fitCurve:fitCurve,fitCurveX:fitCurveX};
}

// Box-erf fit for knife-edge (half-cut) scan of rectangular beam
function _aatFitBoxErf(xs,ys){
  var n=xs.length;if(n<5)return null;
  var sorted=ys.slice().sort(function(a,b){return a-b;});
  var lo=sorted[Math.floor(n*0.1)],hi=sorted[Math.floor(n*0.9)];
  var stepH=hi-lo;if(Math.abs(stepH)<1e-30)return null;
  var sign=(ys[0]>ys[n-1])?1:-1;
  var dy=window.numDeriv?window.numDeriv(xs,ys,true):null;
  var center=xs[Math.floor(n/2)];
  if(dy){var mxD=0,iM=0;for(var i=0;i<dy.length;i++){var av=Math.abs(dy[i]);if(av>mxD){mxD=av;iM=i;}}center=xs[iM];}
  var range=xs[n-1]-xs[0];
  var w0=range*0.3;
  var sig0=range/20;
  var A0=sign>0?lo:hi;
  var B0=sign*stepH/(2*w0);
  var p=[A0,B0,center,w0,sig0],lam=0.01;
  var sq2=1.4142135623730951,invSqrtPi=0.5641895835477563;
  function model(x,pp){
    var w=Math.abs(pp[3]),sig=Math.abs(pp[4]);
    var s=sig*sq2;if(s<1e-15)s=1e-15;
    var a=pp[2]-w/2,b=pp[2]+w/2;
    var u1=(x-a)/s,u2=(x-b)/s;
    var phi=w-((x-a)*erf_a(u1)-(x-b)*erf_a(u2)+s*invSqrtPi*(Math.exp(-u1*u1)-Math.exp(-u2*u2)));
    return pp[0]+pp[1]*phi;
  }
  for(var iter=0;iter<50;iter++){
    var J=[],r=[];var chi=0;
    for(var i2=0;i2<n;i2++){var m=model(xs[i2],p);r.push(ys[i2]-m);chi+=(ys[i2]-m)*(ys[i2]-m);
      var row=[];for(var k=0;k<5;k++){var dp=p.slice();var hh=Math.max(Math.abs(p[k])*1e-5,1e-10);dp[k]+=hh;row.push((model(xs[i2],dp)-m)/hh);}J.push(row);}
    var JtJ=[],Jtr=[];
    for(var k2=0;k2<5;k2++){JtJ[k2]=[];var s2=0;for(var i3=0;i3<n;i3++)s2+=J[i3][k2]*r[i3];Jtr[k2]=s2;
      for(var j=0;j<5;j++){var ss=0;for(var i4=0;i4<n;i4++)ss+=J[i4][k2]*J[i4][j];JtJ[k2][j]=ss;}JtJ[k2][k2]+=lam*(JtJ[k2][k2]+1e-6);}
    var dp2=window.solveLinear?window.solveLinear(JtJ,Jtr):null;if(!dp2)break;
    var pN=p.map(function(v,i5){return v+dp2[i5];});
    if(pN[3]<0)pN[3]=Math.abs(pN[3]);if(pN[4]<0)pN[4]=Math.abs(pN[4]);
    if(pN[4]<1e-12)pN[4]=sig0*0.1;
    var chi2=0;for(var i6=0;i6<n;i6++){var d=ys[i6]-model(xs[i6],pN);chi2+=d*d;}
    if(chi2<chi){p=pN;lam*=0.3;}else{lam*=5;if(lam>1e8)break;}
  }
  var ssRes=0,ssTot=0,yMean=0;
  for(var i7=0;i7<n;i7++)yMean+=ys[i7];yMean/=n;
  for(var i8=0;i8<n;i8++){var m2=model(xs[i8],p);ssRes+=(ys[i8]-m2)*(ys[i8]-m2);ssTot+=(ys[i8]-yMean)*(ys[i8]-yMean);}
  var nDense=Math.max(n*10,200),fitCurve=new Array(nDense),fitCurveX=new Array(nDense);
  var xSpan=xs[n-1]-xs[0];
  for(var i9=0;i9<nDense;i9++){var xd=xs[0]+xSpan*i9/(nDense-1);fitCurveX[i9]=xd;fitCurve[i9]=model(xd,p);}
  return{background:p[0],amplitude:p[1],center:p[2],boxWidth:Math.abs(p[3]),sigma:Math.abs(p[4]),
    fwhm:Math.abs(p[3])+2.355*Math.abs(p[4]),
    r2:ssTot>0?1-ssRes/ssTot:0,fitCurve:fitCurve,fitCurveX:fitCurveX};
}

// Polynomial fit (degree 1-5, normal equations)
function _aatFitPoly(xs,ys,degree){
  var n=xs.length;if(n<degree+1)return null;
  var xMin=xs[0],xR=xs[n-1]-xs[0]||1;
  var xn=xs.map(function(x){return(x-xMin)/xR;});
  var m=degree+1,ATA=[],ATy=[];
  for(var i=0;i<m;i++){ATA[i]=[];var s=0;for(var k=0;k<n;k++)s+=Math.pow(xn[k],i)*ys[k];ATy[i]=s;
    for(var j=0;j<m;j++){var ss=0;for(var k2=0;k2<n;k2++)ss+=Math.pow(xn[k2],i+j);ATA[i][j]=ss;}}
  var c=window.solveLinear?window.solveLinear(ATA,ATy):null;if(!c)return null;
  var ssRes=0,ssTot=0,yMean=0;
  for(var i2=0;i2<n;i2++)yMean+=ys[i2];yMean/=n;
  for(var i3=0;i3<n;i3++){var m2=0;for(var j2=0;j2<=degree;j2++)m2+=c[j2]*Math.pow(xn[i3],j2);
    ssRes+=(ys[i3]-m2)*(ys[i3]-m2);ssTot+=(ys[i3]-yMean)*(ys[i3]-yMean);}
  var nDense=Math.max(n*10,200),fitCurve=new Array(nDense),fitCurveX=new Array(nDense);
  var xSpan=xs[n-1]-xs[0];var maxY=-Infinity,peakX=xs[0];
  for(var i4=0;i4<nDense;i4++){var xd=xs[0]+xSpan*i4/(nDense-1);fitCurveX[i4]=xd;
    var xnd=(xd-xMin)/xR,m3=0;for(var j3=0;j3<=degree;j3++)m3+=c[j3]*Math.pow(xnd,j3);
    fitCurve[i4]=m3;if(m3>maxY){maxY=m3;peakX=xd;}}
  return{coefficients:c,center:peakX,degree:degree,r2:ssTot>0?1-ssRes/ssTot:0,fitCurve:fitCurve,fitCurveX:fitCurveX};
}

// -- Statistics (Shadow4-style) --
function _aatCalcStats(){
  var pos2=_aat.raw.pos,sig=_aat.activeSig||_aat.raw.sig,n=pos2.length;
  var s={};s.n=n;s.xMin=pos2[0];s.xMax=pos2[n-1];
  var yMin=Infinity,yMax=-Infinity;
  for(var i=0;i<n;i++){if(sig[i]<yMin)yMin=sig[i];if(sig[i]>yMax)yMax=sig[i];}
  s.yMin=yMin;s.yMax=yMax;
  var iPeak=0;for(var i2=1;i2<n;i2++)if(sig[i2]>sig[iPeak])iPeak=i2;
  s.peakX=pos2[iPeak];s.peakY=sig[iPeak];
  var sum=0;for(var i3=0;i3<n;i3++)sum+=sig[i3];s.mean=sum/n;
  var v=0;for(var i4=0;i4<n;i4++)v+=(sig[i4]-s.mean)*(sig[i4]-s.mean);s.stddev=Math.sqrt(v/n);
  var ws=0,wsp=0;for(var i5=0;i5<n;i5++){ws+=sig[i5];wsp+=sig[i5]*pos2[i5];}
  s.centroid=ws>0?wsp/ws:pos2[Math.floor(n/2)];
  var wv=0;for(var i6=0;i6<n;i6++)wv+=sig[i6]*(pos2[i6]-s.centroid)*(pos2[i6]-s.centroid);
  s.wSigma=ws>0?Math.sqrt(wv/ws):0;
  s.intensity=sum;
  s.fwhm=_aatFWxM(pos2,sig,yMax*0.5,n);
  s.fwhmCoord=_aatFWxMcoord(pos2,sig,yMax*0.5,n);
  s.fw25=_aatFWxM(pos2,sig,yMax*0.25,n);
  s.fw75=_aatFWxM(pos2,sig,yMax*0.75,n);
  _aat.stats=s;
}
function _aatFWxM(pos2,sig,th,n){
  var iL=-1,iR=-1;
  for(var i=0;i<n-1;i++){
    if(sig[i]<th&&sig[i+1]>=th&&iL<0)iL=i+(th-sig[i])/(sig[i+1]-sig[i]);
    if(sig[i]>=th&&sig[i+1]<th)iR=i+(sig[i]-th)/(sig[i]-sig[i+1]);
  }
  if(iL>=0&&iR>=0){var step=(pos2[n-1]-pos2[0])/(n-1);return(iR-iL)*step;}return null;
}
function _aatFWxMcoord(pos2,sig,th,n){
  var iL=-1,iR=-1;
  for(var i=0;i<n-1;i++){
    if(sig[i]<th&&sig[i+1]>=th&&iL<0)iL=i+(th-sig[i])/(sig[i+1]-sig[i]);
    if(sig[i]>=th&&sig[i+1]<th)iR=i+(sig[i]-th)/(sig[i]-sig[i+1]);
  }
  if(iL>=0&&iR>=0){var step=(pos2[n-1]-pos2[0])/(n-1);return{left:pos2[0]+iL*step,right:pos2[0]+iR*step};}return null;
}

// -- Draw Canvas --
function _aatDrawCanvas(){
  var cv=document.getElementById('aatCanvas');if(!cv)return;
  var dw2=cv.clientWidth||600, dh2=cv.clientHeight||340;
  var dpr2=Math.max(2,window.devicePixelRatio||1);
  cv.width=dw2*dpr2; cv.height=dh2*dpr2;
  var ctx=cv.getContext('2d'); ctx.scale(dpr2,dpr2);
  var W=dw2, H=dh2;
  var pad={l:62,r:16,t:22,b:36};
  if(_aat.show.deriv&&_aat.derivative)pad.r=62;
  var pw=W-pad.l-pad.r,ph=H-pad.t-pad.b;
  var _th3=typeof _getChartTheme==='function'?_getChartTheme():'dark2';
  var _ct3=typeof _CHART_THEMES!=='undefined'?_CHART_THEMES[_th3]:null;
  var _bgc3=_ct3?_ct3.bg:'#080c14';
  var _grc3=_ct3?_ct3.grid:'rgba(80,160,255,0.06)';
  var _brc3=_ct3?_ct3.border:'rgba(80,160,255,0.2)';
  var _tkc3=_ct3?_ct3.tick:'#6b7280';
  var _lbc3=_ct3?_ct3.label:'#6b7280';
  ctx.fillStyle=_bgc3;ctx.fillRect(0,0,W,H);
  var pos2=_aat.raw.pos,sig=_aat.activeSig||_aat.raw.sig,n=pos2.length;
  var xMin=pos2[0],xMax=pos2[n-1],dx=xMax-xMin||1;
  var yMin=Infinity,yMax=-Infinity;
  function updYR(arr){for(var i=0;i<arr.length;i++){var v2=_aat.logY?Math.log10(Math.max(arr[i],1e-30)):arr[i];if(v2<yMin)yMin=v2;if(v2>yMax)yMax=v2;}}
  if(_aat.show.raw)updYR(sig);
  if(_aat.show.smooth&&_aat.smoothed)updYR(_aat.smoothed);
  if(_aat.show.fit&&_aat.fitResult&&_aat.fitResult.fitCurve)updYR(_aat.fitResult.fitCurve);
  if(yMin===Infinity){yMin=0;yMax=1;}
  var yPd=(yMax-yMin)*0.06||0.1;yMin-=yPd;yMax+=yPd;
  var dy=yMax-yMin||1;
  function tx(x){return pad.l+(x-xMin)/dx*pw;}
  function ty(y){var v2=_aat.logY?Math.log10(Math.max(y,1e-30)):y;return pad.t+ph-(v2-yMin)/dy*ph;}

  // Grid
  ctx.strokeStyle=_grc3;ctx.lineWidth=0.5;
  for(var g=0;g<=5;g++){
    var gy=pad.t+ph*g/5;ctx.beginPath();ctx.moveTo(pad.l,gy);ctx.lineTo(pad.l+pw,gy);ctx.stroke();
    var yv=yMax-(yMax-yMin)*g/5;ctx.fillStyle=_tkc3;ctx.font='8px monospace';ctx.textAlign='right';
    ctx.fillText(_aat.logY?'1e'+yv.toFixed(1):yv.toExponential(1),pad.l-4,gy+3);
  }
  for(var g2=0;g2<=5;g2++){
    var gx=pad.l+pw*g2/5;ctx.beginPath();ctx.moveTo(gx,pad.t);ctx.lineTo(gx,pad.t+ph);ctx.stroke();
    var xv=xMin+dx*g2/5;ctx.fillStyle=_tkc3;ctx.textAlign='center';ctx.fillText(xv.toFixed(3),gx,H-pad.b+14);
  }
  ctx.strokeStyle=_brc3;ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(pad.l,pad.t);ctx.lineTo(pad.l,pad.t+ph);ctx.lineTo(pad.l+pw,pad.t+ph);ctx.stroke();

  // FWHM bracket
  var st=_aat.stats;
  if(st&&st.fwhm&&st.fwhmCoord&&_aat.show.raw&&!_aat.logY){
    ctx.save();
    var hm=ty(st.peakY*0.5);
    ctx.strokeStyle='#ff606040';ctx.lineWidth=1;ctx.setLineDash([3,3]);
    ctx.beginPath();ctx.moveTo(pad.l,hm);ctx.lineTo(pad.l+pw,hm);ctx.stroke();
    ctx.strokeStyle='#ff6060';ctx.lineWidth=1.5;ctx.setLineDash([]);
    var xl=tx(st.fwhmCoord.left),xr=tx(st.fwhmCoord.right);
    ctx.beginPath();ctx.moveTo(xl,hm-6);ctx.lineTo(xl,hm+6);ctx.stroke();
    ctx.beginPath();ctx.moveTo(xr,hm-6);ctx.lineTo(xr,hm+6);ctx.stroke();
    ctx.beginPath();ctx.moveTo(xl,hm);ctx.lineTo(xr,hm);ctx.stroke();
    ctx.fillStyle='#ff6060';ctx.font='8px monospace';ctx.textAlign='center';
    ctx.fillText('FWHM='+st.fwhm.toFixed(4),(xl+xr)/2,hm-8);
    ctx.restore();
  }

  // Raw data
  if(_aat.show.raw){
    ctx.fillStyle='#40d89a12';ctx.beginPath();ctx.moveTo(tx(pos2[0]),pad.t+ph);
    for(var i=0;i<n;i++)ctx.lineTo(tx(pos2[i]),ty(sig[i]));
    ctx.lineTo(tx(pos2[n-1]),pad.t+ph);ctx.closePath();ctx.fill();
    ctx.strokeStyle='#40d89a';ctx.lineWidth=1.2;ctx.beginPath();
    for(var i2=0;i2<n;i2++)i2===0?ctx.moveTo(tx(pos2[i2]),ty(sig[i2])):ctx.lineTo(tx(pos2[i2]),ty(sig[i2]));ctx.stroke();
    ctx.fillStyle='#40d89a';for(var i3=0;i3<n;i3++){ctx.beginPath();ctx.arc(tx(pos2[i3]),ty(sig[i3]),2,0,6.283);ctx.fill();}
  }
  // Smoothed data
  if(_aat.show.smooth&&_aat.smoothed){
    ctx.strokeStyle='#4db8ff';ctx.lineWidth=2;ctx.beginPath();
    for(var i4=0;i4<n;i4++)i4===0?ctx.moveTo(tx(pos2[i4]),ty(_aat.smoothed[i4])):ctx.lineTo(tx(pos2[i4]),ty(_aat.smoothed[i4]));ctx.stroke();
  }
  // Fit curve
  if(_aat.show.fit&&_aat.fitResult&&_aat.fitResult.fitCurve){
    ctx.save();ctx.strokeStyle='#ff4060';ctx.lineWidth=2;ctx.setLineDash([5,3]);
    var fc=_aat.fitResult.fitCurve,fcx=_aat.fitResult.fitCurveX||pos2;ctx.beginPath();
    for(var i5=0;i5<fc.length;i5++)i5===0?ctx.moveTo(tx(fcx[i5]),ty(fc[i5])):ctx.lineTo(tx(fcx[i5]),ty(fc[i5]));ctx.stroke();
    if(_aat.fitResult.center!=null){
      ctx.strokeStyle='#ff4060';ctx.lineWidth=1;ctx.setLineDash([2,3]);
      ctx.beginPath();ctx.moveTo(tx(_aat.fitResult.center),pad.t);ctx.lineTo(tx(_aat.fitResult.center),pad.t+ph);ctx.stroke();
    }
    ctx.restore();
  }
  // Derivative (second Y axis)
  if(_aat.show.deriv&&_aat.derivative){
    var dv=_aat.derivative,dvMin=Infinity,dvMax=-Infinity;
    for(var i6=0;i6<dv.length;i6++){if(dv[i6]<dvMin)dvMin=dv[i6];if(dv[i6]>dvMax)dvMax=dv[i6];}
    var dvR=dvMax-dvMin||1;dvMin-=dvR*0.05;dvMax+=dvR*0.05;var ddy=dvMax-dvMin;
    function tyd(v2){return pad.t+ph-(v2-dvMin)/ddy*ph;}
    ctx.strokeStyle='rgba(255,144,96,0.3)';ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(pad.l+pw,pad.t);ctx.lineTo(pad.l+pw,pad.t+ph);ctx.stroke();
    for(var g3=0;g3<=4;g3++){var gy2=pad.t+ph*g3/4;var dv2=dvMax-ddy*g3/4;
      ctx.fillStyle='#ff9060';ctx.font='8px monospace';ctx.textAlign='left';
      ctx.fillText(dv2.toExponential(0),pad.l+pw+4,gy2+3);}
    ctx.strokeStyle='#ff9060';ctx.lineWidth=1.3;ctx.beginPath();
    for(var i7=0;i7<dv.length;i7++)i7===0?ctx.moveTo(tx(pos2[i7]),tyd(dv[i7])):ctx.lineTo(tx(pos2[i7]),tyd(dv[i7]));ctx.stroke();
    var iMx=0;for(var i8=1;i8<dv.length;i8++)if(Math.abs(dv[i8])>Math.abs(dv[iMx]))iMx=i8;
    ctx.fillStyle='#ffcc00';ctx.beginPath();ctx.arc(tx(pos2[iMx]),tyd(dv[iMx]),4,0,6.283);ctx.fill();
    ctx.fillStyle='#ff9060';ctx.font='8px monospace';
    ctx.save();ctx.translate(W-4,pad.t+ph/2);ctx.rotate(-Math.PI/2);ctx.textAlign='center';ctx.fillText('d/dx',0,0);ctx.restore();
  }
  // Centroid marker
  if(st&&!_aat.logY){
    ctx.strokeStyle='#4db8ff60';ctx.lineWidth=1;ctx.setLineDash([2,4]);
    ctx.beginPath();ctx.moveTo(tx(st.centroid),pad.t);ctx.lineTo(tx(st.centroid),pad.t+ph);ctx.stroke();ctx.setLineDash([]);
  }
  // Legend
  var leg=[];
  if(_aat.show.raw)leg.push({c:'#40d89a',l:'Raw'});
  if(_aat.show.smooth)leg.push({c:'#4db8ff',l:'Smooth(SG-'+(2*_aat.sgHW+1)+')'});
  if(_aat.show.deriv)leg.push({c:'#ff9060',l:'d/dx'});
  if(_aat.show.fit&&_aat.fitResult)leg.push({c:'#ff4060',l:_aat.fitResult.type||'Fit'});
  for(var i9=0;i9<leg.length;i9++){
    var lx=pad.l+8+i9*100,ly=pad.t+12;
    ctx.fillStyle=leg[i9].c;ctx.fillRect(lx,ly-4,14,3);
    ctx.font='8px monospace';ctx.textAlign='left';ctx.fillText(leg[i9].l,lx+18,ly);
  }
  ctx.fillStyle=_lbc3;ctx.font='9px monospace';ctx.textAlign='center';
  ctx.fillText('Position',pad.l+pw/2,H-4);
  ctx.save();ctx.translate(10,pad.t+ph/2);ctx.rotate(-Math.PI/2);
  ctx.fillText(_aat.logY?'log10(Signal)':'Signal',0,0);ctx.restore();
}

// -- Stats Panel --
function _aatDrawStats(){
  var el=document.getElementById('aatStats');if(!el)return;
  var s=_aat.stats;if(!s)return;
  var h='<div style="font-size:10px;color:var(--am,#d2a8ff);font-weight:600;margin-bottom:6px">Data Statistics</div>';
  h+='<div style="border-bottom:1px solid var(--b1,#21262d);margin-bottom:5px;padding-bottom:5px">';
  h+=_sr('N points',s.n);
  h+=_sr('X range',s.xMin.toFixed(4)+' ~ '+s.xMax.toFixed(4));
  h+=_sr('Y range',s.yMin.toExponential(2)+' ~ '+s.yMax.toExponential(2));
  h+=_sr('Intensity',s.intensity.toExponential(3));
  h+='</div>';
  h+='<div style="border-bottom:1px solid var(--b1);margin-bottom:5px;padding-bottom:5px">';
  h+=_sr('Peak',s.peakY.toExponential(2)+' @ '+s.peakX.toFixed(4));
  h+=_sr('Centroid',s.centroid.toFixed(5));
  h+=_sr('Mean',s.mean.toExponential(3));
  h+=_sr('StdDev',s.stddev.toExponential(3));
  h+=_sr('\u03c3 (weighted)',s.wSigma.toFixed(5));
  h+='</div>';
  h+='<div style="border-bottom:1px solid var(--b1);margin-bottom:5px;padding-bottom:5px">';
  h+=_sr('FWHM',s.fwhm!=null?s.fwhm.toFixed(5):'N/A');
  h+=_sr('FW25%',s.fw25!=null?s.fw25.toFixed(5):'N/A');
  h+=_sr('FW75%',s.fw75!=null?s.fw75.toFixed(5):'N/A');
  h+='</div>';
  if(_aat.fitResult){
    var f=_aat.fitResult;
    h+='<div style="font-size:10px;color:var(--am);font-weight:600;margin-bottom:4px;margin-top:2px">Fit: '+f.type+'</div>';
    var rc=f.r2>0.95?'#40d89a':f.r2>0.8?'#ffb340':'#ff4060';
    h+=_sr('R\u00b2',f.r2!=null?f.r2.toFixed(5):'N/A',rc);
    if(f.center!=null)h+=_sr('Center',f.center.toFixed(5));
    if(f.sigma!=null)h+=_sr('\u03c3',f.sigma.toFixed(5));
    if(f.fwhm!=null)h+=_sr('FWHM',f.fwhm.toFixed(5));
    if(f.gamma!=null)h+=_sr('\u03b3',f.gamma.toFixed(5));
    if(f.amplitude!=null)h+=_sr('Amplitude',f.amplitude.toExponential(3));
    if(f.background!=null)h+=_sr('Background',f.background.toExponential(3));
    if(f.boxWidth!=null)h+=_sr('Box width',f.boxWidth.toFixed(5));
    if(f.degree!=null)h+=_sr('Degree',f.degree);
    if(f.coefficients){for(var i=0;i<f.coefficients.length;i++)h+=_sr('c['+i+']',f.coefficients[i].toExponential(3));}
  }
  el.innerHTML=h;
}
function _sr(label,value,color){
  return '<div style="display:flex;justify-content:space-between;gap:4px">'
    +'<span style="color:var(--t3,#8b949e)">'+label+':</span>'
    +'<span style="color:'+(color||'var(--t1,#e6edf3)')+'">'+value+'</span></div>';
}

// -- Data Table --
function _aatDrawTable(){
  var el=document.getElementById('aatTable');if(!el)return;
  var pos2=_aat.raw.pos,sig=_aat.activeSig||_aat.raw.sig,sm=_aat.smoothed,dv=_aat.derivative;
  var fitAtData=null;
  if(_aat.fitResult&&_aat.fitResult.fitCurve){
    var fc=_aat.fitResult.fitCurve,fcx=_aat.fitResult.fitCurveX;
    if(fcx&&fcx.length!==pos2.length){
      fitAtData=[];var j=0;
      for(var i=0;i<pos2.length;i++){
        while(j<fcx.length-1&&fcx[j+1]<=pos2[i])j++;
        if(j<fcx.length-1){var t=(pos2[i]-fcx[j])/(fcx[j+1]-fcx[j]||1);fitAtData.push(fc[j]+(fc[j+1]-fc[j])*t);}
        else fitAtData.push(fc[j]);
      }
    }else{fitAtData=fc;}
  }
  var h='<table style="border-collapse:collapse;width:100%;font-size:8px;font-family:var(--mn)">';
  h+='<tr style="color:var(--t2,#c9d1d9);border-bottom:1px solid var(--b1);position:sticky;top:0;background:var(--bg,#0d1117)">';
  h+='<th style="padding:2px 4px;text-align:center">#</th><th style="padding:2px 4px;text-align:right">Position</th>';
  h+='<th style="padding:2px 4px;text-align:right">Signal</th>';
  if(sm)h+='<th style="padding:2px 4px;text-align:right">Smooth</th>';
  if(dv)h+='<th style="padding:2px 4px;text-align:right">d/dx</th>';
  if(fitAtData)h+='<th style="padding:2px 4px;text-align:right">Fit</th>';
  h+='</tr>';
  for(var i2=0;i2<pos2.length;i2++){
    h+='<tr style="border-bottom:1px solid rgba(33,38,45,0.4)">';
    h+='<td style="padding:1px 4px;text-align:center;color:var(--t3)">'+(i2+1)+'</td>';
    h+='<td style="padding:1px 4px;text-align:right">'+pos2[i2].toFixed(4)+'</td>';
    h+='<td style="padding:1px 4px;text-align:right">'+sig[i2].toExponential(3)+'</td>';
    if(sm)h+='<td style="padding:1px 4px;text-align:right">'+sm[i2].toExponential(3)+'</td>';
    if(dv)h+='<td style="padding:1px 4px;text-align:right">'+(i2<dv.length?dv[i2].toExponential(2):'--')+'</td>';
    if(fitAtData)h+='<td style="padding:1px 4px;text-align:right">'+(i2<fitAtData.length?fitAtData[i2].toExponential(3):'--')+'</td>';
    h+='</tr>';
  }
  h+='</table>';el.innerHTML=h;
}

// -- Copy TSV --
function _aatCopy(){
  var pos2=_aat.raw.pos,sig=_aat.activeSig||_aat.raw.sig,sm=_aat.smoothed,dv=_aat.derivative;
  var fitAtData=null;
  if(_aat.fitResult&&_aat.fitResult.fitCurve){
    var fc2=_aat.fitResult.fitCurve,fcx2=_aat.fitResult.fitCurveX;
    if(fcx2&&fcx2.length!==pos2.length){
      fitAtData=[];var j=0;
      for(var i=0;i<pos2.length;i++){
        while(j<fcx2.length-1&&fcx2[j+1]<=pos2[i])j++;
        if(j<fcx2.length-1){var t=(pos2[i]-fcx2[j])/(fcx2[j+1]-fcx2[j]||1);fitAtData.push(fc2[j]+(fc2[j+1]-fc2[j])*t);}
        else fitAtData.push(fc2[j]);
      }
    }else{fitAtData=fc2;}
  }
  var hdr=['Position','Signal'];if(sm)hdr.push('Smoothed');if(dv)hdr.push('Derivative');if(fitAtData)hdr.push('Fit');
  var lines=[hdr.join('\t')];
  for(var i2=0;i2<pos2.length;i2++){
    var row=[pos2[i2].toFixed(6),sig[i2].toExponential(4)];
    if(sm)row.push(sm[i2].toExponential(4));
    if(dv)row.push(i2<dv.length?dv[i2].toExponential(4):'');
    if(fitAtData)row.push(i2<fitAtData.length?fitAtData[i2].toExponential(4):'');
    lines.push(row.join('\t'));
  }
  var text=lines.join('\n');
  if(navigator.clipboard){navigator.clipboard.writeText(text).then(function(){log('info','Data copied ('+pos2.length+' rows)');});}
  else{var ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);log('info','Data copied');}
}

console.log('[alignment/05_align_analysis] Data Analysis Tool loaded');
})();

// ===================================================================
// Alignment Analysis Engine -- Proper Curve Fitting
// Replaces simplistic peak-find / derivative-max analysis
// with Savitzky-Golay smoothing + Levenberg-Marquardt fitting
// ===================================================================
(function(){

  // ---- 1. Savitzky-Golay Smoothing (quadratic polynomial) ----
  var SG = {
    2: {c:[-3,12,17,12,-3], norm:35},       // window=5
    3: {c:[-2,3,6,7,6,3,-2], norm:21}        // window=7
  };

  window.sgSmooth = function(ys, halfW) {
    halfW = halfW || 2;
    var n = ys.length;
    if (n < 2*halfW+1) return ys.slice();
    var out = ys.slice();
    var sg = SG[halfW];
    if (!sg) { // fallback: uniform moving average
      for (var i = halfW; i < n-halfW; i++) {
        var s = 0;
        for (var j = -halfW; j <= halfW; j++) s += ys[i+j];
        out[i] = s / (2*halfW+1);
      }
      return out;
    }
    var c = sg.c, nm = sg.norm;
    for (var i2 = halfW; i2 < n-halfW; i2++) {
      var s2 = 0;
      for (var j2 = -halfW; j2 <= halfW; j2++) s2 += c[j2+halfW] * ys[i2+j2];
      out[i2] = s2 / nm;
    }
    return out;
  };

  // ---- 2. Numerical Derivative (central difference + optional smooth) ----
  window.numDeriv = function(xs, ys, doSmooth) {
    var n = ys.length;
    var hw = Math.min(3, Math.max(2, Math.floor(n/10)));
    var sy = doSmooth ? sgSmooth(ys, hw) : ys;
    var dy = new Array(n);
    dy[0] = (sy[1] - sy[0]) / (xs[1] - xs[0]);
    for (var i = 1; i < n-1; i++)
      dy[i] = (sy[i+1] - sy[i-1]) / (xs[i+1] - xs[i-1]);
    dy[n-1] = (sy[n-1] - sy[n-2]) / (xs[n-1] - xs[n-2]);
    return dy;
  };

  // ---- 3. NxN Linear System Solver (Gaussian elimination, partial pivoting) ----
  function solveLinear(A, b) {
    var N = b.length;
    var M = [];
    for (var i = 0; i < N; i++) {
      M[i] = new Array(N+1);
      for (var j = 0; j < N; j++) M[i][j] = A[i][j];
      M[i][N] = b[i];
    }
    for (var col = 0; col < N; col++) {
      var maxR = col, maxV = Math.abs(M[col][col]);
      for (var r = col+1; r < N; r++)
        if (Math.abs(M[r][col]) > maxV) { maxV = Math.abs(M[r][col]); maxR = r; }
      if (maxV < 1e-30) return null;
      var tmp = M[col]; M[col] = M[maxR]; M[maxR] = tmp;
      for (var r2 = col+1; r2 < N; r2++) {
        var f = M[r2][col] / M[col][col];
        for (var j2 = col; j2 <= N; j2++) M[r2][j2] -= f * M[col][j2];
      }
    }
    var x = new Array(N);
    for (var i2 = N-1; i2 >= 0; i2--) {
      x[i2] = M[i2][N];
      for (var j3 = i2+1; j3 < N; j3++) x[i2] -= M[i2][j3] * x[j3];
      x[i2] /= M[i2][i2];
    }
    return x;
  }
  // Expose solveLinear globally (used by Data Analysis Tool erf/boxerf/poly fits)
  window.solveLinear = solveLinear;

  // ---- 4. Gaussian Fit: A*exp(-0.5*((x-mu)/sig)^2) + bg ----
  window.gaussianFit = function(xs, ys, opts) {
    opts = opts || {};
    var n = xs.length;
    if (n < 5) return null;
    var hw = opts.smoothHW || Math.min(3, Math.max(2, Math.floor(n/10)));
    var sy = opts.smooth !== false ? sgSmooth(ys, hw) : ys;
    var bg0 = Infinity, maxY = -Infinity, iMax = 0;
    for (var i = 0; i < n; i++) {
      if (sy[i] < bg0) bg0 = sy[i];
      if (sy[i] > maxY) { maxY = sy[i]; iMax = i; }
    }
    var A0 = maxY - bg0;
    if (A0 < 1e-30) return null;
    var sumW = 0, sumWx = 0, sumWx2 = 0;
    for (var i2 = 0; i2 < n; i2++) {
      var w = Math.max(sy[i2] - bg0, 0);
      sumW += w; sumWx += w * xs[i2];
    }
    if (sumW < 1e-30) return null;
    var mu0 = sumWx / sumW;
    for (var i3 = 0; i3 < n; i3++) {
      var w2 = Math.max(sy[i3] - bg0, 0);
      sumWx2 += w2 * (xs[i3] - mu0) * (xs[i3] - mu0);
    }
    var sig0 = Math.sqrt(sumWx2 / sumW);
    if (sig0 < 1e-15) sig0 = (xs[n-1] - xs[0]) / 6;
    var p = [A0, mu0, sig0, bg0];
    var lam = 0.01;
    for (var iter = 0; iter < 25; iter++) {
      var JtJ = [[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]];
      var JtR = [0,0,0,0], chi = 0;
      for (var i4 = 0; i4 < n; i4++) {
        var dx = xs[i4] - p[1], s2 = p[2]*p[2];
        var ex = Math.exp(-0.5 * dx * dx / s2);
        var mod = p[0] * ex + p[3];
        var r = ys[i4] - mod;
        chi += r * r;
        var J = [ex, p[0]*ex*dx/s2, p[0]*ex*dx*dx/(s2*p[2]), 1];
        for (var a = 0; a < 4; a++) {
          JtR[a] += J[a] * r;
          for (var b = 0; b < 4; b++) JtJ[a][b] += J[a] * J[b];
        }
      }
      for (var a2 = 0; a2 < 4; a2++) JtJ[a2][a2] *= (1 + lam);
      var delta = solveLinear(JtJ, JtR);
      if (!delta) break;
      var pN = [p[0]+delta[0], p[1]+delta[1], p[2]+delta[2], p[3]+delta[3]];
      if (pN[2] < 0) pN[2] = Math.abs(pN[2]);
      if (pN[2] < 1e-15) pN[2] = sig0 * 0.1;
      var chi2 = 0;
      for (var i5 = 0; i5 < n; i5++) {
        var dx2 = xs[i5] - pN[1];
        var mod2 = pN[0] * Math.exp(-0.5*dx2*dx2/(pN[2]*pN[2])) + pN[3];
        chi2 += (ys[i5] - mod2) * (ys[i5] - mod2);
      }
      if (chi2 < chi) { p = pN; lam *= 0.3; if (lam < 1e-10) lam = 1e-10; }
      else { lam *= 5; if (lam > 1e8) break; }
    }
    var ssRes = 0, ssTot = 0, yMean = 0;
    for (var i6 = 0; i6 < n; i6++) yMean += ys[i6];
    yMean /= n;
    for (var i7 = 0; i7 < n; i7++) {
      var dx3 = xs[i7] - p[1];
      var mod3 = p[0] * Math.exp(-0.5*dx3*dx3/(p[2]*p[2])) + p[3];
      ssRes += (ys[i7] - mod3) * (ys[i7] - mod3);
      ssTot += (ys[i7] - yMean) * (ys[i7] - yMean);
    }
    var r2 = ssTot > 0 ? 1 - ssRes / ssTot : 0;
    var nDense = Math.max(n*10, 200);
    var fitCurve = new Array(nDense), fitCurveX = new Array(nDense);
    var xSpan = xs[n-1] - xs[0];
    for (var i8 = 0; i8 < nDense; i8++) {
      var xd = xs[0] + xSpan * i8 / (nDense - 1); fitCurveX[i8] = xd;
      var dx4 = xd - p[1];
      fitCurve[i8] = p[0] * Math.exp(-0.5*dx4*dx4/(p[2]*p[2])) + p[3];
    }
    return {
      amplitude: p[0], center: p[1], sigma: Math.abs(p[2]),
      fwhm: Math.abs(p[2]) * 2.3548, background: p[3],
      r2: r2, fitCurve: fitCurve, fitCurveX: fitCurveX
    };
  };

  // ---- 5. Lorentzian Fit: A / (1 + ((x-x0)/gamma)^2) + bg ----
  window.lorentzianFit = function(xs, ys, opts) {
    opts = opts || {};
    var n = xs.length;
    if (n < 5) return null;
    var hw = opts.smoothHW || Math.min(3, Math.max(2, Math.floor(n/10)));
    var sy = opts.smooth !== false ? sgSmooth(ys, hw) : ys;
    var bg0 = Infinity, maxY = -Infinity, iMax = 0;
    for (var i = 0; i < n; i++) {
      if (sy[i] < bg0) bg0 = sy[i];
      if (sy[i] > maxY) { maxY = sy[i]; iMax = i; }
    }
    var A0 = maxY - bg0;
    if (A0 < 1e-30) return null;
    var x0_0 = xs[iMax];
    var hm = bg0 + A0 * 0.5;
    var iL = iMax, iR = iMax;
    for (var j = iMax; j >= 0; j--) if (sy[j] < hm) { iL = j; break; }
    for (var j2 = iMax; j2 < n; j2++) if (sy[j2] < hm) { iR = j2; break; }
    var gam0 = Math.max((xs[iR] - xs[iL]) / 2, (xs[n-1] - xs[0]) / 20);
    var p = [A0, x0_0, gam0, bg0];
    var lam = 0.01;
    for (var iter = 0; iter < 25; iter++) {
      var JtJ = [[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]];
      var JtR = [0,0,0,0], chi = 0;
      for (var i2 = 0; i2 < n; i2++) {
        var dx = xs[i2] - p[1], g2 = p[2]*p[2];
        var u2 = dx*dx/g2;
        var den = 1 + u2, den2 = den*den;
        var mod = p[0] / den + p[3];
        var r = ys[i2] - mod;
        chi += r * r;
        var J = [
          1/den,
          p[0]*2*dx / (g2*den2),
          p[0]*2*dx*dx / (p[2]*g2*den2),
          1
        ];
        for (var a = 0; a < 4; a++) {
          JtR[a] += J[a] * r;
          for (var b = 0; b < 4; b++) JtJ[a][b] += J[a] * J[b];
        }
      }
      for (var a2 = 0; a2 < 4; a2++) JtJ[a2][a2] *= (1 + lam);
      var delta = solveLinear(JtJ, JtR);
      if (!delta) break;
      var pN = [p[0]+delta[0], p[1]+delta[1], p[2]+delta[2], p[3]+delta[3]];
      if (pN[2] < 0) pN[2] = Math.abs(pN[2]);
      if (pN[2] < 1e-15) pN[2] = gam0 * 0.1;
      var chi2 = 0;
      for (var i3 = 0; i3 < n; i3++) {
        var dx2 = xs[i3] - pN[1];
        var mod2 = pN[0] / (1 + dx2*dx2/(pN[2]*pN[2])) + pN[3];
        chi2 += (ys[i3] - mod2) * (ys[i3] - mod2);
      }
      if (chi2 < chi) { p = pN; lam *= 0.3; if (lam < 1e-10) lam = 1e-10; }
      else { lam *= 5; if (lam > 1e8) break; }
    }
    var ssRes = 0, ssTot = 0, yMean = 0;
    for (var i4 = 0; i4 < n; i4++) yMean += ys[i4];
    yMean /= n;
    for (var i5 = 0; i5 < n; i5++) {
      var dx3 = xs[i5] - p[1];
      var mod3 = p[0] / (1 + dx3*dx3/(p[2]*p[2])) + p[3];
      ssRes += (ys[i5] - mod3) * (ys[i5] - mod3);
      ssTot += (ys[i5] - yMean) * (ys[i5] - yMean);
    }
    var r2 = ssTot > 0 ? 1 - ssRes / ssTot : 0;
    var nDense = Math.max(n*10, 200);
    var fitCurve = new Array(nDense), fitCurveX = new Array(nDense);
    var xSpan = xs[n-1] - xs[0];
    for (var i6 = 0; i6 < nDense; i6++) {
      var xd = xs[0] + xSpan * i6 / (nDense - 1); fitCurveX[i6] = xd;
      var dx4 = xd - p[1];
      fitCurve[i6] = p[0] / (1 + dx4*dx4/(p[2]*p[2])) + p[3];
    }
    return {
      amplitude: p[0], center: p[1], gamma: Math.abs(p[2]),
      fwhm: 2 * Math.abs(p[2]), background: p[3],
      r2: r2, fitCurve: fitCurve, fitCurveX: fitCurveX
    };
  };

  // ---- 5b. Box-erf Fit: for rectangular beam (WB slit) knife-edge scans ----
  // Model: S(x) = A + B * [erf((x-c+w/2)/(sig*sqrt2)) - erf((x-c-w/2)/(sig*sqrt2))]
  // where c=box center, w=box width, sig=edge blur
  window.boxErfFit = function(xs, ys, opts) {
    opts = opts || {};
    var n = xs.length;
    if (n < 5) return null;
    var sorted = ys.slice().sort(function(a,b){return a-b;});
    var lo = sorted[Math.floor(n*0.1)], hi = sorted[Math.floor(n*0.9)];
    var stepH = hi - lo;
    if (Math.abs(stepH) < 1e-30) return null;
    // Determine scan direction: rising or falling edge
    var sign = (ys[0] > ys[n-1]) ? 1 : -1;
    // Initial center from derivative peak
    var dy = numDeriv(xs, ys, true);
    var center = xs[Math.floor(n/2)];
    if (dy) {
      var mxD = 0, iM = 0;
      for (var i = 0; i < dy.length; i++) {
        var av = Math.abs(dy[i]);
        if (av > mxD) { mxD = av; iM = i; }
      }
      center = xs[iM];
    }
    var range = xs[n-1] - xs[0];
    var w0 = range * 0.3;
    var sig0 = range / 20;
    var A0 = sign > 0 ? lo : hi;
    var B0 = sign * stepH / (2 * w0);
    var p = [A0, B0, center, w0, sig0], lam = 0.01;
    var sq2 = 1.4142135623730951, invSqrtPi = 0.5641895835477563;
    function model(x, pp) {
      var w = Math.abs(pp[3]), sig2 = Math.abs(pp[4]);
      var s = sig2 * sq2; if (s < 1e-15) s = 1e-15;
      var a = pp[2] - w/2, b = pp[2] + w/2;
      var u1 = (x-a)/s, u2 = (x-b)/s;
      var phi = w - ((x-a)*erf_a(u1) - (x-b)*erf_a(u2)
                + s*invSqrtPi*(Math.exp(-u1*u1) - Math.exp(-u2*u2)));
      return pp[0] + pp[1] * phi;
    }
    for (var iter = 0; iter < 50; iter++) {
      var J = [], r = [], chi = 0;
      for (var i2 = 0; i2 < n; i2++) {
        var m = model(xs[i2], p); r.push(ys[i2] - m); chi += (ys[i2]-m)*(ys[i2]-m);
        var row = [];
        for (var k = 0; k < 5; k++) {
          var dp = p.slice(); var hh = Math.max(Math.abs(p[k])*1e-5, 1e-10);
          dp[k] += hh; row.push((model(xs[i2], dp) - m) / hh);
        }
        J.push(row);
      }
      var JtJ = [], Jtr = [];
      for (var k2 = 0; k2 < 5; k2++) {
        JtJ[k2] = []; var s2 = 0;
        for (var i3 = 0; i3 < n; i3++) s2 += J[i3][k2]*r[i3];
        Jtr[k2] = s2;
        for (var j2 = 0; j2 < 5; j2++) {
          var ss = 0; for (var i4 = 0; i4 < n; i4++) ss += J[i4][k2]*J[i4][j2];
          JtJ[k2][j2] = ss;
        }
        JtJ[k2][k2] += lam*(JtJ[k2][k2]+1e-6);
      }
      var dp2 = solveLinear(JtJ, Jtr); if (!dp2) break;
      var pN = p.map(function(v,i5){return v+dp2[i5];});
      if (pN[3] < 0) pN[3] = Math.abs(pN[3]);
      if (pN[4] < 0) pN[4] = Math.abs(pN[4]);
      if (pN[4] < 1e-12) pN[4] = sig0*0.1;
      var chi2 = 0;
      for (var i6 = 0; i6 < n; i6++) { var d = ys[i6]-model(xs[i6],pN); chi2 += d*d; }
      if (chi2 < chi) { p = pN; lam *= 0.3; } else { lam *= 5; if (lam > 1e8) break; }
    }
    var ssRes = 0, ssTot = 0, yMean = 0;
    for (var i7 = 0; i7 < n; i7++) yMean += ys[i7]; yMean /= n;
    for (var i8 = 0; i8 < n; i8++) {
      var m2 = model(xs[i8], p); ssRes += (ys[i8]-m2)*(ys[i8]-m2); ssTot += (ys[i8]-yMean)*(ys[i8]-yMean);
    }
    var nDense = Math.max(n*10, 200), fitCurve = new Array(nDense), fitCurveX = new Array(nDense);
    var xSpan = xs[n-1] - xs[0];
    for (var i9 = 0; i9 < nDense; i9++) {
      var xd = xs[0] + xSpan*i9/(nDense-1); fitCurveX[i9] = xd; fitCurve[i9] = model(xd, p);
    }
    return {
      background: p[0], amplitude: p[1], center: p[2],
      boxWidth: Math.abs(p[3]), sigma: Math.abs(p[4]),
      fwhm: Math.abs(p[3]) + 2.355*Math.abs(p[4]),
      r2: ssTot > 0 ? 1 - ssRes/ssTot : 0,
      fitCurve: fitCurve, fitCurveX: fitCurveX
    };
  };

  // ---- 6. Analysis Dispatcher -- called by all alignment procedures ----
  window.analyzeAlignScan = function(xs, ys, algo, opts) {
    opts = opts || {};
    var result = {positions: xs, signals: ys};

    if (algo === 'boxerf') {
      // Box-erf fit for rectangular beam (white beam through WB slit)
      var beFit = boxErfFit(xs, ys);
      if (beFit && beFit.r2 > 0.3) {
        result.center = beFit.center;
        result.boxWidth = beFit.boxWidth;
        result.sigma = beFit.sigma;
        result.fwhm = beFit.fwhm;
        result.fit = beFit;
        result.method = 'boxerf: LM fit (R2=' + beFit.r2.toFixed(3) + ')';
      } else {
        // Fallback: derivative peak
        var dy0 = numDeriv(xs, ys, true);
        var absDy0 = new Array(dy0.length);
        for (var j0 = 0; j0 < dy0.length; j0++) absDy0[j0] = Math.abs(dy0[j0]);
        var mxD0 = 0, iM0 = 0;
        for (var j0b = 0; j0b < absDy0.length; j0b++) if (absDy0[j0b] > mxD0) { mxD0 = absDy0[j0b]; iM0 = j0b; }
        result.center = xs[iM0];
        result.method = 'boxerf: derivPeak (fallback, R2=' + (beFit ? beFit.r2.toFixed(3) : 'N/A') + ')';
      }
    }

    else if (algo === 'halfcut') {
      var dy = numDeriv(xs, ys, true);
      var absDy = new Array(dy.length);
      for (var j = 0; j < dy.length; j++) absDy[j] = Math.abs(dy[j]);
      absDy = sgSmooth(absDy, 3);
      result.derivative = dy;
      var fit = gaussianFit(xs, absDy, {smooth: false});
      if (fit && fit.r2 > 0.3) {
        result.center = fit.center;
        result.sigma = fit.sigma;
        result.fwhm = fit.fwhm;
        result.fit = fit;
        result.method = 'halfcut: d/dx->|deriv|->gaussFit (R2=' + fit.r2.toFixed(3) + ')';
      } else {
        var mxD = 0, iM = 0;
        for (var j2 = 0; j2 < absDy.length; j2++) if (absDy[j2] > mxD) { mxD = absDy[j2]; iM = j2; }
        result.center = xs[iM];
        result.method = 'halfcut: derivPeak (fallback)';
      }
    }

    else if (algo === 'halfbeam') {
      var dy2 = numDeriv(xs, ys, true);
      dy2 = sgSmooth(dy2, 3);
      result.derivative = dy2;
      var maxDy = -Infinity, minDy = Infinity, iMaxDy = 0, iMinDy = 0;
      for (var j3 = 0; j3 < dy2.length; j3++) {
        if (dy2[j3] > maxDy) { maxDy = dy2[j3]; iMaxDy = j3; }
        if (dy2[j3] < minDy) { minDy = dy2[j3]; iMinDy = j3; }
      }
      var dyRange = maxDy - minDy;
      var hasTwoEdges = maxDy > dyRange * 0.15 && Math.abs(minDy) > dyRange * 0.15
                        && Math.abs(iMaxDy - iMinDy) > 3;
      if (hasTwoEdges) {
        var iLo = Math.min(iMaxDy, iMinDy), iHi = Math.max(iMaxDy, iMinDy);
        var mid = Math.floor((iLo + iHi) / 2);
        var xs1 = xs.slice(0, mid+1), dy1 = dy2.slice(0, mid+1);
        var fit1 = gaussianFit(xs1, dy1, {smooth: false});
        var xs2 = xs.slice(mid), dy2neg = [];
        for (var j4 = mid; j4 < dy2.length; j4++) dy2neg.push(-dy2[j4]);
        var fit2 = gaussianFit(xs2, dy2neg, {smooth: false});
        if (fit1 && fit2 && fit1.r2 > 0.3 && fit2.r2 > 0.3) {
          result.center = (fit1.center + fit2.center) / 2;
          result.edges = [fit1.center, fit2.center];
          result.gapWidth = Math.abs(fit2.center - fit1.center);
          result.sigma = (fit1.sigma + fit2.sigma) / 2;
          result.fwhm = (fit1.fwhm + fit2.fwhm) / 2;
          result.fit = {edge1: fit1, edge2: fit2};
          result.method = 'halfbeam: dualEdge gaussFit (R2=' +
            fit1.r2.toFixed(2) + '/' + fit2.r2.toFixed(2) + ')';
        } else {
          result.center = (xs[iMaxDy] + xs[iMinDy]) / 2;
          result.method = 'halfbeam: dualEdge derivPeak (fallback)';
        }
      } else {
        var absDy2 = dy2.map(function(v){return Math.abs(v);});
        var fit3 = gaussianFit(xs, absDy2, {smooth: true});
        if (fit3 && fit3.r2 > 0.4) {
          result.center = fit3.center;
          result.sigma = fit3.sigma;
          result.fwhm = fit3.fwhm;
          result.fit = fit3;
          result.method = 'halfbeam: |deriv|->gaussFit (R2=' + fit3.r2.toFixed(3) + ')';
        } else {
          var mxD2 = 0, iM2 = 0;
          for (var j5 = 0; j5 < absDy2.length; j5++) if (absDy2[j5] > mxD2) { mxD2 = absDy2[j5]; iM2 = j5; }
          result.center = xs[iM2];
          result.method = 'halfbeam: derivPeak (fallback)';
        }
      }
    }

    else if (algo === 'rocking') {
      var fit4 = lorentzianFit(xs, ys, {smooth: true});
      if (fit4 && fit4.r2 > 0.4) {
        result.center = fit4.center;
        result.gamma = fit4.gamma;
        result.fwhm = fit4.fwhm;
        result.fit = fit4;
        result.method = 'rocking: lorentzianFit (R2=' + fit4.r2.toFixed(3) + ')';
      } else {
        var maxS = 0, iMax2 = 0;
        for (var j6 = 0; j6 < ys.length; j6++) if (ys[j6] > maxS) { maxS = ys[j6]; iMax2 = j6; }
        var center = xs[iMax2];
        if (iMax2 > 0 && iMax2 < ys.length-1) {
          var y0 = ys[iMax2-1], y1 = ys[iMax2], y2 = ys[iMax2+1];
          var step = xs[1] - xs[0];
          center = xs[iMax2] + (y0-y2)/(2*(y0-2*y1+y2)) * step;
        }
        result.center = center;
        result.method = 'rocking: parabolicInterp (fallback)';
      }
    }

    else if (algo === 'gaussian') {
      var fit5 = gaussianFit(xs, ys, {smooth: true});
      if (fit5 && fit5.r2 > 0.4) {
        result.center = fit5.center;
        result.sigma = fit5.sigma;
        result.fwhm = fit5.fwhm;
        result.fit = fit5;
        result.method = 'gaussianFit (R2=' + fit5.r2.toFixed(3) + ')';
      } else {
        var maxS2 = 0, iMax3 = 0;
        for (var j7 = 0; j7 < ys.length; j7++) if (ys[j7] > maxS2) { maxS2 = ys[j7]; iMax3 = j7; }
        result.center = xs[iMax3];
        result.method = 'peakFind (fallback)';
      }
    }

    else if (algo === 'centroid') {
      var sumS = 0, sumSP = 0;
      for (var j8 = 0; j8 < xs.length; j8++) { sumS += ys[j8]; sumSP += ys[j8] * xs[j8]; }
      var centroid = sumS > 0 ? sumSP / sumS : xs[Math.floor(xs.length/2)];
      result.centroid = centroid;
      var fit6 = gaussianFit(xs, ys, {smooth: true});
      if (fit6 && fit6.r2 > 0.6) {
        result.center = fit6.center;
        result.sigma = fit6.sigma;
        result.fwhm = fit6.fwhm;
        result.fit = fit6;
        result.method = 'centroid+gaussFit (R2=' + fit6.r2.toFixed(3) + ')';
      } else {
        result.center = centroid;
        result.method = 'centroid (no fit)';
      }
    }

    else if (algo === 'verify') {
      var minS = Infinity, maxS3 = -Infinity;
      for (var j9 = 0; j9 < ys.length; j9++) {
        if (ys[j9] < minS) minS = ys[j9];
        if (ys[j9] > maxS3) maxS3 = ys[j9];
      }
      result.signalRange = maxS3 - minS;
      result.relDrift = maxS3 > 0 ? (maxS3 - minS) / maxS3 : 0;
      result.stable = result.relDrift < 0.05;
      var fit7 = gaussianFit(xs, ys, {smooth: true});
      if (fit7 && fit7.r2 > 0.3) {
        result.center = fit7.center;
        result.fwhm = fit7.fwhm;
        result.fit = fit7;
      } else {
        var maxS4 = 0, iMax4 = 0;
        for (var j10 = 0; j10 < ys.length; j10++) if (ys[j10] > maxS4) { maxS4 = ys[j10]; iMax4 = j10; }
        result.center = xs[iMax4];
      }
      result.method = 'verify: drift=' + (result.relDrift*100).toFixed(1) + '% '
        + (result.stable ? 'STABLE' : 'UNSTABLE')
        + (fit7 ? ' R2=' + fit7.r2.toFixed(3) : '');
    }

    // ---- Range insufficiency detection ----
    // For peaked signals: check if peak is near scan edges or signal never drops to half-max
    if (algo !== 'verify' && algo !== 'halfcut' && algo !== 'halfbeam' && algo !== 'boxerf') {
      var nPtsCheck = xs.length;
      var edgeZone = Math.max(2, Math.floor(nPtsCheck * 0.15));
      var maxY = -Infinity, iMaxY = 0;
      for (var jR = 0; jR < ys.length; jR++) {
        if (ys[jR] > maxY) { maxY = ys[jR]; iMaxY = jR; }
      }
      // Peak near edge?
      var peakNearEdge = (iMaxY < edgeZone || iMaxY >= nPtsCheck - edgeZone);
      // Signal never drops to half-max?
      var halfMax = maxY * 0.5;
      var minY = Infinity;
      for (var jR2 = 0; jR2 < ys.length; jR2++) {
        if (ys[jR2] < minY) minY = ys[jR2];
      }
      var noHalfMax = (minY > halfMax && maxY > 0);
      // Combine: range insufficient if peak at edge, or if signal never reaches half-max and fit is poor
      var fitR2 = (result.fit && result.fit.r2 != null) ? result.fit.r2 : 0;
      result.peakNearEdge = peakNearEdge;
      result.noHalfMax = noHalfMax;
      result.rangeInsufficient = peakNearEdge || (noHalfMax && fitR2 < 0.5);
    }

    return result;
  };

  // ---- 7. Override standalone alignment functions ----

  // Helper: run a scan loop and return {positions, signals}
  async function _doAlignScan(motor, signalFn, range, nPts, onPoint) {
    var start = motor.value + range[0], end = motor.value + range[1];
    var step = (end - start) / (nPts - 1);
    var positions = [], signals = [];
    for (var i = 0; i < nPts; i++) {
      if (state._alignAborted) throw new Error('Alignment aborted');
      var p = start + i * step;
      await motor.moveTo(p);
      var s = signalFn(p);
      positions.push(p); signals.push(s);
      if (onPoint) onPoint(i, nPts, p, s, positions, signals);
      await (typeof _yieldAsync==='function'?_yieldAsync():new Promise(function(r){setTimeout(r,0);}));
    }
    return {positions: positions, signals: signals};
  }

  // Max auto-expansion attempts
  var MAX_RANGE_EXPAND = 2;

  window.alignCentroid = async function(motor, signalFn, range, nPts, label, onPoint) {
    log('info', 'Align [' + (label||motor.name) + ']: centroid+gaussFit scan');
    var curRange = range.slice();
    for (var attempt = 0; attempt <= MAX_RANGE_EXPAND; attempt++) {
      var scan = await _doAlignScan(motor, signalFn, curRange, nPts, onPoint);
      var res = analyzeAlignScan(scan.positions, scan.signals, 'centroid');
      if (!res.rangeInsufficient || attempt === MAX_RANGE_EXPAND) {
        await motor.moveTo(res.center);
        log('info', label + ': ' + res.method + ' center=' + res.center.toFixed(4)
          + (res.fwhm ? ' FWHM=' + res.fwhm.toFixed(4) : ''));
        return res;
      }
      curRange = [curRange[0] * 2, curRange[1] * 2];
      log('info', label + ': range expanded to [' + curRange[0].toFixed(1) + ', ' + curRange[1].toFixed(1) + ']');
    }
  };

  window.alignGaussianFit = async function(motor, signalFn, range, nPts, label, onPoint) {
    log('info', 'Align [' + (label||motor.name) + ']: gaussianFit scan');
    var curRange = range.slice();
    for (var attempt = 0; attempt <= MAX_RANGE_EXPAND; attempt++) {
      var scan = await _doAlignScan(motor, signalFn, curRange, nPts, onPoint);
      var res = analyzeAlignScan(scan.positions, scan.signals, 'gaussian');
      if (!res.rangeInsufficient || attempt === MAX_RANGE_EXPAND) {
        await motor.moveTo(res.center);
        log('info', label + ': ' + res.method + ' center=' + res.center.toFixed(4)
          + (res.fwhm ? ' FWHM=' + res.fwhm.toFixed(4) : ''));
        return res;
      }
      curRange = [curRange[0] * 2, curRange[1] * 2];
      log('info', label + ': range expanded to [' + curRange[0].toFixed(2) + ', ' + curRange[1].toFixed(2) + ']');
    }
  };

  window.alignHalfBeam = async function(motor, signalFn, range, nPts, label, onPoint) {
    log('info', 'Align [' + (label||motor.name) + ']: deriv->gaussFit scan');
    var scan = await _doAlignScan(motor, signalFn, range, nPts, onPoint);
    var res = analyzeAlignScan(scan.positions, scan.signals, 'halfbeam');
    await motor.moveTo(res.center);
    log('info', label + ': ' + res.method + ' center=' + res.center.toFixed(4)
      + (res.sigma ? ' sig=' + res.sigma.toFixed(4) : ''));
    return res;
  };

  window.alignRockingCurve = async function(motor, signalFn, range, nPts, label, onPoint) {
    log('info', 'Align [' + (label||motor.name) + ']: lorentzianFit scan');
    var curRange = range.slice();
    for (var attempt = 0; attempt <= MAX_RANGE_EXPAND; attempt++) {
      var scan = await _doAlignScan(motor, signalFn, curRange, nPts, onPoint);
      var res = analyzeAlignScan(scan.positions, scan.signals, 'rocking');
      if (!res.rangeInsufficient || attempt === MAX_RANGE_EXPAND) {
        await motor.moveTo(res.center);
        log('info', label + ': ' + res.method + ' peak=' + res.center.toFixed(4)
          + (res.fwhm ? ' FWHM=' + res.fwhm.toFixed(4) : ''));
        return res;
      }
      curRange = [curRange[0] * 2, curRange[1] * 2];
      log('info', label + ': range expanded to [' + curRange[0].toFixed(2) + ', ' + curRange[1].toFixed(2) + ']');
    }
  };

  // ---- 8. Post-process runMirrorAlign results with improved analysis ----
  var _prevRunMirrorAlign = window.runMirrorAlign;
  window.runMirrorAlign = async function(mirrorId, onStepStart, onPoint) {
    var results = await _prevRunMirrorAlign(mirrorId, onStepStart, onPoint);
    if (!results || !results.length) return results;

    var seq = window.MIRROR_ALIGN_SEQ[mirrorId];
    if (!seq || !seq.steps) return results;

    for (var i = 0; i < results.length; i++) {
      var res = results[i];
      if (!res.positions || !res.signals || res.positions.length < 5) continue;
      var step = seq.steps[i];
      if (!step || !step.algo) continue;

      var algo;
      var isWB = (mirrorId === 'm1' || mirrorId === 'dcm');
      if (step.algo === 'halfcut') algo = isWB ? 'boxerf' : 'halfcut';
      else if (step.algo === 'rocking') algo = (mirrorId === 'dcm') ? 'rocking' : 'gaussian';
      else if (step.algo === 'verify') algo = 'verify';
      else continue;

      var analysis = analyzeAlignScan(res.positions, res.signals, algo);

      res.center = analysis.center;
      if (analysis.fwhm !== undefined) res.fwhm = analysis.fwhm;
      if (analysis.sigma !== undefined) res.sigma = analysis.sigma;
      if (analysis.gamma !== undefined) res.gamma = analysis.gamma;
      if (analysis.fit) res.fit = analysis.fit;
      if (analysis.derivative) res.derivative = analysis.derivative;
      if (analysis.beamDrift !== undefined) res.beamDrift = analysis.beamDrift;
      if (analysis.stable !== undefined) res.stable = analysis.stable;
      if (analysis.relDrift !== undefined) res.relDrift = analysis.relDrift;
      res.method = analysis.method;

      if (algo === 'verify' && res.beamPos && res.beamPos.length > 0) {
        var bMin = Infinity, bMax = -Infinity;
        for (var j = 0; j < res.beamPos.length; j++) {
          if (res.beamPos[j] < bMin) bMin = res.beamPos[j];
          if (res.beamPos[j] > bMax) bMax = res.beamPos[j];
        }
        res.beamDrift = bMax - bMin;
        res.stable = res.beamDrift < 0.01 && res.relDrift < 0.05;
      }

      log('info', mirrorId + '/' + res.step + ' [re-analyzed]: ' + (res.method || '')
        + (res.center !== undefined ? ' center=' + res.center.toFixed(4) : '')
        + (res.fwhm !== undefined ? ' FWHM=' + res.fwhm.toFixed(4) : '')
        + (res.fit ? ' R2=' + res.fit.r2.toFixed(3) : ''));
    }

    return results;
  };

  console.log('[alignment/05_align_analysis] Alignment analysis engine loaded');
})();

// ESM bridge: expose module-scoped vars to globalThis
if(typeof _aat!=="undefined")globalThis._aat=_aat;
if(typeof _aatBuild!=="undefined")globalThis._aatBuild=_aatBuild;
if(typeof _aatCalcDeriv!=="undefined")globalThis._aatCalcDeriv=_aatCalcDeriv;
if(typeof _aatCalcSmooth!=="undefined")globalThis._aatCalcSmooth=_aatCalcSmooth;
if(typeof _aatCalcStats!=="undefined")globalThis._aatCalcStats=_aatCalcStats;
if(typeof _aatCopy!=="undefined")globalThis._aatCopy=_aatCopy;
if(typeof _aatDrawCanvas!=="undefined")globalThis._aatDrawCanvas=_aatDrawCanvas;
if(typeof _aatDrawStats!=="undefined")globalThis._aatDrawStats=_aatDrawStats;
if(typeof _aatDrawTable!=="undefined")globalThis._aatDrawTable=_aatDrawTable;
if(typeof _aatFWxM!=="undefined")globalThis._aatFWxM=_aatFWxM;
if(typeof _aatFWxMcoord!=="undefined")globalThis._aatFWxMcoord=_aatFWxMcoord;
if(typeof _aatFitBoxErf!=="undefined")globalThis._aatFitBoxErf=_aatFitBoxErf;
if(typeof _aatFitErf!=="undefined")globalThis._aatFitErf=_aatFitErf;
if(typeof _aatFitPoly!=="undefined")globalThis._aatFitPoly=_aatFitPoly;
if(typeof _aatRefresh!=="undefined")globalThis._aatRefresh=_aatRefresh;
if(typeof _aatRunFit!=="undefined")globalThis._aatRunFit=_aatRunFit;
if(typeof _aatTBtn!=="undefined")globalThis._aatTBtn=_aatTBtn;
if(typeof _aatTC!=="undefined")globalThis._aatTC=_aatTC;
if(typeof _sr!=="undefined")globalThis._sr=_sr;
if(typeof alignCentroid!=="undefined")globalThis.alignCentroid=alignCentroid;
if(typeof alignGaussianFit!=="undefined")globalThis.alignGaussianFit=alignGaussianFit;
if(typeof alignHalfBeam!=="undefined")globalThis.alignHalfBeam=alignHalfBeam;
if(typeof alignRockingCurve!=="undefined")globalThis.alignRockingCurve=alignRockingCurve;
if(typeof analyzeAlignScan!=="undefined")globalThis.analyzeAlignScan=analyzeAlignScan;
if(typeof boxErfFit!=="undefined")globalThis.boxErfFit=boxErfFit;
if(typeof gaussianFit!=="undefined")globalThis.gaussianFit=gaussianFit;
if(typeof lorentzianFit!=="undefined")globalThis.lorentzianFit=lorentzianFit;
if(typeof numDeriv!=="undefined")globalThis.numDeriv=numDeriv;
if(typeof runMirrorAlign!=="undefined")globalThis.runMirrorAlign=runMirrorAlign;
if(typeof sgSmooth!=="undefined")globalThis.sgSmooth=sgSmooth;
if(typeof solveLinear!=="undefined")globalThis.solveLinear=solveLinear;
if(typeof toggleAlignAnalysis!=="undefined")globalThis.toggleAlignAnalysis=toggleAlignAnalysis;
