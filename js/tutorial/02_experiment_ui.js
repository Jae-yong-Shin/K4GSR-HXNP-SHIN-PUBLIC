'use strict';
// ===== tutorial/02_experiment_ui.js — Enhanced Experiment Workflow =====
// @module tutorial/02_experiment_ui
// @exports EXP_WF, addWorkflowButton2, draw2DScanResult2, drawDiffPattern, drawRealisticMicroscope, genDiffPattern, genVoronoiGrains, openExpWorkflow, runFinalMeas2, runWfScan2, setupMicroDrag2, setupScanDrag2, showWfStep, sim2DScanXRD, wfConfirmRoi, ...
// Extracted from 11_v433_fixes.js (DDD Phase 4)
// Realistic microscopy, Voronoi grains, per-pixel XRD, workflow steps

var EXP_WF={step:0,roi:null,scanData:null,subRoi:null,features:null,diffPatterns:null,finalData:null,finalType:'xanes',scanType:'xrf',scanRes:101};

// ============ Realistic Microscope Image ============
function genVoronoiGrains(n,w,h){
  var seeds=[];for(var i=0;i<n;i++) seeds.push({x:Math.random()*w,y:Math.random()*h,
    phase:Math.floor(Math.random()*5),orient:Math.random()*Math.PI,
    elem:['Fe','Cu','Ni','Ti','Au'][Math.floor(Math.random()*5)]});
  // Assign pixels to nearest seed (Voronoi)
  var grid=[];for(var y=0;y<h;y++){var row=[];for(var x=0;x<w;x++){
    var best=0,bd=1e9;for(var i=0;i<seeds.length;i++){
      var dx=x-seeds[i].x,dy=y-seeds[i].y,d=dx*dx+dy*dy;if(d<bd){bd=d;best=i;}}
    row.push(best);}grid.push(row);}
  return{seeds:seeds,grid:grid,w:w,h:h};
}

function drawRealisticMicroscope(cv,roi){
  var ctx=cv.getContext('2d'),w=cv.width,h=cv.height;
  if(!EXP_WF.features) EXP_WF.features=genVoronoiGrains(60,w,h);
  var F=EXP_WF.features,seeds=F.seeds,grid=F.grid;
  // Phase colors (DIC microscopy style)
  var pc=[[45,55,70],[55,45,70],[40,65,55],[65,50,45],[50,50,65]];
  var img=ctx.createImageData(w,h);
  for(var y=0;y<h;y++) for(var x=0;x<w;x++){
    var gi=grid[y][x],s=seeds[gi],p=s.phase;
    // Orientation-dependent shade (crossed polarizers effect)
    var ang=Math.atan2(y-s.y,x-s.x)+s.orient;
    var shade=0.7+0.3*Math.cos(2*ang);
    // Distance to grain boundary
    var onBound=false;
    if(x>0&&grid[y][x-1]!==gi) onBound=true;
    if(y>0&&grid[y-1][x]!==gi) onBound=true;
    if(x<w-1&&grid[y][x+1]!==gi) onBound=true;
    if(y<h-1&&grid[y+1][x]!==gi) onBound=true;
    var r,g,b;
    if(onBound){r=20;g=25;b=30;}
    else{r=pc[p][0]*shade+Math.random()*8;g=pc[p][1]*shade+Math.random()*8;b=pc[p][2]*shade+Math.random()*8;}
    var i=(y*w+x)*4;img.data[i]=r|0;img.data[i+1]=g|0;img.data[i+2]=b|0;img.data[i+3]=255;
  }
  ctx.putImageData(img,0,0);
  // Inclusions/precipitates
  for(var k=0;k<40;k++){var ix=Math.random()*w,iy=Math.random()*h,ir=2+Math.random()*6;
    var ec={Fe:'#ff5533',Cu:'#33aaff',Ni:'#55ff77',Au:'#ffcc22',Ti:'#bb66ff'}[seeds[grid[Math.min(h-1,iy|0)][Math.min(w-1,ix|0)]].elem];
    ctx.beginPath();ctx.arc(ix,iy,ir,0,Math.PI*2);ctx.fillStyle=ec||'#888';ctx.globalAlpha=0.6;ctx.fill();ctx.globalAlpha=1;}
  // Twin boundaries (straight lines within grains)
  ctx.strokeStyle='rgba(120,140,160,0.25)';ctx.lineWidth=0.5;
  for(var k=0;k<15;k++){var sx=Math.random()*w,sy=Math.random()*h,a=seeds[grid[sy|0][sx|0]].orient;
    ctx.beginPath();ctx.moveTo(sx-50*Math.cos(a),sy-50*Math.sin(a));
    ctx.lineTo(sx+50*Math.cos(a),sy+50*Math.sin(a));ctx.stroke();}
  // Scale bar
  ctx.fillStyle='rgba(255,255,255,0.9)';ctx.fillRect(w-120,h-18,90,2);
  ctx.fillRect(w-120,h-22,1,8);ctx.fillRect(w-31,h-22,1,8);
  ctx.font='10px monospace';ctx.fillText('50 \u00b5m',w-115,h-25);
  // Crosshair
  ctx.strokeStyle='rgba(255,255,255,0.15)';ctx.setLineDash([4,4]);
  ctx.beginPath();ctx.moveTo(w/2,0);ctx.lineTo(w/2,h);ctx.stroke();
  ctx.beginPath();ctx.moveTo(0,h/2);ctx.lineTo(w,h/2);ctx.stroke();ctx.setLineDash([]);
  // ROI
  if(roi){ctx.strokeStyle='#ff0';ctx.lineWidth=2;ctx.setLineDash([6,3]);
    ctx.strokeRect(roi.x,roi.y,roi.w,roi.h);ctx.setLineDash([]);
    ctx.fillStyle='rgba(255,255,0,0.06)';ctx.fillRect(roi.x,roi.y,roi.w,roi.h);
    ctx.fillStyle='#ff0';ctx.font='10px monospace';
    var um=roi.w/w*500; // 500µm field of view
    ctx.fillText('ROI: '+um.toFixed(0)+'x'+(roi.h/h*500).toFixed(0)+' \u00b5m',roi.x,roi.y-4);}
}

