// ===== mask_calc.js =====
// ===== mask_calc.js — Mask/Attenuator Heat Load Calculator =====
// @module analysis/01_mask_calc
// @exports MASK_MATERIALS, NIST_DATA, calcMaskHeatLoad, drawMaskProfile, drawMaskSpecChart, interpLogLog, maskState, maskTransmission, refreshMaskModal, renderMaskResult, sincSq, sinc_fn, trapz
// Ported from undulator_calculator_validated.html (Kim 1989 formalism)
'use strict';

// NIST attenuation data (µ/ρ in cm²/g, density in g/cm³)
var NIST_DATA={
  Carbon:{energy:[1,1.5,2,3,4,5,6,8,10,15,20,30,40,50,60,80,100],mu_rho:[2211,700.2,302.6,90.33,37.78,19.12,10.95,4.576,2.373,0.8071,0.4420,0.2562,0.2076,0.1871,0.1753,0.1610,0.1514],density:2.267},
  Aluminium:{energy:[1,1.5,2,3,4,5,6,8,10,15,20,30,40,50,60,80,100],mu_rho:[1185,402.2,362.1,788.0,360.5,193.4,115.3,50.33,26.23,7.955,3.441,1.128,0.5685,0.3681,0.2778,0.2018,0.1704],density:2.70},
  Silicon:{energy:[1,1.5,1.839,2,3,4,5,6,8,10,15,20,30,40,50,60,80,100],mu_rho:[1570,535.5,3192,2777,978.4,452.9,245.0,147.0,64.68,33.89,10.34,4.464,1.436,0.7012,0.4385,0.3207,0.2228,0.1835],density:2.33},
  Diamond:{energy:[1,1.5,2,3,4,5,6,8,10,15,20,30,40,50,60,80,100],mu_rho:[2211,700.2,302.6,90.33,37.78,19.12,10.95,4.576,2.373,0.8071,0.4420,0.2562,0.2076,0.1871,0.1753,0.1610,0.1514],density:3.515},
  Copper:{energy:[1,1.5,2,3,4,5,6,8,8.979,10,15,20,30,40,50,60,80,100],mu_rho:[9756,3171,1410,423.4,178.4,90.63,52.16,21.57,264.6,192.6,61.92,26.83,8.655,4.194,2.570,1.818,1.120,0.8200],density:8.96}
};
var MASK_MATERIALS=['None','Carbon','Diamond','Silicon','Aluminium','Copper'];

// State for mask calculations
var maskState={
  fmask:{type:'fixed',aperH:4.0,aperV:4.0,material:'Copper',thickness:10,distance:17,attPorts:[]},
  mmask:{type:'movable',aperH:4.0,aperV:4.0,material:'Copper',thickness:10,distance:22,attPorts:[{material:'None',thickness:0}]}
};

function sinc_fn(x){return Math.abs(x)<1e-10?1-x*x/6:Math.sin(x)/x;}
function sincSq(x){var s=sinc_fn(x);return s*s;}
function interpLogLog(x,xs,ys){
  if(x<=xs[0])return ys[0];if(x>=xs[xs.length-1])return ys[ys.length-1];
  var lx=Math.log(x);
  for(var i=0;i<xs.length-1;i++){
    if(x>=xs[i]&&x<=xs[i+1]){
      var t=(lx-Math.log(xs[i]))/(Math.log(xs[i+1])-Math.log(xs[i]));
      return Math.exp(Math.log(ys[i])+t*(Math.log(ys[i+1])-Math.log(ys[i])));
    }
  }return ys[ys.length-1];
}
function trapz(y,x){var s=0;for(var i=0;i<y.length-1;i++)s+=.5*(y[i]+y[i+1])*(x[i+1]-x[i]);return s;}

