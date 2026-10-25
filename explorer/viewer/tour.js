import * as THREE from 'three';
import {METRICS,scaleRGB,automaticSectionBounds} from './survey-colors.js';
import {projectReference} from './reference-plane.js';
import {buildGammaTubeBuffers,turboLinear,turboSRGB} from './gamma-geometry.js';
import {clamp,ease,mix,planFrame,zoomFrame,perspectiveDistance,TOUR_SHOTS,shotAt} from './tour-math.js';

// Record the local WebGL scene. Statewide context never participates in cluster
// picking, metric indexing or production joins; all detailed data remain exact.
export function createShowcase(api){
  const W=1920,H=1080,DURATION=50,plot={x:36,y:167,w:1340,h:820},aspect=plot.w/plot.h;
  const panel=document.createElement('div');panel.id='tourStudio';
  panel.innerHTML='<div class="tour-tools"><strong>North Dakota video tour</strong><span id="tourStatus" role="status">Preparing survey paths and logs…</span><button id="tourRecord" disabled>Record 50-second tour</button><a id="tourDownload" hidden download>Download video</a><label>Preview scene <select id="tourScene" disabled></select></label><div id="tourReview" hidden><button id="tourReviewState">Review North Dakota</button><button id="tourReviewDls">Review DLS</button><button id="tourReviewLogs">Review logs</button><button id="tourReviewOil">Review production</button></div></div><canvas id="tourCanvas" width="1920" height="1080" aria-label="North Dakota tour preview"></canvas><video id="tourPlayback" controls hidden aria-label="Recorded North Dakota tour"></video>';
  const style=document.createElement('style');style.textContent='#tourStudio{position:fixed;inset:0;z-index:110;background:#071523;display:flex;flex-direction:column;align-items:center;overflow:auto}.tour-tools{width:100%;padding:12px 20px;display:flex;gap:14px;align-items:center;flex-wrap:wrap;background:#102738;flex-shrink:0}.tour-tools span{flex:1;font-size:13px}.tour-tools a{color:#a9ffdf}.tour-tools label{font-size:13px;display:flex;align-items:center;gap:7px}#tourCanvas,#tourPlayback{width:100%;max-height:calc(100vh - 100px);object-fit:contain}';document.head.append(style);document.body.append(panel);
  const $=id=>document.getElementById(id),canvas=$('tourCanvas'),ctx=canvas.getContext('2d',{alpha:false});
  const mime=['video/mp4;codecs=avc1.420028','video/mp4','video/webm;codecs=vp9','video/webm;codecs=vp8'].find(v=>typeof MediaRecorder!=='undefined'&&MediaRecorder.isTypeSupported(v));
  for(const s of TOUR_SHOTS){const o=document.createElement('option');o.value=s.key;o.textContent=s.title;$('tourScene').append(o)}
  const ortho=new THREE.OrthographicCamera(-1,1,1,-1,1,10000000),perspective=new THREE.PerspectiveCamera(45,aspect,1,10000000);
  ortho.up.set(0,0,-1);let activeCamera=ortho;
  let preparing=false,ready=false,recording=false,elapsed=0,start=0,lastShot='',recorder,url,parts=[],frames=0,lastMonth=-1;
  let stats,fullManifest,context,stateFrame,clusterFrame,clusterTarget,orbitDistance,orbitAngle,places=[],monthStart,monthEnd,logBox;
  const logs={gamma:new THREE.Group(),cbl:new THREE.Group()};
  const LOG_SOURCES=[['21994','21994-AIG-CND-CAL1.las#11','21994-CBL.las#4'],['26882','26882-CBL.las#29','26882-CBL.las#27'],['33835','33835-CBL.las#1','33835-CBL.las#4'],['39016','39016-CBL.las#15','39016-CBL.las#1']];
  const text=(v,x,y,size=24,color='#e4edf5',weight=400)=>{ctx.fillStyle=color;ctx.font=`${weight} ${size}px "Segoe UI",Arial,sans-serif`;ctx.fillText(v,x,y)};
  function paragraph(v,x,y,width=450,size=27,color='#a9c0d0',line=39){ctx.font=`${size}px "Segoe UI",Arial,sans-serif`;let row='';for(const word of v.split(' ')){const next=row?row+' '+word:word;if(ctx.measureText(next).width>width&&row){text(row,x,y,size,color);y+=line;row=word}else row=next}if(row)text(row,x,y,size,color);return y+line}
  const json=async path=>{const r=await fetch(path);if(!r.ok)throw Error('Missing '+path);return r.json()};
  const setOil=v=>{$('productionEnabled').checked=v;$('productionEnabled').onchange({target:{checked:v}})};
  function setMonth(i){if(i===lastMonth)return;lastMonth=i;$('productionMonth').value=i;$('productionMonth').oninput({target:{value:i}})}
  async function prepare(){
    preparing=true;const s=api.state();
    try{
      [stats,fullManifest]=await Promise.all([api.read('section-metric-scales.json',true),json('../full-dataset/manifest.json'),api.referenceReady()]);
      if(JSON.stringify(fullManifest.origin)!==JSON.stringify(s.manifest.origin)||fullManifest.sourceCRS!==s.manifest.sourceCRS)throw Error('State and cluster coordinate references differ.');
      if(!s.reference.bounds)throw Error('North Dakota boundary unavailable.');
      const response=await fetch('../full-dataset/overview.bin');if(!response.ok)throw Error('Statewide paths unavailable.');
      const raw=new Float32Array(await response.arrayBuffer());if(raw.length!==fullManifest.overviewSegments*8)throw Error('Incomplete statewide paths.');
      const identity=w=>`${w.permit}|${w.api}|${w.branch}`,selected=new Set(s.manifest.wells.map(identity)),include=fullManifest.wells.map(w=>!selected.has(identity(w)));let count=0;for(let i=0;i<raw.length;i+=8)if(include[raw[i+7]])count++;
      const vertices=new Float32Array(count*6);let p=0;for(let i=0;i<raw.length;i+=8)if(include[raw[i+7]]){vertices.set(raw.subarray(i,i+6),p);p+=6}
      context=new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(vertices,3)),new THREE.LineBasicMaterial({color:'#63b8cb',transparent:true,opacity:.8,depthWrite:false}));context.name='Unpickable statewide tour context';s.scene.add(context);
      const cities=await json('./data/reference/places.geojson');places=cities.features.map(f=>({name:f.properties.BASENAME||f.properties.NAME,point:new THREE.Vector3(...projectReference(...f.geometry.coordinates,s.manifest))}));
      // Preload every advertised numeric mode before the recording starts.
      for(const key of Object.keys(METRICS))await s.surveyColors.setMode(key);
      await s.surveyColors.setMode('section');
      await Promise.all(Object.entries(logs).map(async([metric,group])=>{
        const ceiling=metric==='gamma'?300:100;
        const responses=await Promise.all(LOG_SOURCES.map(async row=>{
          const source=row[metric==='gamma'?1:2];
          const data=await json(`/api/${metric}/well?permit=${row[0]}&source=${encodeURIComponent(source)}&average=100`);
          if(JSON.stringify(data.origin)!==JSON.stringify(s.manifest.origin)||!data.paths?.length)throw Error('Log path alignment unavailable for '+row[0]);
          if(!new RegExp(metric==='gamma'?'^(g?api|aapi)$':'^mv$','i').test(data.unit))throw Error('Unexpected log unit.');
          for(const path of data.paths){
            const samples=path.points.map(v=>v&&Number.isFinite(v[4])?{x:v[0],y:v[1],z:v[2],md:v[3],gr:v[4]}:null);
            const buffers=buildGammaTubeBuffers(samples,{sides:10,maxGapMD:250,maxVertices:200000,radiusAt:v=>280*clamp(v.gr/ceiling),colorAt:v=>turboLinear(v.gr/ceiling)});
            const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(buffers.positions,3));geometry.setAttribute('color',new THREE.BufferAttribute(buffers.colors,3));geometry.setIndex(new THREE.BufferAttribute(buffers.indices,1));
            group.add(new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({vertexColors:true,toneMapped:false,side:THREE.DoubleSide})));
            if(metric==='cbl'){
              const centers=[];for(let i=0;i<buffers.faceSources.length;i+=40){const a=samples[buffers.faceSources[i]],b=samples[buffers.faceSources[i+1]];centers.push(a.x,a.y,a.z,b.x,b.y,b.z)}
              group.add(new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(centers,3)),new THREE.LineBasicMaterial({color:'#8496aa',transparent:true,opacity:.6,toneMapped:false})));
            }
          }
          return {permit:data.permit,source:data.source,unit:data.unit};
        }));
        group.userData.sources=responses;s.scene.add(group);
      }));
      logBox=new THREE.Box3().setFromObject(logs.gamma).union(new THREE.Box3().setFromObject(logs.cbl));
      const oil=await api.read('production.json',true);monthStart=oil.months.indexOf('2016-01');monthEnd=oil.months.indexOf('2024-12');if(monthStart<0||monthEnd<monthStart)throw Error('Production timeline unavailable.');
      setOil(false);api.clearSelection();s.controls.enabled=false;s.controls.enableDamping=false;s.navigation.reset();api.hideGrid();s.root.scale.y=1;
      s.renderer.setPixelRatio(1);s.renderer.setSize(plot.w,plot.h,false);s.camera.aspect=aspect;s.camera.updateProjectionMatrix();api.fit();
      clusterTarget=s.controls.target.clone();const offset=s.camera.position.clone().sub(clusterTarget);orbitDistance=offset.length()*.72;orbitAngle=Math.atan2(offset.x,offset.z);
      clusterTarget.y-=orbitDistance*.07;clusterTarget.x-=Math.cos(orbitAngle)*orbitDistance*.04;clusterTarget.z+=Math.sin(orbitAngle)*orbitDistance*.04;
      stateFrame=planFrame(s.reference.bounds,aspect);clusterFrame=planFrame(s.manifest.bounds,aspect,1.12);
      for(const group of Object.values(logs))group.visible=false;
      ready=true;$('tourRecord').disabled=!mime;$('tourScene').disabled=false;
      $('tourStatus').textContent=mime?'Ready · 50 seconds · 1920×1080 · state, views, 10 metrics, logs and oil · no audio':'Canvas recording unavailable in this browser.';
    }catch(e){$('tourStatus').textContent='Could not prepare tour: '+e.message;console.error(e)}
  }
  function changeShot(shot){
    lastShot=shot.key;const s=api.state(),oil=['oil','end'].includes(shot.key);
    s.surveyColors.setMode(METRICS[shot.key]?shot.key:'section');setOil(oil);
    if(oil){$('productionSize').value=7;$('productionSize').oninput({target:{value:7}})}
    for(const [key,group] of Object.entries(logs))group.visible=shot.key===key;
    s.root.visible=!['gamma','cbl'].includes(shot.key);
    $('tourScene').value=shot.key;
  }
  function pose(t,shot){
    const s=api.state();context.visible=t<8;context.material.opacity=.8*(1-ease((t-6.3)/1.7));s.reference.setVisible(t<8);api.hideGrid();
    if(t<10){
      activeCamera=ortho;const f=zoomFrame(stateFrame,clusterFrame,(t-2.8)/5.2),c=f.center;
      ortho.left=-f.half*aspect;ortho.right=f.half*aspect;ortho.top=f.half;ortho.bottom=-f.half;ortho.updateProjectionMatrix();ortho.position.set(c[0],3000000,c[2]);ortho.lookAt(...c);
    }else{
      activeCamera=perspective;perspective.up.set(0,1,0);
      if(t<12){
        // Perspective starts at the exact scale of the final plan frame at the
        // cluster depth center; a smooth tilt reveals its vertical dimension.
        const u=ease((t-10)/1.1),c=clusterFrame.center,theta=mix(.00001,Math.PI/2,u),azimuth=Math.PI/2*u,d=mix(perspectiveDistance(clusterFrame.half),orbitDistance*.82,u)*(1+.4*Math.sin(Math.PI*u));
        perspective.position.set(c[0]+Math.sin(theta)*Math.sin(azimuth)*d,c[1]+Math.cos(theta)*d,c[2]+Math.sin(theta)*Math.cos(azimuth)*d);perspective.lookAt(...c);
      }else if(['gamma','cbl'].includes(shot.key)){
        const center=logBox.getCenter(new THREE.Vector3()),size=logBox.getSize(new THREE.Vector3()),d=Math.max(size.y/2,size.x/(2*aspect))*1.22/Math.tan(Math.PI/8);
        perspective.position.set(center.x+d*.15,center.y+d*.06,center.z+d);perspective.lookAt(center);
      }else{
        const angle=orbitAngle-.17+(t-12)/38*.48,d=orbitDistance;
        const desired=clusterTarget.clone().add(new THREE.Vector3(Math.sin(angle)*d*.93,d*.37,Math.cos(angle)*d*.93));
        if(t<13){const u=ease(t-12),c=new THREE.Vector3(...clusterFrame.center),startPosition=c.clone().add(new THREE.Vector3(d*.82,0,0)),look=c.clone().lerp(clusterTarget,u);perspective.position.copy(startPosition.lerp(desired,u)).sub(look).multiplyScalar(1+.2*Math.sin(Math.PI*u)).add(look);perspective.lookAt(look)}else{perspective.position.copy(desired);perspective.lookAt(clusterTarget)}
      }
    }
    activeCamera.updateMatrixWorld();
  }
  function ramp(palette,x,y,width=450){const g=ctx.createLinearGradient(x,0,x+width,0);for(let i=0;i<=48;i++){const rgb=palette==='turbo'?turboSRGB(i/48):scaleRGB(i/48,palette);g.addColorStop(i/48,`rgb(${rgb.map(v=>Math.round(v*255)).join(',')})`)}ctx.fillStyle=g;ctx.fillRect(x,y,width,17)}
  const project=point=>{const p=point.clone().project(activeCamera);return {x:plot.x+(p.x+1)*plot.w/2,y:plot.y+(1-p.y)*plot.h/2,z:p.z}};
  function drawMapLabels(){
    ctx.save();ctx.beginPath();ctx.rect(plot.x,plot.y,plot.w,plot.h);ctx.clip();
    if(elapsed<6)for(const place of places){const p=project(place.point);if(p.x<plot.x+15||p.x>plot.x+plot.w-130||p.y<plot.y+35||p.y>plot.y+plot.h-25)continue;ctx.fillStyle='#cce3ee';ctx.beginPath();ctx.arc(p.x,p.y,4,0,Math.PI*2);ctx.fill();text(place.name,p.x+10,p.y-8,22,'#cce3ee',500)}
    if(elapsed<7.2){const p=project(new THREE.Vector3(clusterFrame.center[0],0,clusterFrame.center[2]));ctx.strokeStyle='#a3ff12';ctx.lineWidth=2;ctx.beginPath();ctx.arc(p.x,p.y,14,0,Math.PI*2);ctx.stroke();text('FEATURED WELLS',p.x+23,p.y+9,19,'#b9ed84',600)}
    text('N ↑',plot.x+28,plot.y+45,24,'#b3cedb',600);
    ctx.restore();
  }
  function draw(){
    const shot=shotAt(elapsed),s=api.state(),x=1420;
    ctx.fillStyle='#071523';ctx.fillRect(0,0,W,H);
    text('W',44,68,38,'#86e3d7',700);text('WELLBORE EXPLORER',102,67,28,'#e5f4fa',600);text('BAKKEN  /  NORTH DAKOTA',1390,65,23,'#8cabbf',500);
    text('From statewide context to individual wells.',42,130,42,'#f3f8fc',500);
    ctx.drawImage(s.renderer.domElement,plot.x,plot.y,plot.w,plot.h);ctx.strokeStyle='#264456';ctx.strokeRect(plot.x+.5,plot.y+.5,plot.w-1,plot.h-1);
    if(elapsed<10)drawMapLabels();
    text(shot.tag,x,216,20,'#86e3d7',600);text(shot.title,x,278,shot.key==='departure'?35:42,'#f2f8fc',500);paragraph(shot.note,x,340);
    if(['state','zoom'].includes(shot.key)){
      text(fullManifest.wells.length.toLocaleString(),x,573,65,'#86e3d7',600);text('survey branches',x,617,27,'#b7cddb');text((fullManifest.stations/1e6).toFixed(2)+' million',x,722,50,'#e7f1f8',500);text('survey stations',x,767,27,'#b7cddb');paragraph('Statewide overview → 31 wells / 65 branches in the featured cluster.',x,876,450,23,'#8fabbf',33);
    }else if(METRICS[shot.key]&&shot.key!=='section'){
      const spec=METRICS[shot.key];ramp(spec.cyclic?'cyclic':spec.signed?'signed':'thermal',x,515);
      if(spec.cyclic){['N','E','S','W','N'].forEach((v,i)=>text(v,x+i*108,567,23));paragraph('Bearings below 5° inclination are unavailable.',x,680,450,24);paragraph('The source azimuth reference is retained.',x,856,450,22,'#829fb2',32)}else{
        text(spec.signed?'NEGATIVE':'LOW',x,567,21,'#b2c9d9');text(spec.signed?'POSITIVE':'HIGH',x+340,567,21,'#b2c9d9');text('SCALED WITHIN EACH SECTION',x,638,20,'#86e3d7',600);
        let y=688;for(const id of [0,2,4]){const section=stats.sections.find(v=>v.id===id),key=shot.key==='curvature'?'dls':shot.key,range=automaticSectionBounds(shot.key,section.metrics[key]);text(section.label,x,y,23);if(range)text(range.map(v=>v.toLocaleString('en-US',{maximumFractionDigits:shot.key==='tortuosity'?4:2})).join(' – '),x+155,y,22,'#b7cddb');y+=45}
        text(spec.unit,x,850,23,'#b7cddb');paragraph('Automatic percentile ranges preserve variation within each section.',x,905,450,21,'#829fb2',30);
      }
    }else if(['gamma','cbl'].includes(shot.key)){
      ramp('turbo',x,530);text('0',x,582,24);text(shot.key==='gamma'?'300 API':'100 mV',x+340,582,24);text('100 FT MD MEANS',x,678,22,'#86e3d7',600);paragraph('Four matched wells • measured LAS curves • observed vertical paths',x,732,450,26);paragraph('Radius and color encode the measured value. Illustrative width, not bore diameter.',x,887,450,21,'#829fb2',30);
    }else if(['oil','end'].includes(shot.key)){
      text($('productionDateLabel').textContent,x,535,46,'#a3ff12',600);paragraph($('productionSummary').textContent,x,592,450,25,'#cfe2c4',37);
      const p=clamp((Number($('productionMonth').value)-monthStart)/(monthEnd-monthStart));ctx.fillStyle='#233b4b';ctx.fillRect(x,731,450,7);ctx.fillStyle='#a3ff12';ctx.fillRect(x,731,450*p,7);text('2016',x,783,23,'#9db5c8');text('2024',x+395,783,23,'#9db5c8');paragraph('Lateral width ∝ √monthly oil barrels',x,855,450,24,'#d9efb6');paragraph('Display symbols; survey geometry stays fixed through time.',x,929,450,20,'#829fb2',28);
    }else{
      const labels=[['#65b9ff','Vertical'],['#b79cff','Directional'],['#ffd84d','Curve'],['#ff665e','Drillback candidate'],['#a3ff12','Lateral']];let y=546;for(const [color,label]of labels){ctx.fillStyle=color;ctx.fillRect(x,y-17,29,6);text(label,x+48,y,26);y+=59}
      paragraph('31 wells • 65 recorded branches\nRelative TVD • actual survey paths',x,899,450,22,'#829fb2',33);
    }
    text(elapsed<8?'STATEWIDE SURVEY OVERVIEW  ·  NORTH DAKOTA REFERENCE BOUNDARY':'ACTUAL VIEWER RENDERING  ·  FEATURED CLUSTER: 31 WELLS / 65 BRANCHES',45,1032,18,'#7899ae',500);
    text('PLAN  /  3D  /  SURVEY METRICS  /  LOGS  /  PRODUCTION',1310,1032,17,'#7899ae');
    ctx.fillStyle='#86e3d7';ctx.fillRect(0,H-4,W*elapsed/DURATION,4);
    if(recording){const edge=Math.min(elapsed/.6,(DURATION-elapsed)/.6,1);if(edge<1){ctx.fillStyle=`rgba(7,21,35,${1-Math.max(0,edge)})`;ctx.fillRect(0,0,W,H)}}
  }
  $('tourScene').onchange=e=>{if(recording)return;const shot=TOUR_SHOTS.find(s=>s.key===e.target.value);elapsed=(shot.at+shot.end)/2;const v=$('tourPlayback');canvas.hidden=!!url;v.hidden=!url;if(url){v.pause();v.currentTime=elapsed}};
  $('tourRecord').onclick=()=>{
    if(!ready||recording||!mime)return;elapsed=0;start=performance.now();lastShot='';lastMonth=-1;frames=0;parts=[];recording=true;
    $('tourRecord').disabled=true;$('tourScene').disabled=true;$('tourDownload').hidden=true;$('tourReview').hidden=true;$('tourPlayback').hidden=true;canvas.hidden=false;
    const stream=canvas.captureStream(30);recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:12000000});recorder.ondataavailable=e=>{if(e.data.size)parts.push(e.data)};
    recorder.onerror=e=>{$('tourStatus').textContent='Recording failed: '+e.error.message;recording=false;stream.getTracks().forEach(t=>t.stop());$('tourRecord').disabled=false;$('tourScene').disabled=false};
    recorder.onstop=()=>{stream.getTracks().forEach(t=>t.stop());const blob=new Blob(parts,{type:recorder.mimeType});if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(blob);const mp4=recorder.mimeType.startsWith('video/mp4');$('tourDownload').href=url;$('tourDownload').download='Bakken-North-Dakota-Tour.'+(mp4?'mp4':'webm');$('tourDownload').textContent='Download '+(mp4?'MP4':'WebM')+' tour';$('tourDownload').hidden=false;$('tourPlayback').src=url;$('tourReview').hidden=false;$('tourRecord').disabled=false;$('tourScene').disabled=false;$('tourStatus').textContent=`Recording complete · ${(blob.size/1048576).toFixed(1)} MB · ${frames} rendered frames · 1920×1080 · ${recorder.mimeType}`};recorder.start(1000);
  };
  for(const [id,time]of [['tourReviewState',1.5],['tourReviewDls',18.5],['tourReviewLogs',37.5],['tourReviewOil',46]])$(id).onclick=()=>{const v=$('tourPlayback');v.hidden=false;canvas.hidden=true;v.pause();v.currentTime=time};
  return {
    camera:()=>ready?activeCamera:null,
    beforeRender(t){
      const s=api.state();if(!preparing&&s.manifest&&s.surveyColors.ready()&&!s.busy&&s.detail.size===s.manifest.tiles.length)prepare();if(!ready)return;
      if(s.renderer.domElement.width!==plot.w||s.renderer.domElement.height!==plot.h)s.renderer.setSize(plot.w,plot.h,false);
      if(recording)elapsed=Math.min(DURATION,(t-start)/1000);
      const shot=shotAt(elapsed);if(shot.key!==lastShot)changeShot(shot);pose(elapsed,shot);
      if(shot.key==='oil')setMonth(monthStart+Math.min(monthEnd-monthStart,Math.floor((elapsed-42)/6*(monthEnd-monthStart+1))));if(shot.key==='end')setMonth(monthEnd);
      s.production.update(t,activeCamera,plot.w,plot.h);
      if(recording)$('tourStatus').textContent=`Recording locally… ${Math.floor(elapsed)} / 50 seconds · ${shot.title}`;
    },
    afterRender(){if(!ready)return;draw();if(recording){frames++;if(elapsed>=DURATION){recording=false;recorder.stop()}}}
  };
}