// ============ XRD Diffraction Pattern Generator ============
function genDiffPattern(x,y,w){
  // Simulate powder/single-crystal diffraction on 2D detector
  var n=128,pat=[];
  var gi=0;if(EXP_WF.features){var gx=Math.round(x/500*EXP_WF.features.w);
    var gy=Math.round(y/500*EXP_WF.features.h);
    gx=Math.max(0,Math.min(EXP_WF.features.w-1,gx));gy=Math.max(0,Math.min(EXP_WF.features.h-1,gy));
    gi=EXP_WF.features.grid[gy][gx];}
  var orient=EXP_WF.features?EXP_WF.features.seeds[gi].orient:0;
  var phase=EXP_WF.features?EXP_WF.features.seeds[gi].phase:0;
  for(var j=0;j<n;j++){var row=new Float32Array(n);for(var i=0;i<n;i++){
    var dx=i-n/2,dy=j-n/2,r=Math.sqrt(dx*dx+dy*dy),ang=Math.atan2(dy,dx);
    // Debye-Scherrer rings at specific radii
    var rings=[18,25,32,38,44,52];var v=2+Math.random()*3;
    rings.forEach(function(rr,ri){var dr=r-rr-phase*1.5;
      v+=Math.max(0,(200-ri*25)*Math.exp(-dr*dr/3));
      // Texture: modulate by orientation
      v*=1+0.4*Math.cos(2*(ang-orient-ri*0.3));});
    // Laue spots for single-crystal-like regions
    if(phase<2){var nSpots=3+phase*2;for(var si=0;si<nSpots;si++){
      var sa=orient+si*Math.PI*2/nSpots,sr=20+si*7;
      var sdx=i-n/2-sr*Math.cos(sa),sdy=j-n/2-sr*Math.sin(sa);
      v+=500*Math.exp(-(sdx*sdx+sdy*sdy)/8);}}
    // Beam stop
    if(r<5) v=0;
    row[i]=Math.max(0,v);}pat.push(row);}
  return pat;
}

function drawDiffPattern(cv,pat){
  var n=pat.length;
  if(typeof _drawHeatmap2D==='function'&&typeof Plotly!=='undefined'){
    var z=[];
    for(var j=0;j<n;j++){
      var row=[];
      for(var i=0;i<n;i++) row.push(Math.sqrt(Math.max(0,pat[j][i])));
      z.push(row);
    }
    _drawHeatmap2D(cv,z,{
      title:'2D Detector ('+n+'x'+n+')',
      colorscale:[[0,'#000'],[0.25,'#003c1e'],[0.5,'#00805a'],[0.75,'#00b4e0'],[1,'#33ff00']],
      width:cv.clientWidth||cv.width,
      height:cv.clientHeight||cv.height,
      aspectEqual:true
    });
  } else {
    // Canvas fallback (original code)
    var ctx=cv.getContext('2d'),w=cv.width,h=cv.height;
    var mn=Infinity,mx=-Infinity;
    pat.forEach(function(r){r.forEach(function(v){if(v<mn)mn=v;if(v>mx)mx=v;});});
    var rng=mx-mn||1,img=ctx.createImageData(w,h);
    for(var j2=0;j2<h;j2++) for(var i2=0;i2<w;i2++){
      var si=Math.floor(i2/w*n),sj=Math.floor(j2/h*n);
      var t=Math.sqrt((pat[sj][si]-mn)/rng);
      var idx=(j2*w+i2)*4;
      img.data[idx]=t*60|0;img.data[idx+1]=t*180|0;img.data[idx+2]=t*255|0;img.data[idx+3]=255;}
    ctx.putImageData(img,0,0);
    ctx.fillStyle='rgba(255,255,255,0.7)';ctx.font='9px monospace';
    ctx.fillText('2D Detector ('+n+'x'+n+')',4,12);
    ctx.fillText('Beam stop',w/2-20,h/2+20);
  }
}

// ============ 2D Scan with per-pixel diffraction ============
function sim2DScanXRD(roi,nx,ny){
  var d=[],xP=[],yP=[],diffs=[];
  var dx=roi.w/(nx-1),dy=roi.h/(ny-1);
  for(var i=0;i<nx;i++) xP.push(roi.x+i*dx);
  for(var j=0;j<ny;j++) yP.push(roi.y+j*dy);
  for(var j=0;j<ny;j++){var row=[],drow=[];
    for(var i=0;i<nx;i++){
      var pat=genDiffPattern(xP[i],yP[j],500);
      var sum=0;pat.forEach(function(r){r.forEach(function(v){sum+=v;});});
      row.push(sum/1000);drow.push(pat);}
    d.push(row);diffs.push(drow);}
  return{xP:xP,yP:yP,d:d,nx:nx,ny:ny,diffs:diffs};
}