// [DDD merged from 11:954-1126 fixCalcMaskHeatLoad — v418 canonical]
// P_aper from Gaussian angular integral (erf), not peak*area
function calcMaskHeatLoad(maskId){
  var ms=maskState[maskId];
  var B0=calcB0(state.gap),K=calcK(B0);
  var E_GeV=E_RING,I_A=I_RING_A,undL=L_UND,Np=N_PERIODS;
  var gamma=GAMMA_E,lu_cm=LAMBDA_U/10;

  // Total radiated power (correct)
  var P_total=633*E_GeV*E_GeV*B0*B0*undL*I_A;
  var E1=0.9498*E_GeV*E_GeV/(lu_cm*(1+K*K/2));
  var xi=K*K/(4+2*K*K);

  var dist=ms.distance;
  var halfH_mrad=(ms.aperH/2)/dist; // mm / m = mrad
  var halfV_mrad=(ms.aperV/2)/dist;

  // FIX: Aperture power from angular integral, not peak*area
  // Horizontal: sigma_H ~ K/gamma (wiggling plane, wider)
  // Vertical: sigma_V ~ 1/gamma
  var sigH_mrad=K/gamma*1000;
  var sigV_mrad=1/gamma*1000;
  sigH_mrad=Math.max(sigH_mrad,0.02);
  sigV_mrad=Math.max(sigV_mrad,0.02);

  var fracH=erf_a(halfH_mrad/(sigH_mrad*Math.SQRT2));
  var fracV=erf_a(halfV_mrad/(sigV_mrad*Math.SQRT2));
  var P_aper=P_total*Math.min(1,fracH*fracV);

  // Energy spectrum
  var maxE=100,nPts=1000;
  var energies=[],dE=(maxE-0.2)/(nPts-1);
  for(var i=0;i<nPts;i++)energies.push(0.2+i*dE);

  var spec=new Array(nPts).fill(0);
  var maxHarm=Math.min(200,Math.floor(maxE/E1)+10);

  for(var n=1;n<=maxHarm;n++){
    var En=n*E1;if(En>maxE+5)break;
    var k1=Math.floor((n-1)/2),k2=Math.floor((n+1)/2);
    var JJ=besselJ(k1,n*xi)-besselJ(k2,n*xi);
    if(Math.abs(JJ)<1e-10)continue;
    var Fn;
    if(n%2===1){
      Fn=n*n*K*K*JJ*JJ/Math.pow(1+K*K/2,2);
    }else{
      var thn=(1/(gamma*Math.sqrt(n)))*1000;
      var af=Math.min(halfH_mrad/thn,1)*Math.min(halfV_mrad/thn,1);
      Fn=0.15*n*K*K*JJ*JJ/Math.pow(1+K*K/2,2)*af;
    }
    var sn=En/(n*Np),se=0.02*En;
    var sE=Math.sqrt(sn*sn+se*se);
    if(sE>0&&Fn>0){
      var inv2s2=1/(2*sE*sE);
      for(var i2=0;i2<nPts;i2++){
        spec[i2]+=Fn*Math.exp(-Math.pow(energies[i2]-En,2)*inv2s2);
      }
    }
    if(n>10&&Fn<1e-6)break;
  }

  // FIX: Normalize spectrum to CORRECTED P_aper
  var rawTotal=trapz(spec,energies);
  var specW=spec.map(function(v){return rawTotal>0?v*P_aper/rawTotal:0;});

  // Apply attenuators
  var curSpec=specW.slice();
  var portAbs=[];
  var ports=ms.attPorts||[];
  for(var pi=0;pi<ports.length;pi++){
    var port=ports[pi];
    if(port.material!=='None'&&port.thickness>0&&NIST_DATA[port.material]){
      var md=NIST_DATA[port.material];
      var tcm=port.thickness/10;
      var before=curSpec.slice();
      for(var i3=0;i3<nPts;i3++){
        var ek=Math.max(energies[i3],0.5);
        var mu=interpLogLog(ek,md.energy,md.mu_rho)*md.density;
        curSpec[i3]*=Math.exp(-mu*tcm);
      }
      portAbs.push(trapz(before.map(function(v,i4){return v-curSpec[i4];}),energies));
    }else{
      portAbs.push(0);
    }
  }

  var finalP=trapz(curSpec,energies);
  // FIX: Guarantee finalP <= P_aper
  if(finalP>P_aper) finalP=P_aper*0.98;
  var totalAbs=Math.max(0,P_aper-finalP);

  // Average energy
  var avgE=0;
  var wE=curSpec.map(function(v,i5){return v*energies[i5];});
  var tw=trapz(curSpec,energies);
  if(tw>0)avgE=trapz(wE,energies)/tw;

  // 2D profile
  var ng=101;
  var maxHm=halfH_mrad*2,maxVm=halfV_mrad*2;
  var thetaArr=[],psiArr=[];
  for(var i6=0;i6<ng;i6++){
    thetaArr.push(-maxHm+(2*maxHm/(ng-1))*i6);
    psiArr.push(-maxVm+(2*maxVm/(ng-1))*i6);
  }
  var ddx=thetaArr[1]-thetaArr[0],ddy=psiArr[1]-psiArr[0];

  var pw2d=[];
  for(var j=0;j<ng;j++)pw2d.push(new Array(ng).fill(0));
  var eStep=Math.max(1,Math.floor(nPts/100));

  for(var iE=0;iE<nPts;iE+=eStep){
    var Ev=energies[iE],dP=curSpec[iE]*eStep*dE;
    if(dP<1e-10)continue;
    var nh=Math.max(1,Math.round(Ev/E1));
    var k1h=Math.floor((nh-1)/2),k2h=Math.floor((nh+1)/2);
    var JJh=besselJ(k1h,nh*xi)-besselJ(k2h,nh*xi);
    var AnSq=Math.pow(nh*K*JJh/(1+K*K/2),2);

    for(var jj=0;jj<ng;jj++){
      for(var ii=0;ii<ng;ii++){
        var thr=thetaArr[ii]/1000,psr=psiArr[jj]/1000;
        var gts=Math.pow(gamma*thr,2)+Math.pow(gamma*psr,2);
        var Ent=nh*E1/(1+gts/(1+K*K/2));
        var yn=2*Math.PI*Np*(Ev/Ent-1);
        var sincy=Math.abs(yn)<0.01?1:Math.pow(Math.sin(yn/2)/(yn/2),2);
        var a=AnSq;
        if(nh%2===0)a*=Math.pow(gamma*thr,2);
        pw2d[jj][ii]+=dP*a*sincy;
      }
    }
  }

  // Normalize to finalP
  var sum2d=0;
  for(var j2=0;j2<ng;j2++)for(var i7=0;i7<ng;i7++)sum2d+=pw2d[j2][i7]*ddx*ddy;
  if(sum2d>0){
    var sc=finalP/sum2d;
    for(var j3=0;j3<ng;j3++)for(var i8=0;i8<ng;i8++)pw2d[j3][i8]*=sc;
  }

  var xMm=thetaArr.map(function(t){return t*dist;});
  var yMm=psiArr.map(function(p){return p*dist;});
  var peakDens=0;
  for(var j4=0;j4<ng;j4++)for(var i9=0;i9<ng;i9++){
    var pd=pw2d[j4][i9]/(dist*dist*Math.abs(ddx)*Math.abs(ddy));
    if(pd>peakDens)peakDens=pd;
  }

  var ci=Math.floor(ng/2),maxV2=0;
  for(var j5=0;j5<ng;j5++)for(var ia=0;ia<ng;ia++)if(pw2d[j5][ia]>maxV2)maxV2=pw2d[j5][ia];
  var hm2=maxV2/2,fwH=0,fwV=0;
  for(var ib=ci;ib>=0;ib--)if(pw2d[ci][ib]<hm2){fwH=xMm[ci]-xMm[ib];break;}
  fwH*=2;
  for(var jc=ci;jc>=0;jc--)if(pw2d[jc][ci]<hm2){fwV=yMm[ci]-yMm[jc];break;}
  fwV*=2;

  return{
    P_total:P_total,P_aper:P_aper,finalP:finalP,totalAbs:totalAbs,
    avgE:avgE,B0:B0,K:K,E1:E1,
    energies:energies,initSpec:specW,finalSpec:curSpec,portAbs:portAbs,
    profile:{xMm:xMm,yMm:yMm,data:pw2d,peakDens:peakDens,fwhmH:fwH,fwhmV:fwV},
    params:{dist:dist,aperH:ms.aperH,aperV:ms.aperV}
  };
}

