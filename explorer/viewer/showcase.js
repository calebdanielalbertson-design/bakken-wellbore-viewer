import {scaleRGB} from './survey-colors.js';

// Local recording of the actual viewer renderer and production controller.
export function createShowcase(api){
  const W=1920,H=1080,DURATION=35,plot={x:36,y:167,w:1340,h:820};
  const overlay=document.createElement('div');overlay.id='showcaseStudio';
  overlay.innerHTML='<div class="showcase-tools"><strong>Local video studio</strong><span id="showcaseStatus" role="status">Preparing real survey data…</span><button id="showcaseRecord" disabled>Record 35-second showcase</button><a id="showcaseDownload" hidden download>Download video</a><div id="showcaseReview" hidden><button id="showcaseReviewAzimuth">Review azimuth</button><button id="showcaseReviewDls">Review DLS</button><button id="showcaseReviewOil">Review production</button></div></div><canvas id="showcaseCanvas" width="1920" height="1080" aria-label="Wellbore showcase video preview"></canvas><video id="showcasePlayback" controls hidden aria-label="Recorded showcase preview"></video>';
  const style=document.createElement('style');style.textContent='#showcaseStudio{position:fixed;inset:0;z-index:100;background:#071523;display:flex;flex-direction:column;align-items:center;overflow:auto}.showcase-tools{width:100%;padding:12px 20px;display:flex;gap:18px;align-items:center;flex-wrap:wrap;background:#102738;flex-shrink:0}.showcase-tools span{flex:1;font-size:13px}.showcase-tools a{color:#a9ffdf}#showcaseCanvas,#showcasePlayback{width:100%;max-height:calc(100vh - 80px);object-fit:contain}';document.head.append(style);document.body.append(overlay);
  const $=id=>document.getElementById(id),canvas=$('showcaseCanvas'),ctx=canvas.getContext('2d',{alpha:false});
  const candidates=['video/mp4;codecs=avc1.420028','video/mp4','video/webm;codecs=vp9','video/webm;codecs=vp8'];
  const mime=candidates.find(s=>typeof MediaRecorder!=='undefined'&&MediaRecorder.isTypeSupported(s));
  let preparing=false,ready=false,recording=false,start=0,elapsed=0,phase=-1,recorder=null,parts=[],url=null,baseDistance=1,baseAngle=0,target=null,stats=null,lastMonth=-1,finished=false,frames=0,monthStart=192,monthEnd=299;
  let fullCounts={branches:47802,stations:5360341};
  const text=(str,x,y,size=24,color='#e4edf5',weight=400)=>{ctx.fillStyle=color;ctx.font=`${weight} ${size}px "Segoe UI",Arial,sans-serif`;ctx.fillText(str,x,y)};
  function paragraph(str,x,y,width,size=26,color='#9db5c8',line=38){ctx.font=`${size}px "Segoe UI",Arial,sans-serif`;let row='';for(const word of str.split(' ')){const next=row?row+' '+word:word;if(ctx.measureText(next).width>width&&row){text(row,x,y,size,color);y+=line;row=word}else row=next}if(row)text(row,x,y,size,color);return y+line;}
  const setEnabled=value=>{$('productionEnabled').checked=value;$('productionEnabled').onchange({target:{checked:value}})};
  function setMonth(index){if(index===lastMonth)return;lastMonth=index;$('productionMonth').value=index;$('productionMonth').oninput({target:{value:index}})}
  async function prepare(){
    preparing=true;const s=api.state();
    try{
      stats=await api.read('section-metric-scales.json',true);try{const response=await fetch('../full-dataset/manifest.json');if(response.ok){const full=await response.json();fullCounts={branches:full.wells.length,stations:full.stations}}}catch{}const oil=await api.read('production.json',true);monthStart=oil.months.indexOf('2016-01');monthEnd=oil.months.indexOf('2024-12');if(monthStart<0||monthEnd<monthStart)throw Error('Production coverage for 2016–2024 is required.');await s.surveyColors.setMode('dls');await s.surveyColors.setMode('azimuth');
      setEnabled(false);api.clearSelection();api.hideReference();s.controls.enabled=false;s.controls.enableDamping=false;s.navigation.reset();
      s.renderer.setPixelRatio(1);s.renderer.setSize(plot.w,plot.h,false);s.camera.aspect=plot.w/plot.h;s.camera.updateProjectionMatrix();api.fit();
      target=s.controls.target.clone();const offset=s.camera.position.clone().sub(target);baseDistance=offset.length()*.81;baseAngle=Math.atan2(offset.x,offset.z);
      target.y-=baseDistance*.07;target.x-=Math.cos(baseAngle)*baseDistance*.04;target.z+=Math.sin(baseAngle)*baseDistance*.04;
      ready=true;$('showcaseRecord').disabled=!mime;$('showcaseStatus').textContent=mime?`Ready · 1920×1080 · 35 seconds · ${mime.startsWith('video/mp4')?'MP4 / H.264':'WebM'} · no audio`:'This browser cannot record canvas video.';
    }catch(e){$('showcaseStatus').textContent='Could not prepare recording: '+e.message;}
  }
  function setPhase(next){
    phase=next;const s=api.state();
    if(next===0){s.surveyColors.setMode('azimuth');setEnabled(false)}
    if(next===1){s.surveyColors.setMode('dls');setEnabled(false)}
    if(next>=2){s.surveyColors.setMode('section');setEnabled(true);$('productionSize').value=7;$('productionSize').oninput({target:{value:7}})}
  }
  function draw(){
    ctx.fillStyle='#071523';ctx.fillRect(0,0,W,H);
    text('W',44,68,38,'#86e3d7',700);text('WELLBORE EXPLORER',102,67,28,'#e5f4fa',600);text('BAKKEN  /  NORTH DAKOTA',1390,65,23,'#8cabbf',500);
    text('Below the surface. Across time.',42,130,44,'#f3f8fc',500);
    ctx.save();ctx.beginPath();ctx.rect(plot.x,plot.y,plot.w,plot.h);ctx.clip();ctx.drawImage(api.state().renderer.domElement,plot.x,plot.y,plot.w,plot.h);ctx.restore();
    ctx.strokeStyle='#264456';ctx.lineWidth=1;ctx.strokeRect(plot.x+.5,plot.y+.5,plot.w-1,plot.h-1);
    const x=1420,width=450,active=phase<0?0:phase;
    const headers=['01  DIRECTION','02  WELLBORE SHAPE','03  PRODUCTION','BUILT TO EXPLORE'];
    const titles=['Azimuth','Dogleg severity','Oil over time','One connected view'];
    text(headers[active],x,216,20,'#86e3d7',600);text(titles[active],x,276,42,'#f2f8fc',500);
    if(active===0){
      paragraph('See how the wells are oriented beneath the surface.',x,335,width,28);
      const gradient=ctx.createLinearGradient(x,0,x+width,0);for(let i=0;i<=48;i++)gradient.addColorStop(i/48,'rgb('+scaleRGB(i/48,'cyclic').map(v=>Math.round(v*255)).join(',')+')');ctx.fillStyle=gradient;ctx.fillRect(x,474,width,18);
      ['N','E','S','W','N'].forEach((label,i)=>text(label,x+i*(width-16)/4,525,23,'#b9cfde',500));
      paragraph('A cyclic compass scale makes directional patterns visible.',x,600,width,27);
      paragraph('Bearings below 5° inclination are shown as unavailable.',x,790,width,21,'#809eaf',30);
    }else if(active===1){
      paragraph('Reveal directional changes without letting the curve dominate.',x,335,width,27);
      const gradient=ctx.createLinearGradient(x,0,x+width,0);for(let i=0;i<=32;i++)gradient.addColorStop(i/32,'rgb('+scaleRGB(i/32,'thermal').map(v=>Math.round(v*255)).join(',')+')');ctx.fillStyle=gradient;ctx.fillRect(x,476,width,18);text('LOW',x,529,20,'#9db5c8');text('HIGH',x+width-52,529,20,'#9db5c8');
      text('INDEPENDENT SECTION SCALES',x,598,20,'#86e3d7',600);
      let y=652;for(const id of [0,2,4]){const section=stats.sections.find(v=>v.id===id),m=section.metrics.dls;text(section.label,x,y,26);text(`${m.p02.toFixed(2)} – ${m.p98.toFixed(2)}°/100 ft`,x+160,y,24,'#b8cede');y+=53}
      paragraph('Automatic 2nd–98th percentile ranges; custom limits available.',x,859,width,21,'#809eaf',30);
    }else if(active===2){
      paragraph('Watch monthly oil production change across the same well paths.',x,335,width,27);
      text($('productionDateLabel').textContent,x,510,48,'#a3ff12',600);
      paragraph($('productionSummary').textContent,x,568,width,25,'#d7eac9',37);
      const month=Number($('productionMonth').value),p=Math.max(0,Math.min(1,(month-monthStart)/(monthEnd-monthStart)));ctx.fillStyle='#233b4b';ctx.fillRect(x,697,width,7);ctx.fillStyle='#a3ff12';ctx.fillRect(x,697,width*p,7);text('2016',x,746,22,'#9db5c8');text('2024',x+width-55,746,22,'#9db5c8');
      paragraph('Lateral width ∝ √monthly oil barrels',x,818,width,24,'#d9efb6',34);
      paragraph('Display symbols, not bore diameters. Survey geometry is fixed through time.',x,902,width,20,'#809eaf',28);
    }else{
      paragraph('Explore direction, wellbore shape and production in an interactive 3D view.',x,344,width,29,'#c3d7e4',43);
      text(fullCounts.branches.toLocaleString('en-US'),x,605,68,'#86e3d7',600);text('survey branches in the full database',x,652,23,'#a5bece');text((fullCounts.stations/1e6).toFixed(2)+' million',x,760,52,'#e6f2fa',500);text('survey stations',x,804,24,'#a5bece');
      paragraph('Mouse navigation. Local data. A new way to explore the Bakken.',x,900,width,22,'#a5bece',31);
    }
    text(`ACTUAL VIEWER RENDERING  ·  REPRESENTATIVE CLUSTER: ${api.state().manifest.wells.length} BRANCHES`,45,1032,19,'#7899ae',500);
    const label=active>=2?'Monthly oil: matched wells only · current survey geometry':'Relative TVD · survey-derived colors';text(label,1050,1032,19,'#7899ae');
    const progress=Math.min(1,elapsed/DURATION);ctx.fillStyle='#86e3d7';ctx.fillRect(0,H-4,W*progress,4);
    if(recording){const edge=Math.min(elapsed/.7,(DURATION-elapsed)/.7,1);if(edge<1){ctx.fillStyle=`rgba(7,21,35,${1-Math.max(0,edge)})`;ctx.fillRect(0,0,W,H)}}
  }
  function record(){
    if(!ready||recording||!mime)return;
    elapsed=0;phase=-1;finished=false;frames=0;lastMonth=-1;parts=[];start=performance.now();recording=true;
    $('showcaseRecord').disabled=true;$('showcaseDownload').hidden=true;$('showcasePlayback').hidden=true;$('showcaseReview').hidden=true;canvas.hidden=false;
    const stream=canvas.captureStream(30);recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:12000000});
    recorder.ondataavailable=e=>{if(e.data.size)parts.push(e.data)};
    recorder.onerror=e=>{$('showcaseStatus').textContent='Recording error: '+e.error.message;recording=false;stream.getTracks().forEach(t=>t.stop());$('showcaseRecord').disabled=false};
    recorder.onstop=()=>{stream.getTracks().forEach(t=>t.stop());const blob=new Blob(parts,{type:recorder.mimeType});if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(blob);const mp4=recorder.mimeType.startsWith('video/mp4');$('showcaseDownload').href=url;$('showcaseDownload').download='Bakken-Wellbore-Explorer.'+(mp4?'mp4':'webm');$('showcaseDownload').textContent='Download '+(mp4?'MP4':'WebM')+' video';$('showcaseDownload').hidden=false;$('showcasePlayback').src=url;$('showcaseReview').hidden=false;$('showcaseRecord').disabled=false;$('showcaseStatus').textContent=`Recording complete · ${(blob.size/1048576).toFixed(1)} MB · ${frames} rendered frames · 1920×1080 · ${recorder.mimeType}`;};
    recorder.start(1000);
  }
  $('showcaseRecord').onclick=record;
  for(const [id,time] of [['showcaseReviewAzimuth',5],['showcaseReviewDls',14],['showcaseReviewOil',26]])$(id).onclick=()=>{const v=$('showcasePlayback');v.hidden=false;canvas.hidden=true;v.pause();v.currentTime=time;};
  return {
    beforeRender(t){const s=api.state();if(!preparing&&s.manifest&&s.surveyColors.ready()&&!s.busy&&s.detail.size===s.manifest.tiles.length)prepare();if(!ready)return;
      if(s.renderer.domElement.width!==plot.w||s.renderer.domElement.height!==plot.h)s.renderer.setSize(plot.w,plot.h,false);
      if(s.camera.aspect!==plot.w/plot.h){s.camera.aspect=plot.w/plot.h;s.camera.updateProjectionMatrix()}
      s.production.update(t,s.camera,plot.w,plot.h);
      if(recording)elapsed=Math.min(DURATION,(t-start)/1000);
      const next=elapsed<9?0:elapsed<19?1:elapsed<32?2:3;if(next!==phase)setPhase(next);
      const angle=baseAngle-.22+elapsed/DURATION*.58,distance=baseDistance*(1-.04*Math.sin(Math.PI*elapsed/DURATION));
      s.controls.target.copy(target);s.camera.position.set(target.x+Math.sin(angle)*distance*.93,target.y+distance*.37,target.z+Math.cos(angle)*distance*.93);s.camera.lookAt(target);
      if(phase===2)setMonth(monthStart+Math.min(monthEnd-monthStart,Math.floor((elapsed-19)/13*(monthEnd-monthStart+1))));if(phase===3)setMonth(monthEnd);
      if(recording)$('showcaseStatus').textContent=`Recording locally… ${Math.floor(elapsed)} / 35 seconds`;
    },
    afterRender(){if(!ready)return;draw();if(recording){frames++;if(elapsed>=DURATION&&!finished){finished=true;recording=false;recorder.stop()}}}
  };
}