// ============ Workflow UI ============
function openExpWorkflow(){
  EXP_WF={step:0,roi:null,scanData:null,subRoi:null,features:null,diffPatterns:null,finalData:null,finalType:'xanes',scanType:'xrf',scanRes:51};
  showWfStep(0);
}

function showWfStep(step){
  EXP_WF.step=step;
  var html='<div style="display:flex;gap:3px;margin-bottom:8px;font-family:var(--mn);font-size:8px">';
  ['\u2460 Microscope','\u2461 2D Scan','\u2462 Sub-ROI','\u2463 Measurement'].forEach(function(l,i){
    var c=i===step?'var(--ac)':i<step?'var(--gn)':'var(--t3)';
    var bg=i===step?'rgba(77,184,255,0.15)':i<step?'rgba(64,216,154,0.1)':'var(--s2)';
    html+='<div style="padding:3px 6px;background:'+bg+';color:'+c+';border-radius:3px;border:1px solid '+c+'33">'+l+'</div>';});
  html+='</div>';
  if(step===0) html+=wfStep0Html();
  else if(step===1) { html+=wfStep1Html(); openModal('Experiment Workflow',html); setTimeout(function(){runWfScan2();},80); return; }
  else if(step===2) html+=wfStep2Html();
  else if(step===3) { html+=wfStep3Html(); openModal('Experiment Workflow',html); setTimeout(runFinalMeas2,80); return; }
  openModal('Experiment Workflow',html);
  if(step===0) setTimeout(function(){drawRealisticMicroscope(document.getElementById('wfMicro'),null);setupMicroDrag2();},50);
  if(step===2) setTimeout(function(){draw2DScanResult2(document.getElementById('wfResult2D'),EXP_WF.scanData,null);setupScanDrag2();},50);
}

function wfStep0Html(){
  return '<div style="font-size:10px;color:var(--t2);margin-bottom:4px">\uD83D\uDD2C Optical Microscope (DIC) \u2014 Drag to select ROI</div>'+
    '<canvas id="wfMicro" width="500" height="500" style="border:1px solid var(--b1);border-radius:4px;cursor:crosshair"></canvas>'+
    '<div id="wfRoiInfo" style="font-size:9px;color:var(--t3);margin-top:3px;font-family:var(--mn)">Drag to select region of interest</div>'+
    '<div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap">'+
    '<button class="sb go act" onclick="wfConfirmRoi()" id="wfNextBtn" disabled style="opacity:0.4">2D Scan \u25b6</button>'+
    '<select id="wfScanType" style="font-size:9px"><option value="xrf">XRF Map</option><option value="xrd">XRD Map (diffraction)</option></select>'+
    '<input type="number" id="wfScanRes" value="51" min="11" max="201" step="10" style="width:50px;font-size:9px"/></div>';
}
function wfStep1Html(){
  var tp=EXP_WF.scanType,res=EXP_WF.scanRes;
  return '<div style="font-size:10px;color:var(--t2);margin-bottom:4px">\u23F3 2D '+tp.toUpperCase()+' Scan ('+res+'x'+res+')...</div>'+
    '<canvas id="wfScan2D" width="500" height="500" style="border:1px solid var(--b1);border-radius:4px"></canvas>'+
    '<div class="prog-bar" style="margin-top:4px"><div class="prog-fill" id="wfScanProg"></div></div>'+
    '<div id="wfScanInfo" style="font-size:9px;color:var(--am);margin-top:3px;font-family:var(--mn)">Scanning...</div>';
}
function wfStep2Html(){
  var isXRD=(EXP_WF.scanType==='xrd');
  return '<div style="font-size:10px;color:var(--t2);margin-bottom:4px">\uD83D\uDD0D 2D Result \u2014 '+(isXRD?'Click pixel for diffraction pattern. ':'')+'Drag sub-ROI for measurement</div>'+
    '<div style="display:flex;gap:6px"><div>'+
    '<canvas id="wfResult2D" width="400" height="400" style="border:1px solid var(--b1);border-radius:4px;cursor:crosshair"></canvas></div>'+
    (isXRD?'<div><div style="font-size:8px;color:var(--t3);margin-bottom:2px">Diffraction Pattern</div><canvas id="wfDiffPat" width="200" height="200" style="border:1px solid var(--b1);border-radius:4px"></canvas><div id="wfDiffInfo" style="font-size:8px;color:var(--ac);margin-top:2px;font-family:var(--mn)">Click a pixel</div></div>':'')+
    '</div>'+
    '<div id="wfSubInfo" style="font-size:9px;color:var(--t3);margin-top:3px;font-family:var(--mn)">Drag sub-region or click point</div>'+
    '<div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap">'+
    '<button class="sb go act" onclick="wfStartFinal2()" id="wfFinalBtn" disabled style="opacity:0.4">Measure \u25b6</button>'+
    '<select id="wfFinalType" style="font-size:9px"><option value="xanes">XANES</option><option value="xrd_point">XRD \u03b8-2\u03b8</option><option value="xrf_detail">XRF Spectrum</option><option value="time_scan">Time Scan</option><option value="energy_scan">Energy Scan</option><option value="ptychography">Ptychography</option></select>'+
    '<button class="sb sec" onclick="showWfStep(0)">\u25c0 Restart</button></div>';
}
function wfStep3Html(){
  var tp=EXP_WF.finalType;
  var labels={xanes:'XANES',xrd_point:'XRD \u03b8-2\u03b8',xrf_detail:'XRF Spectrum',time_scan:'Time Scan (repeated exposure)',energy_scan:'Energy Scan (fixed position)',ptychography:'Ptychography Raster'};
  return '<div style="font-size:10px;color:var(--t2);margin-bottom:4px">\uD83D\uDCCA '+(labels[tp]||tp)+'</div>'+
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">'+
    '<div><div style="font-size:8px;color:var(--t3);margin-bottom:2px">2D Map (sub-ROI)</div><canvas id="wfFinalMap" width="240" height="240" style="border:1px solid var(--b1);border-radius:4px"></canvas></div>'+
    '<div><div style="font-size:8px;color:var(--t3);margin-bottom:2px" id="wfFinalLabel">'+(labels[tp]||tp)+'</div><canvas id="wfFinalSpec" width="280" height="240" style="border:1px solid var(--b1);border-radius:4px"></canvas></div></div>'+
    '<div class="prog-bar" style="margin-top:4px"><div class="prog-fill" id="wfFinalProg"></div></div>'+
    '<div id="wfFinalInfo" style="font-size:9px;color:var(--am);margin-top:3px;font-family:var(--mn)">Measuring...</div>'+
    '<div style="margin-top:6px;display:flex;gap:4px">'+
    '<button class="sb sec" onclick="showWfStep(2)">\u25c0 Back</button>'+
    '<button class="sb sec" onclick="showWfStep(0)">\u25c0 Restart</button>'+
    '<button class="sb act" onclick="wfExportAll2()">\uD83D\uDCBE Export</button></div>';
}