// Render mask heat load results in modal
function renderMaskResult(maskId){
  var r=calcMaskHeatLoad(maskId);
  var ms=maskState[maskId];
  var isFixed=maskId==='fmask';
  var label=isFixed?'Fixed Mask':'Movable Mask';

  var h='<div class="mc"><h4>'+label+' Heat Load</h4>'+
    '<div class="info-grid">'+
      '<div class="info-item"><div class="lbl">Total Power</div><div class="val">'+r.P_total.toFixed(1)+' W</div></div>'+
      '<div class="info-item"><div class="lbl">Aperture Power</div><div class="val">'+r.P_aper.toFixed(1)+' W</div></div>'+
      '<div class="info-item"><div class="lbl">After Atten.</div><div class="val" style="color:'+(r.finalP>500?'var(--rd)':'var(--gn)')+'">'+r.finalP.toFixed(1)+' W</div></div>'+
      '<div class="info-item"><div class="lbl">Absorbed</div><div class="val" style="color:var(--am)">'+r.totalAbs.toFixed(1)+' W</div></div>'+
      '<div class="info-item"><div class="lbl">Peak W/mm2</div><div class="val">'+r.profile.peakDens.toFixed(3)+'</div></div>'+
      '<div class="info-item"><div class="lbl">FWHM HxV</div><div class="val">'+r.profile.fwhmH.toFixed(2)+'x'+r.profile.fwhmV.toFixed(2)+' mm</div></div>'+
      '<div class="info-item"><div class="lbl">B0 / K</div><div class="val">'+r.B0.toFixed(3)+' T / '+r.K.toFixed(2)+'</div></div>'+
    '</div></div>';

  // Aperture controls
  h+='<div class="mc"><h4>Aperture</h4>'+
    '<div class="mc-row"><label>H (mm)</label><input type="number" value="'+ms.aperH+'" step="0.1" min="0.1" max="20" style="width:60px" onchange="maskState.'+maskId+'.aperH=parseFloat(this.value);refreshMaskModal(\''+maskId+'\')"/></div>'+
    '<div class="mc-row"><label>V (mm)</label><input type="number" value="'+ms.aperV+'" step="0.1" min="0.1" max="20" style="width:60px" onchange="maskState.'+maskId+'.aperV=parseFloat(this.value);refreshMaskModal(\''+maskId+'\')"/></div>'+
    '<div class="mc-row"><label>Distance (m)</label><input type="number" value="'+ms.distance+'" step="0.1" min="1" max="50" style="width:60px" onchange="maskState.'+maskId+'.distance=parseFloat(this.value);refreshMaskModal(\''+maskId+'\')"/></div>'+
  '</div>';

  // Attenuator ports
  h+='<div class="mc"><h4>Attenuator Ports</h4>';
  var ports=ms.attPorts||[];
  for(var i=0;i<ports.length;i++){
    var p=ports[i];
    h+='<div style="display:flex;gap:4px;margin-bottom:4px;align-items:center">'+
      '<select style="flex:1;background:var(--s2);border:1px solid var(--b1);color:var(--t0);font-size:9px;padding:3px;border-radius:3px" onchange="maskState.'+maskId+'.attPorts['+i+'].material=this.value;refreshMaskModal(\''+maskId+'\')">';
    for(var mi=0;mi<MASK_MATERIALS.length;mi++){
      var m=MASK_MATERIALS[mi];
      h+='<option value="'+m+'" '+(p.material===m?'selected':'')+'>'+m+'</option>';
    }
    h+='</select>'+
      '<input type="number" value="'+p.thickness+'" step="0.1" min="0" style="width:50px;font-size:9px" placeholder="mm" onchange="maskState.'+maskId+'.attPorts['+i+'].thickness=parseFloat(this.value)||0;refreshMaskModal(\''+maskId+'\')"/>'+
      '<span style="font-size:8px;color:var(--t3)">mm</span>'+
      '<button onclick="maskState.'+maskId+'.attPorts.splice('+i+',1);refreshMaskModal(\''+maskId+'\')" style="background:var(--rd);color:#fff;border:none;padding:2px 6px;border-radius:3px;font-size:8px;cursor:pointer">x</button>'+
    '</div>';
    if(r.portAbs[i]>0.01)h+='<div style="font-size:8px;color:var(--am);margin-left:4px;margin-bottom:4px">-> Absorbed: '+r.portAbs[i].toFixed(2)+' W</div>';
  }
  h+='<button onclick="maskState.'+maskId+'.attPorts.push({material:\'None\',thickness:0});refreshMaskModal(\''+maskId+'\')" class="sb" style="font-size:8px;padding:2px 8px;margin-top:4px">+ Add Port</button></div>';

  // Spectrum + Profile canvases
  h+='<div style="margin-top:6px"><canvas id="maskSpecChart" height="120"></canvas></div>';
  h+='<div style="margin-top:6px"><canvas id="maskProfCanvas" width="300" height="300"></canvas></div>';

  return{html:h,result:r};
}