// ============ Interactions ============
function setupMicroDrag2(){
  var cv=document.getElementById('wfMicro');if(!cv)return;
  // Cache image to offscreen canvas (render once, no flicker)
  var cache=document.createElement('canvas');cache.width=cv.width;cache.height=cv.height;
  cache.getContext('2d').drawImage(cv,0,0);
  var dragging=false,sx=0,sy=0;
  function drawRoiOverlay(roi){
    var ctx=cv.getContext('2d');ctx.drawImage(cache,0,0); // restore cached image
    if(!roi)return;
    ctx.strokeStyle='#ff0';ctx.lineWidth=2;ctx.setLineDash([6,3]);
    ctx.strokeRect(roi.x,roi.y,roi.w,roi.h);ctx.setLineDash([]);
    ctx.fillStyle='rgba(255,255,0,0.06)';ctx.fillRect(roi.x,roi.y,roi.w,roi.h);
    ctx.fillStyle='#ff0';ctx.font='10px monospace';
    var um=roi.w/cv.width*500;
    ctx.fillText('ROI: '+um.toFixed(0)+'x'+(roi.h/cv.height*500).toFixed(0)+' \u00b5m',roi.x,roi.y-4);
  }
  cv.onmousedown=function(e){var r=cv.getBoundingClientRect();sx=e.clientX-r.left;sy=e.clientY-r.top;dragging=true;};
  cv.onmousemove=function(e){if(!dragging)return;var r=cv.getBoundingClientRect();
    var ex=e.clientX-r.left,ey=e.clientY-r.top;
    EXP_WF.roi={x:Math.min(sx,ex),y:Math.min(sy,ey),w:Math.abs(ex-sx),h:Math.abs(ey-sy)};
    drawRoiOverlay(EXP_WF.roi);
    document.getElementById('wfRoiInfo').textContent='ROI: '+(EXP_WF.roi.w/cv.width*500).toFixed(0)+'x'+(EXP_WF.roi.h/cv.height*500).toFixed(0)+' \u00b5m';};
  cv.onmouseup=function(){dragging=false;if(EXP_WF.roi&&EXP_WF.roi.w>15){
    var b=document.getElementById('wfNextBtn');if(b){b.disabled=false;b.style.opacity='1';}}};
}

function wfConfirmRoi(){
  if(!EXP_WF.roi)return;
  var sel=document.getElementById('wfScanType');EXP_WF.scanType=sel?sel.value:'xrf';
  var res=document.getElementById('wfScanRes');EXP_WF.scanRes=parseInt(res?res.value:'51');
  showWfStep(1);
}