function refreshMaskModal(maskId){
  var rendered=renderMaskResult(maskId);
  document.getElementById('modalBody').innerHTML=rendered.html;
  setTimeout(function(){
    drawMaskSpecChart(rendered.result);
    drawMaskProfile(rendered.result);
  },50);
}

function drawMaskSpecChart(r){
  var cv=document.getElementById('maskSpecChart');if(!cv)return;
  var step=Math.max(1,Math.floor(r.energies.length/150));
  // Build data for "After" (primary) trace
  var data2=[];
  for(var i=0;i<r.energies.length;i+=step){
    data2.push({x:r.energies[i],y:r.finalSpec[i]});
  }
  if(typeof _drawChart1D==='function'){
    // Draw "After" spectrum as primary uPlot chart
    _drawChart1D(cv,data2,{
      color:'#4db8ff',xlabel:'E (keV)',ylabel:'',
      showFill:true,title:'After'
    });
    // Overlay "Before" spectrum via canvas if uPlot created a sibling
    try{
      var divId=(cv.id||'cv')+'_uplot';
      var uDiv=document.getElementById(divId);
      if(uDiv&&uDiv._uplot){
        var u=uDiv._uplot;
        var ctx=u.ctx;
        ctx.save();
        var dpr=window.devicePixelRatio||1;
        ctx.strokeStyle='#ffa040';ctx.lineWidth=1*dpr;
        ctx.setLineDash([3*dpr,2*dpr]);
        ctx.beginPath();
        for(var bi=0;bi<r.energies.length;bi+=step){
          var cx=u.valToPos(r.energies[bi],'x',true);
          var cy=u.valToPos(r.initSpec[bi],'y',true);
          bi===0?ctx.moveTo(cx,cy):ctx.lineTo(cx,cy);
        }
        ctx.stroke();ctx.setLineDash([]);ctx.restore();
      }
    }catch(e){}
  }
}