function runWfScan2(){
  var cv=document.getElementById('wfScan2D');if(!cv)return;
  var roi=EXP_WF.roi,res=EXP_WF.scanRes,tp=EXP_WF.scanType;
  var w=cv.width,h=cv.height;
  // Convert pixel ROI to µm (500µm FOV)
  var roiUm={x:roi.x/w*500,y:roi.y/h*500,w:roi.w/w*500,h:roi.h/h*500};
  var nx=res,ny=res,xP=[],yP=[];
  for(var i=0;i<nx;i++) xP.push(roiUm.x+roiUm.w*i/(nx-1));
  for(var j=0;j<ny;j++) yP.push(roiUm.y+roiUm.h*j/(ny-1));
  var data={xP:xP,yP:yP,d:[],nx:nx,ny:ny,diffs:[]};
  var j=0;
  function scanRow(){
    if(j>=ny){EXP_WF.scanData=data;
      document.getElementById('wfScanInfo').textContent='\u2705 Complete: '+nx+'x'+ny;
      document.getElementById('wfScanInfo').style.color='var(--gn)';
      document.getElementById('wfScanProg').style.width='100%';
      setTimeout(function(){showWfStep(2);},600);return;}
    var row=[],drow=[];
    for(var i=0;i<nx;i++){
      var x=xP[i],y=yP[j],val=50+Math.random()*20;
      if(tp==='xrd'){
        var pat=genDiffPattern(x,y,500);var sum=0;
        pat.forEach(function(r){r.forEach(function(v){sum+=v;});});
        val=sum/500;drow.push(pat);
      } else {
        if(EXP_WF.features){var gx=(x/500*EXP_WF.features.w)|0,gy=(y/500*EXP_WF.features.h)|0;
          gx=Math.max(0,Math.min(EXP_WF.features.w-1,gx));gy=Math.max(0,Math.min(EXP_WF.features.h-1,gy));
          var gi=EXP_WF.features.grid[gy][gx],s=EXP_WF.features.seeds[gi];
          val+=({Fe:600,Cu:800,Ni:400,Au:1200,Ti:300}[s.elem]||200)*(0.5+0.5*Math.cos(2*Math.atan2(y-s.y,x-s.x)+s.orient));
          val+=Math.random()*50;}
      }
      row.push(val);}
    data.d.push(row);if(tp==='xrd')data.diffs.push(drow);j++;
    draw2DScanResult2(cv,data,null);
    document.getElementById('wfScanProg').style.width=(j/ny*100).toFixed(0)+'%';
    document.getElementById('wfScanInfo').textContent='Row '+j+'/'+ny;
    setTimeout(scanRow,tp==='xrd'?15:3);}
  scanRow();
}

function draw2DScanResult2(cv,data,subRoi){
  if(!data.d||!data.d.length)return;
  var nx=data.d[0].length,ny=data.d.length;
  if(typeof _drawHeatmap2D==='function'&&typeof Plotly!=='undefined'){
    var z=data.d;
    var opts={
      xLabel:'X (\u00b5m)',yLabel:'Y (\u00b5m)',
      colorscale:'Hot',
      width:cv.clientWidth||cv.width,
      height:cv.clientHeight||cv.height
    };
    if(data.xP&&data.xP.length>0)opts.x=data.xP;
    if(data.yP&&data.yP.length>0)opts.y=data.yP;
    _drawHeatmap2D(cv,z,opts);
    // Sub-ROI overlay via canvas
    if(subRoi&&data.xP){
      try{
        var cvEl=cv.tagName==='CANVAS'?cv:document.getElementById((cv.id||'hm')+'_cv');
        if(cvEl){
          var cCtx=cvEl.getContext('2d');
          var dpr=window.devicePixelRatio||1;
          var cW=cvEl.width/dpr,cH=cvEl.height/dpr;
          var xArr=data.xP,yArr=data.yP;
          var xMin=xArr[0],xMax=xArr[xArr.length-1];
          var yMin=yArr[0],yMax=yArr[yArr.length-1];
          var sx0=(subRoi.x-xMin)/(xMax-xMin)*cW*dpr;
          var sy0=(1-(subRoi.y+subRoi.h-yMin)/(yMax-yMin))*cH*dpr;
          var sw=(subRoi.w)/(xMax-xMin)*cW*dpr;
          var sh=(subRoi.h)/(yMax-yMin)*cH*dpr;
          cCtx.strokeStyle='#0ff';cCtx.lineWidth=2*dpr;
          cCtx.setLineDash([4*dpr,3*dpr]);
          cCtx.strokeRect(sx0,sy0,sw,sh);
          cCtx.setLineDash([]);
          cCtx.fillStyle='rgba(0,255,255,0.08)';
          cCtx.fillRect(sx0,sy0,sw,sh);
        }
      }catch(e){}
    }
  } else {
    // Canvas fallback (original code)
    var ctx=cv.getContext('2d'),w=cv.width,h=cv.height;
    var mn=Infinity,mx=-Infinity;
    data.d.forEach(function(r){r.forEach(function(v){if(v<mn)mn=v;if(v>mx)mx=v;});});
    var rng=mx-mn||1,cw=w/nx,ch=h/ny;
    for(var j=0;j<ny;j++) for(var i=0;i<nx;i++){
      var t=(data.d[j][i]-mn)/rng;
      ctx.fillStyle='rgb('+((t*220)|0)+','+(((1-Math.abs(t-0.5)*2)*180)|0)+','+((((1-t)*220)|0))+')';
      ctx.fillRect(i*cw,j*ch,cw+1,ch+1);}
    if(subRoi&&data.xP){
      var sx=(subRoi.x-data.xP[0])/(data.xP[nx-1]-data.xP[0])*w;
      var sy=(subRoi.y-data.yP[0])/(data.yP[ny-1]-data.yP[0])*h;
      var sw=subRoi.w/(data.xP[nx-1]-data.xP[0])*w;
      var sh=subRoi.h/(data.yP[ny-1]-data.yP[0])*h;
      ctx.strokeStyle='#0ff';ctx.lineWidth=2;ctx.setLineDash([4,3]);
      ctx.strokeRect(sx,sy,sw,sh);ctx.setLineDash([]);
      ctx.fillStyle='rgba(0,255,255,0.08)';ctx.fillRect(sx,sy,sw,sh);}
  }
}