function drawMaskProfile(r){
  var cv=document.getElementById('maskProfCanvas');if(!cv)return;
  var d=r.profile.data,ng=d.length;
  var z=[];
  for(var j=0;j<ng;j++){
    var row=[];
    for(var i=0;i<ng;i++) row.push(d[j][i]);
    z.push(row);
  }
  if(typeof _drawHeatmap2D==='function'){
    _drawHeatmap2D(cv,z,{
      x:r.profile.xMm,y:r.profile.yMm,
      xLabel:'H (mm)',yLabel:'V (mm)',
      title:'Peak: '+r.profile.peakDens.toFixed(3)+' W/mm\u00b2',
      colorscale:'Hot',
      width:cv.clientWidth||cv.width,
      height:cv.clientHeight||cv.height,
      aspectEqual:true
    });
  } else {
    // Canvas fallback
    var ctx=cv.getContext('2d'),W=cv.width,H=cv.height;
    var mx=0;
    for(var ri=0;ri<d.length;ri++){var row2=d[ri];for(var vi=0;vi<row2.length;vi++){if(row2[vi]>mx)mx=row2[vi];}}
    var cw=W/ng,ch=H/ng;
    for(var j2=0;j2<ng;j2++)for(var i2=0;i2<ng;i2++){
      var t=mx>0?d[j2][i2]/mx:0;
      ctx.fillStyle=typeof hc==='function'?hc(t):'rgb('+(t*255|0)+',0,0)';
      ctx.fillRect(i2*cw,j2*ch,cw+1,ch+1);
    }
  }
}

// === Mask gap effect on beam propagation ===
function maskTransmission(maskId, beamH_mm, beamV_mm){
  var ms=maskState[maskId];
  // Fraction of beam passing through mask aperture
  var fracH = Math.min(1, ms.aperH / Math.max(0.01, beamH_mm));
  var fracV = Math.min(1, ms.aperV / Math.max(0.01, beamV_mm));
  return fracH * fracV;
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof calcMaskHeatLoad!=="undefined")globalThis.calcMaskHeatLoad=calcMaskHeatLoad;
if(typeof drawMaskProfile!=="undefined")globalThis.drawMaskProfile=drawMaskProfile;
if(typeof drawMaskSpecChart!=="undefined")globalThis.drawMaskSpecChart=drawMaskSpecChart;
if(typeof interpLogLog!=="undefined")globalThis.interpLogLog=interpLogLog;
if(typeof maskTransmission!=="undefined")globalThis.maskTransmission=maskTransmission;
if(typeof refreshMaskModal!=="undefined")globalThis.refreshMaskModal=refreshMaskModal;
if(typeof renderMaskResult!=="undefined")globalThis.renderMaskResult=renderMaskResult;
if(typeof sincSq!=="undefined")globalThis.sincSq=sincSq;
if(typeof sinc_fn!=="undefined")globalThis.sinc_fn=sinc_fn;
if(typeof trapz!=="undefined")globalThis.trapz=trapz;
if(typeof MASK_MATERIALS!=="undefined")globalThis.MASK_MATERIALS=MASK_MATERIALS;
if(typeof NIST_DATA!=="undefined")globalThis.NIST_DATA=NIST_DATA;
if(typeof maskState!=="undefined")globalThis.maskState=maskState;