function setupScanDrag2(){
  var cv=document.getElementById('wfResult2D');if(!cv)return;
  var d=EXP_WF.scanData,dragging=false,sx=0,sy=0,isXRD=(EXP_WF.scanType==='xrd');
  var x0=d.xP[0],x1=d.xP[d.nx-1],y0=d.yP[0],y1=d.yP[d.ny-1];
  cv.onmousedown=function(e){var r=cv.getBoundingClientRect();sx=e.clientX-r.left;sy=e.clientY-r.top;dragging=true;};
  cv.onmousemove=function(e){if(!dragging)return;var r=cv.getBoundingClientRect();
    var ex=e.clientX-r.left,ey=e.clientY-r.top;
    var rx=x0+(Math.min(sx,ex)/cv.width)*(x1-x0),ry=y0+(Math.min(sy,ey)/cv.height)*(y1-y0);
    var rw=Math.abs(ex-sx)/cv.width*(x1-x0),rh=Math.abs(ey-sy)/cv.height*(y1-y0);
    EXP_WF.subRoi={x:rx,y:ry,w:rw,h:rh};
    draw2DScanResult2(cv,d,EXP_WF.subRoi);
    document.getElementById('wfSubInfo').textContent='Sub-ROI: '+rw.toFixed(0)+'x'+rh.toFixed(0)+' \u00b5m';};
  cv.onmouseup=function(e){
    if(dragging&&EXP_WF.subRoi&&EXP_WF.subRoi.w>2){dragging=false;
      var b=document.getElementById('wfFinalBtn');if(b){b.disabled=false;b.style.opacity='1';}return;}
    dragging=false;
    // Click = show diffraction pattern for XRD
    if(isXRD&&d.diffs&&d.diffs.length>0){
      var r=cv.getBoundingClientRect(),cx=e.clientX-r.left,cy=e.clientY-r.top;
      var pi=Math.floor(cx/cv.width*d.nx),pj=Math.floor(cy/cv.height*d.ny);
      pi=Math.max(0,Math.min(d.nx-1,pi));pj=Math.max(0,Math.min(d.diffs.length-1,pj));
      if(d.diffs[pj]&&d.diffs[pj][pi]){
        var dcv=document.getElementById('wfDiffPat');
        if(dcv){drawDiffPattern(dcv,d.diffs[pj][pi]);
          var info=document.getElementById('wfDiffInfo');
          if(info) info.textContent='Pixel ('+pi+','+pj+') @ ('+d.xP[pi].toFixed(1)+', '+d.yP[pj].toFixed(1)+') \u00b5m';
        }
        // Highlight clicked pixel
        draw2DScanResult2(cv,d,EXP_WF.subRoi);
        var ctx2=cv.getContext('2d'),pw=cv.width/d.nx,ph=cv.height/d.ny;
        ctx2.strokeStyle='#fff';ctx2.lineWidth=2;ctx2.strokeRect(pi*pw,pj*ph,pw,ph);
      }
    }
  };
}

function wfStartFinal2(){
  if(!EXP_WF.subRoi)return;
  var sel=document.getElementById('wfFinalType');
  EXP_WF.finalType=sel?sel.value:'xanes';showWfStep(3);
}

// ============ Final Measurements ============
function runFinalMeas2(){
  var mapCv=document.getElementById('wfFinalMap'),specCv=document.getElementById('wfFinalSpec');
  if(!mapCv||!specCv)return;
  draw2DScanResult2(mapCv,EXP_WF.scanData,EXP_WF.subRoi);
  var tp=EXP_WF.finalType,sr=EXP_WF.subRoi,cx=sr.x+sr.w/2,cy=sr.y+sr.h/2;
  var label=document.getElementById('wfFinalLabel');
  // Find element at position
  var elem='Cu';
  if(EXP_WF.features){var gx=(cx/500*EXP_WF.features.w)|0,gy=(cy/500*EXP_WF.features.h)|0;
    gx=Math.max(0,Math.min(EXP_WF.features.w-1,gx));gy=Math.max(0,Math.min(EXP_WF.features.h-1,gy));
    elem=EXP_WF.features.seeds[EXP_WF.features.grid[gy][gx]].elem;}
  var mat=MATERIALS[elem]||MATERIALS['Cu'];
  if(label) label.textContent=tp+' @ ('+cx.toFixed(0)+','+cy.toFixed(0)+') \u00b5m ['+elem+']';
  var data=[],i=0;

  if(tp==='time_scan'){
    // Same position, multiple exposures over time
    var nExp=100,dwellMs=500;
    var baseFlux=photonFlux(state.energy);
    function tick(){
      if(i>=nExp){wfFinish2(data,tp);return;}
      var t=i*dwellMs/1000; // seconds
      var flux=baseFlux*(1+0.05*Math.sin(t*0.3))*(1-0.001*t)+Math.random()*baseFlux*0.02;
      data.push({x:t,y:flux}); i++;
      document.getElementById('wfFinalProg').style.width=(i/nExp*100).toFixed(0)+'%';
      document.getElementById('wfFinalInfo').textContent='Exposure '+i+'/'+nExp+' (t='+t.toFixed(1)+'s)';
      if(i%5===0) wfDrawSpec2(specCv,data,'time');
      setTimeout(tick,8);}tick();
  } else if(tp==='energy_scan'){
    // Same position, scan energy
    var eStart=state.energy-2,eEnd=state.energy+2,eStep=0.02;
    var pts=[];for(var e=eStart;e<=eEnd;e+=eStep)pts.push(e);
    function tick(){
      if(i>=pts.length){wfFinish2(data,tp);return;}
      var e=pts[i],flux=photonFlux(e);
      flux+=(Math.random()-0.5)*flux*0.03;
      data.push({x:e,y:flux}); i++;
      document.getElementById('wfFinalProg').style.width=(i/pts.length*100).toFixed(0)+'%';
      document.getElementById('wfFinalInfo').textContent='E='+pts[i-1].toFixed(2)+' keV ('+i+'/'+pts.length+')';
      if(i%10===0) wfDrawSpec2(specCv,data,'energy');
      setTimeout(tick,3);}tick();
  } else if(tp==='ptychography'){
    // Raster scan with overlap, show reconstructed phase
    var nPty=41,pdata={d:[],n:nPty};
    function tick(){
      if(i>=nPty){
        // Show "reconstructed" phase image
        var ctx=specCv.getContext('2d'),w=specCv.width,h=specCv.height;
        var img=ctx.createImageData(w,h);
        for(var py=0;py<h;py++) for(var px=0;px<w;px++){
          var t=pdata.d[Math.floor(py/h*nPty)]?pdata.d[Math.floor(py/h*nPty)][Math.floor(px/w*nPty)]||0:0;
          t=(t+Math.PI)/(2*Math.PI);
          var idx=(py*w+px)*4;img.data[idx]=t*100|0;img.data[idx+1]=t*255|0;img.data[idx+2]=(1-t)*200|0;img.data[idx+3]=255;}
        ctx.putImageData(img,0,0);
        ctx.fillStyle='#fff';ctx.font='9px monospace';ctx.fillText('Phase (reconstructed)',4,12);
        wfFinish2(data,'ptychography');return;}
      var row=[];for(var k=0;k<nPty;k++){
        var px=sr.x+sr.w*k/(nPty-1),py=sr.y+sr.h*i/(nPty-1);
        var phase=Math.sin(px*0.1)*Math.cos(py*0.1)+0.5*Math.sin(px*0.05+py*0.03);
        row.push(phase);data.push({x:k,y:i,val:phase});}
      pdata.d.push(row);i++;
      document.getElementById('wfFinalProg').style.width=(i/nPty*100).toFixed(0)+'%';
      document.getElementById('wfFinalInfo').textContent='Pty row '+i+'/'+nPty;
      setTimeout(tick,20);}tick();
  } else if(tp==='xanes'){
    var E0=mat.K/1000,pts=[];
    for(var e=E0-0.05;e<=E0+0.3;e+=0.0005)pts.push(e);
    function tick(){if(i>=pts.length){wfFinish2(data,tp);return;}
      var e=pts[i],x=(e-E0)*1000,mu=0.5;
      if(x>0){mu=1;var k=Math.sqrt(0.2625*Math.max(x,0.1));
        mu+=0.08*Math.sin(2*k*2.5)*Math.exp(-2*0.003*k*k)/k;
        mu+=0.04*Math.sin(2*k*3.6)*Math.exp(-2*0.005*k*k)/k;
        mu+=0.3*Math.exp(-x*x/50);}else mu=0.5+x*0.0005;
      mu+=(Math.random()-0.5)*0.003;data.push({x:x,y:mu});i++;
      document.getElementById('wfFinalProg').style.width=(i/pts.length*100).toFixed(0)+'%';
      if(i%30===0)wfDrawSpec2(specCv,data,'xanes');setTimeout(tick,2);}tick();
  } else if(tp==='xrd_point'){
    var pts=[];for(var t=20;t<=80;t+=0.05)pts.push(t);
    function tick(){if(i>=pts.length){wfFinish2(data,tp);return;}
      var t2=pts[i],v=5+Math.random()*2;
      if(mat.xrd)mat.xrd.forEach(function(pk,j){v+=(1000-j*150)*(0.8+Math.random()*0.4)*Math.exp(-4*Math.LN2*Math.pow((t2-pk)/0.12,2));});
      data.push({x:t2,y:Math.max(0,v)});i++;
      document.getElementById('wfFinalProg').style.width=(i/pts.length*100).toFixed(0)+'%';
      if(i%40===0)wfDrawSpec2(specCv,data,'xrd');setTimeout(tick,1);}tick();
  } else { // xrf_detail
    var nCh=2048,chW=20/nCh;
    function tick(){if(i>=nCh){wfFinish2(data,'xrf');return;}
      var e=i*chW,c=20*Math.exp(-e*0.3)+Math.random()*5;
      if(mat.lines)Object.values(mat.lines).forEach(function(le){var ek=le/1000;if(ek<15)c+=2000*Math.exp(-4*Math.LN2*Math.pow((e-ek)/0.15,2));});
      data.push({x:e,y:Math.max(0,c)});i+=4;
      document.getElementById('wfFinalProg').style.width=(i/nCh*100).toFixed(0)+'%';
      if(i%100===0)wfDrawSpec2(specCv,data,'xrf');setTimeout(tick,1);}tick();
  }
}

function wfDrawSpec2(cv,data,tp){
  if(typeof v420FallbackChart==='function')v420FallbackChart(cv,data,tp==='xrf_detail'?'xrf':(tp==='time'||tp==='energy'?'xanes':tp));
  else if(typeof renderScan1DPopup==='function')renderScan1DPopup(cv,data,tp==='xrf_detail'?'xrf':tp);
}
function wfFinish2(data,tp){
  EXP_WF.finalData=data;
  var specCv=document.getElementById('wfFinalSpec');if(specCv&&tp!=='ptychography')wfDrawSpec2(specCv,data,tp);
  var info=document.getElementById('wfFinalInfo');
  if(info){info.textContent='\u2705 Complete: '+data.length+' pts ('+tp+')';info.style.color='var(--gn)';}
  document.getElementById('wfFinalProg').style.width='100%';
  log('info','Workflow: '+tp+' done, '+data.length+' pts');
}
function wfExportAll2(){
  var csv='# Workflow Export\n# ROI: '+JSON.stringify(EXP_WF.roi)+'\n# Sub-ROI: '+JSON.stringify(EXP_WF.subRoi)+'\n# Type: '+EXP_WF.finalType+'\nX,Y\n';
  if(EXP_WF.finalData)EXP_WF.finalData.forEach(function(d){csv+=d.x+','+d.y+'\n';});
  var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  a.download='workflow_'+EXP_WF.finalType+'.csv';a.click();
}

// ============ Install ============
function addWorkflowButton2(){
  var mt=document.getElementById('tab-measure');if(!mt)return;
  var ex=mt.querySelector('.wf-btn-container');if(ex)ex.remove();
  var div=document.createElement('div');div.className='ctrl-group wf-btn-container';
  div.innerHTML='<button class="sb go act" onclick="openExpWorkflow()" style="width:100%;padding:6px">Experiment Workflow</button>'+
    '<div style="font-size:8px;color:var(--t3);margin-top:2px;font-family:var(--mn)">Microscope \u2192 ROI \u2192 2D Scan \u2192 Sub-ROI \u2192 Measurement</div>';
  mt.insertBefore(div,mt.firstChild);
  log('info', APP_VTAG + ': Workflow with Voronoi microscopy, per-pixel XRD diffraction, time/energy/pty scans');
}

// ESM bridge: expose module-scoped vars to globalThis
if(typeof addWorkflowButton2!=="undefined")globalThis.addWorkflowButton2=addWorkflowButton2;
if(typeof draw2DScanResult2!=="undefined")globalThis.draw2DScanResult2=draw2DScanResult2;
if(typeof drawDiffPattern!=="undefined")globalThis.drawDiffPattern=drawDiffPattern;
if(typeof drawRealisticMicroscope!=="undefined")globalThis.drawRealisticMicroscope=drawRealisticMicroscope;
if(typeof genDiffPattern!=="undefined")globalThis.genDiffPattern=genDiffPattern;
if(typeof genVoronoiGrains!=="undefined")globalThis.genVoronoiGrains=genVoronoiGrains;
if(typeof openExpWorkflow!=="undefined")globalThis.openExpWorkflow=openExpWorkflow;
if(typeof runFinalMeas2!=="undefined")globalThis.runFinalMeas2=runFinalMeas2;
if(typeof runWfScan2!=="undefined")globalThis.runWfScan2=runWfScan2;
if(typeof setupMicroDrag2!=="undefined")globalThis.setupMicroDrag2=setupMicroDrag2;
if(typeof setupScanDrag2!=="undefined")globalThis.setupScanDrag2=setupScanDrag2;
if(typeof showWfStep!=="undefined")globalThis.showWfStep=showWfStep;
if(typeof sim2DScanXRD!=="undefined")globalThis.sim2DScanXRD=sim2DScanXRD;
if(typeof wfConfirmRoi!=="undefined")globalThis.wfConfirmRoi=wfConfirmRoi;
if(typeof wfDrawSpec2!=="undefined")globalThis.wfDrawSpec2=wfDrawSpec2;
if(typeof wfExportAll2!=="undefined")globalThis.wfExportAll2=wfExportAll2;
if(typeof wfFinish2!=="undefined")globalThis.wfFinish2=wfFinish2;
if(typeof wfStartFinal2!=="undefined")globalThis.wfStartFinal2=wfStartFinal2;
if(typeof wfStep0Html!=="undefined")globalThis.wfStep0Html=wfStep0Html;
if(typeof wfStep1Html!=="undefined")globalThis.wfStep1Html=wfStep1Html;
if(typeof wfStep2Html!=="undefined")globalThis.wfStep2Html=wfStep2Html;
if(typeof wfStep3Html!=="undefined")globalThis.wfStep3Html=wfStep3Html;
if(typeof EXP_WF!=="undefined")globalThis.EXP_WF=EXP_WF;
