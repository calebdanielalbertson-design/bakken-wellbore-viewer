import * as THREE from 'three';
import {OrbitControls} from '/viewer/vendor/OrbitControls.js';
import {scaleRGB} from '/viewer/survey-colors.js';
import {bounds,center,transform,dominantDirection,intervals} from './tour-math.js';

const $=id=>document.getElementById(id), nf=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:0});
const sections=['Vertical','Directional','Curve','Drillback candidate','Lateral','Unknown'];
const sectionColors=['#65b9ff','#b79cff','#ffd84d','#ff665e','#a3ff12','#889eaa'];
const targetColors={'Middle Bakken':'#64c6f3','Three Forks 1':'#a4d929','Three Forks 2':'#ffa85c','Three Forks 3':'#b89aff'};
const configs={
  owan:{title:'A lateral that turns back.',subtitle:'Owan 5402 43-26 3BU · NDIC 41330',description:'Follow the recorded path, then move inside the U-turn. Compass colors make the heading reversal visible; inclination shows the smaller vertical changes.',steps:[
    {title:'Start with the recorded well paths',text:'The reviewed STK1 path is shown with VERT and the recorded LAT1 prefix as context. Their source endpoints coincide; these records are not a verified completed-well reconstruction.',view:'3d',color:'section'},
    {title:'Follow the heading reversal',text:'A close view of STK1 at MD 19,110–23,230 ft. Follow the compass colors around the bend; north wraps from 360° back to 0°.',view:'plan',color:'azimuth',lateral:true,detail:true},
    {title:'Look at the vertical variation',text:'The same turn, colored from 87° to 93° inclination. A 10× vertical display scale makes small changes easier to see; the measured angles remain unchanged.',view:'3d',color:'inclination',lateral:true,detail:true,exag:10}
  ]},
  nystuen:{title:'Follow an extended-reach lateral.',subtitle:'Nystuen 20-17-8-5 1H · NDIC 41872',description:'See the relationship between depth and horizontal reach. Explore the recorded lateral at its true display scale before looking more closely at vertical variation.',steps:[
    {title:'Depth and reach in one view',text:'The vertical and representative lateral records show the overall proportions. These are source survey branches; completion status has not been verified.',view:'3d',color:'section'},
    {title:'Look along the horizontal reach',text:'A north-up plan view isolates classified lateral intervals. The footage summary measures those intervals, rather than calling total measured depth the lateral length.',view:'plan',color:'azimuth',lateral:true},
    {title:'Inspect the vertical profile',text:'The lateral is shown from the side with 10× vertical exaggeration. Inclination colors use the original survey angles, with 90° representing horizontal.',view:'side',color:'inclination',lateral:true,exag:10}
  ]},
  torpedo:{title:'See the surface and subsurface together.',subtitle:'Torpedo Federal wells · Mountrail County',description:'Ten mapped Torpedo wells share a compact surface area beside Lake Sakakawea. Follow their paths outward, with the shoreline providing geographic context.',steps:[
    {title:'Begin at the shoreline',text:'The lake footprint and surface-hole locations establish the setting. The clipped water layer is a geographic reference, not a water-level or terrain model.',view:'plan',color:'section',context:true},
    {title:'Go below the surface',text:'Rotate the view to see the available vertical sections and representative lateral branches. The surface reference is translucent so the surveyed paths remain visible.',view:'3d',color:'section',context:true},
    {title:'Compare lateral directions',text:'Isolate the classified laterals and use compass colors to compare their headings. Select a well to identify its file number and recorded branch.',view:'plan',color:'azimuth',lateral:true,context:true}
  ]},
  hawkinson:{title:'Four targets. One pilot.',subtitle:'Hawkinson · 14 wells across four intervals',description:'Hawkinson explored stacked development in a 1,280-acre unit: four Middle Bakken wells and ten across Three Forks benches 1–3. Compare the published spacing design with the available survey paths.',steps:[
    {title:'See the stacked layout',text:'Four colors identify the published pilot targets. The available survey paths are shown at 10× vertical scale so their depth variations are easier to see.',view:'3d',color:'formation',lateral:true,exag:10},
    {title:'Look down the laterals',text:'Compare this end-on view with “Pilot spacing design”: 1,320 ft between same-zone wells, staggered by 660 ft in adjacent zones. Actual paths retain their source coordinates.',view:'end',color:'formation',lateral:true,exag:10},
    {title:'Return to the footprint',text:'A north-up plan view at 1× separates the horizontal pattern from vertical exaggeration. Select individual wells to compare their published targets and mapped branches.',view:'plan',color:'formation',lateral:true}
  ]}
};

let dataset,shoreline,tour,stepIndex=0,origin=[0,0,0],exaggeration=1,selectedFile='',view='3d',segments=[],renderPoints=[],plotBounds,meshList=[],surfaceMarkers=[];
const scene=new THREE.Scene();scene.background=new THREE.Color('#071724');
const camera=new THREE.OrthographicCamera(-1,1,1,-1,.01,1e8);
const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.outputColorSpace=THREE.SRGBColorSpace;
renderer.domElement.setAttribute('aria-label','Interactive mapped wellbore scene. Drag to rotate, right-drag to pan, scroll to zoom.');
renderer.domElement.setAttribute('tabindex','0');$('scene').append(renderer.domElement);
const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.12;controls.minZoom=.03;controls.maxZoom=400;controls.screenSpacePanning=true;
controls.addEventListener('start',()=>{$('view-label').textContent='Custom view';document.querySelectorAll('[data-view]').forEach(el=>el.setAttribute('aria-pressed','false'));});
const geometryGroup=new THREE.Group(),contextGroup=new THREE.Group();scene.add(geometryGroup,contextGroup);
const cylinder=new THREE.CylinderGeometry(1,1,1,8,1,false),raycaster=new THREE.Raycaster();
let dirty=true;controls.addEventListener('change',()=>{dirty=true;});
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function clearGroup(group){group.traverse(o=>{if(o.geometry&&o.geometry!==cylinder)o.geometry.dispose();if(o.material)for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose();});group.clear();}
function defaultBranches(w){return w.branches.filter(b=>b.selectedByDefault);}
function groupLabel(w){return w.historicalTarget||'Unassigned';}
function groupColor(w){return targetColors[groupLabel(w)]||'#92a5b3';}
function pointColor(p,w){
  const mode=$('color-mode').value;
  if(mode==='formation')return new THREE.Color(p[6]===4?groupColor(w):'#677d8a');
  if(mode==='section')return new THREE.Color(sectionColors[p[6]]||sectionColors[5]);
  const v=mode==='azimuth'?p[5]:p[4];if(!Number.isFinite(v)||(mode==='azimuth'&&p[4]<5))return new THREE.Color('#8395a1');
  const lateral=$('lateral-only').checked;
  const t=mode==='azimuth'?((v%360)+360)%360/360:lateral?(v-87)/6:v/95;
  return new THREE.Color().setRGB(...scaleRGB(t,mode==='azimuth'?'cyclic':'thermal'),THREE.SRGBColorSpace);
}
function collectSegments(){
  const lateral=$('lateral-only').checked,detail=configs[tour.id].steps[stepIndex].detail;
  const out=[];
  for(const w of tour.wells)for(const b of defaultBranches(w))for(const [a,p] of intervals(b)){
    if(b.displayMDRange&&(a[3]<b.displayMDRange[0]||p[3]>b.displayMDRange[1]))continue;
    if(lateral&&p[6]!==4)continue;
    if(detail&&(b.branch!=='STK1'||a[3]<19110||p[3]>23230))continue;
    out.push({a,p,w,b});
  }
  return out;
}
function rebuild(fit=true){
  clearGroup(geometryGroup);clearGroup(contextGroup);meshList=[];surfaceMarkers=[];
  exaggeration=Number($('exaggeration').value);segments=collectSegments();
  if(!segments.length){$('status').textContent='No valid survey intervals for this view.';return;}
  const sourcePoints=segments.flatMap(s=>[s.a,s.p]);origin=center(bounds(sourcePoints));
  const byWell=new Map();for(const s of segments){if(!byWell.has(s.w.file))byWell.set(s.w.file,[]);byWell.get(s.w.file).push(s);}
  renderPoints=[];
  const baseRadius=configs[tour.id].steps[stepIndex].detail?9:tour.id==='hawkinson'?11:tour.id==='torpedo'?17:23;
  const q=new THREE.Quaternion(),up=new THREE.Vector3(0,1,0),m=new THREE.Matrix4();
  for(const [file,rows] of byWell){
    const material=new THREE.MeshBasicMaterial({color:'#ffffff',transparent:true,opacity:selectedFile&&selectedFile!==file?.18:1,depthWrite:!selectedFile||selectedFile===file});
    const mesh=new THREE.InstancedMesh(cylinder,material,rows.length);mesh.userData.file=file;
    rows.forEach((s,i)=>{
      const aa=transform(s.a,origin,exaggeration),bb=transform(s.p,origin,exaggeration);renderPoints.push(aa,bb);
      const a=new THREE.Vector3(...aa),b=new THREE.Vector3(...bb),dir=b.clone().sub(a),len=dir.length();
      q.setFromUnitVectors(up,dir.normalize());const radius=s.b.displayRole==='recorded_connecting_context'?baseRadius*.7:baseRadius;m.compose(a.add(b).multiplyScalar(.5),q,new THREE.Vector3(radius,len,radius));mesh.setMatrixAt(i,m);mesh.setColorAt(i,s.b.displayRole==='recorded_connecting_context'?new THREE.Color('#8295a5'):pointColor(s.p,s.w));
    });
    mesh.instanceMatrix.needsUpdate=true;mesh.instanceColor.needsUpdate=true;mesh.computeBoundingSphere();geometryGroup.add(mesh);meshList.push(mesh);
  }
  plotBounds=bounds(renderPoints);buildContext();updateLegend();drawLocator();updateCaption();
  if(fit)fitCamera(view);dirty=true;
}
function buildContext(){
  const visible=$('show-context').checked;contextGroup.visible=visible;
  if(tour.id==='torpedo'&&shoreline){
    for(const polygon of shoreline.polygons){
      const ring=polygon.outer.map(p=>new THREE.Vector2(p[0]-origin[0],p[2]-origin[2]));
      const shape=new THREE.Shape(ring);for(const h of polygon.holes||[])shape.holes.push(new THREE.Path(h.map(p=>new THREE.Vector2(p[0]-origin[0],p[2]-origin[2]))));
      const geo=new THREE.ShapeGeometry(shape);geo.rotateX(Math.PI/2);geo.translate(0,(0-origin[1])*exaggeration,0);
      const mesh=new THREE.Mesh(geo,new THREE.MeshBasicMaterial({color:'#318fbd',transparent:true,opacity:view==='plan'?.2:.12,side:THREE.DoubleSide,depthWrite:false}));mesh.renderOrder=2;contextGroup.add(mesh);
    }
    for(const path of shoreline.shorelinePaths||[]){const geo=new THREE.BufferGeometry().setFromPoints(path.map(p=>new THREE.Vector3(...transform(p,origin,exaggeration))));const line=new THREE.Line(geo,new THREE.LineBasicMaterial({color:'#5bb6df',transparent:true,opacity:.65,depthWrite:false}));contextGroup.add(line);}
    for(const w of shoreline.surfaceWells||[]){
      const p=w.position||w.point;if(!p)continue;
      const dot=new THREE.Mesh(new THREE.SphereGeometry(40,10,8),new THREE.MeshBasicMaterial({color:'#f5f6dc'}));dot.position.set(...transform(p,origin,exaggeration));contextGroup.add(dot);surfaceMarkers.push(dot.position.toArray());
    }
  }else{
    const span=Math.max(plotBounds[3]-plotBounds[0],plotBounds[5]-plotBounds[2],1000),grid=new THREE.GridHelper(span*1.2,10,'#35586a','#153344');
    grid.position.set((plotBounds[0]+plotBounds[3])/2,plotBounds[1]-span*.03,(plotBounds[2]+plotBounds[5])/2);
    grid.material.transparent=true;grid.material.opacity=.4;contextGroup.add(grid);
  }
}
function fitCamera(kind=view,points=renderPoints){
  if(!points.length)return;view=kind;
  const b=bounds(points),c=new THREE.Vector3(...center(b)),axis=dominantDirection(segments.filter(s=>s.p[6]===4).flatMap(s=>[s.a,s.p]));
  let back;
  if(kind==='plan'){camera.up.set(0,0,-1);back=new THREE.Vector3(0,1,0);}
  else {camera.up.set(0,1,0);back=kind==='end'?new THREE.Vector3(...axis):kind==='side'?new THREE.Vector3(-axis[2],0,axis[0]):new THREE.Vector3(.8,.55,.75);back.normalize();}
  const span=Math.max(b[3]-b[0],b[4]-b[1],b[5]-b[2],500);
  camera.position.copy(c).addScaledVector(back,span*3+1000);controls.target.copy(c);camera.lookAt(c);camera.updateMatrixWorld();
  const right=new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,0),up=new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,1),ext=[Infinity,Infinity,-Infinity,-Infinity];
  for(const p of points){const d=new THREE.Vector3(...p).sub(c),x=d.dot(right),y=d.dot(up);ext[0]=Math.min(ext[0],x);ext[1]=Math.min(ext[1],y);ext[2]=Math.max(ext[2],x);ext[3]=Math.max(ext[3],y);}
  c.addScaledVector(right,(ext[0]+ext[2])/2).addScaledVector(up,(ext[1]+ext[3])/2);controls.target.copy(c);camera.position.copy(c).addScaledVector(back,span*3+1000);camera.lookAt(c);
  const rx=(ext[2]-ext[0])/2,uy=(ext[3]-ext[1])/2,aspect=Math.max(.1,$('scene').clientWidth/$('scene').clientHeight),half=Math.max(uy,rx/aspect,100)*1.23;
  camera.left=-half*aspect;camera.right=half*aspect;camera.top=half;camera.bottom=-half;camera.zoom=1;camera.near=.1;camera.far=span*20+1e6;camera.updateProjectionMatrix();controls.update();
  document.querySelectorAll('[data-view]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.view===kind)));
  $('view-label').textContent=({plan:'North-up plan',side:'Lateral side profile',end:'Gun-barrel view','3d':'3D oblique'})[kind];
  if(tour.id==='torpedo')for(const child of contextGroup.children)if(child.material?.side===THREE.DoubleSide)child.material.opacity=kind==='plan'?.2:.12;
  dirty=true;
}
function updateLegend(){
  const mode=$('color-mode').value,legend=$('legend');legend.replaceChildren();
  if(mode==='section'||mode==='formation'){
    const items=mode==='section'?sections.slice(0,5).map((n,i)=>[n,sectionColors[i]]):Object.entries(targetColors);
    if(tour.id==='owan'&&!configs[tour.id].steps[stepIndex].detail)items.push(['Recorded LAT1 context','#8295a5']);
    for(const [label,color]of items){const row=document.createElement('span');row.className='legend-item';const dot=document.createElement('i');dot.style.background=color;row.append(dot,document.createTextNode(label));legend.append(row);}
  }else{
    const ramp=document.createElement('span');ramp.className='metric-ramp';ramp.style.background='linear-gradient(90deg,'+Array.from({length:25},(_,i)=>`rgb(${scaleRGB(i/24,mode==='azimuth'?'cyclic':'thermal').map(v=>Math.round(v*255)).join(',')})`).join(',')+')';
    const label=document.createElement('span');label.textContent=mode==='azimuth'?'N 0° · E 90° · S 180° · W 270° · N 360°':$('lateral-only').checked?'Inclination 87° → 93° · 90° horizontal':'Inclination 0° → 95° from vertical';legend.append(ramp,label);
  }
}
function updateCaption(){
  $('scene-caption').textContent=`${exaggeration}× vertical display · Relative TVD · Enlarged line width for visibility${tour.id==='torpedo'&&$('show-context').checked?' · Lake at a schematic surface reference':''}`;
  $('hawkinson-notice').hidden=tour.id!=='hawkinson';
}
function showDesign(enabled){
  const design=enabled&&tour?.id==='hawkinson';
  $('spacing-design').hidden=!design;$('survey-scene').hidden=design;
  $('show-surveys').setAttribute('aria-pressed',String(!design));$('show-design').setAttribute('aria-pressed',String(design));
  document.querySelector('.scene-toolbar').hidden=design;document.querySelector('.display-toolbar').hidden=design;$('scene-caption').hidden=design;
  $('focus-well').disabled=design||!selectedFile;
  const url=new URL(location.href);if(design)url.searchParams.set('comparison','design');else url.searchParams.delete('comparison');history.replaceState({},'',url);
  if(!design){resize();dirty=true;}
}
function selectWell(file){
  selectedFile=file;$('well-select').value=file;$('focus-well').disabled=!file||!$('spacing-design').hidden;
  const w=tour.wells.find(w=>w.file===file);
  $('selected-well').textContent=w?`${w.name} · NDIC ${w.file} · API ${w.api}. Displayed records: ${defaultBranches(w).map(b=>b.branch).join(', ')}.${tour.id==='hawkinson'?' Published pilot target: '+groupLabel(w)+'. Current completion interval unverified.':''}`:'Select a path or choose a well to inspect its recorded branches.';
  for(const m of meshList){m.material.opacity=!file||m.userData.file===file?1:.16;m.material.depthWrite=!file||m.userData.file===file;}
  drawLocator();dirty=true;
}
function drawLocator(){
  const canvas=$('locator'),ctx=canvas.getContext('2d');canvas.width=300;canvas.height=180;ctx.fillStyle='#0b2230';ctx.fillRect(0,0,300,180);
  const all=tour.wells.flatMap(w=>defaultBranches(w).flatMap(b=>b.points)),b=bounds(all),margin=25,dx=b[3]-b[0],dz=b[5]-b[2],scale=Math.min((300-margin*2)/Math.max(dx,1),(180-margin*2)/Math.max(dz,1));
  const cx=(b[0]+b[3])/2,cz=(b[2]+b[5])/2,xy=p=>[150+(p[0]-cx)*scale,90+(p[2]-cz)*scale];
  if(tour.id==='torpedo'&&shoreline){ctx.fillStyle='#205775';for(const poly of shoreline.polygons){ctx.beginPath();for(const r of [poly.outer,...poly.holes]){r.forEach((p,i)=>{const [x,y]=xy(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.closePath();}ctx.fill('evenodd');}}
  for(const w of tour.wells){ctx.strokeStyle=selectedFile&&selectedFile!==w.file?'#355360':w.file===selectedFile?'#ffffff':'#8dcbdc';ctx.lineWidth=w.file===selectedFile?2:1;for(const branch of defaultBranches(w))for(const [a,p]of intervals(branch)){ctx.beginPath();ctx.moveTo(...xy(a));ctx.lineTo(...xy(p));ctx.stroke();}}
  ctx.fillStyle='#dbedf5';ctx.font='11px Segoe UI';ctx.fillText('N ↑',12,19);ctx.fillText('Plan locator · Same featured wells',12,168);
}
function applyStep(){
  showDesign(false);
  const step=configs[tour.id].steps[stepIndex];$('tour-step').textContent=`${stepIndex+1} / ${configs[tour.id].steps.length}`;$('step-title').textContent=step.title;$('step-description').textContent=step.text;
  $('prev-step').disabled=stepIndex===0;$('next-step').disabled=stepIndex===configs[tour.id].steps.length-1;
  $('mobile-step-title').textContent=`${stepIndex+1} / 3 · ${step.title}`;$('mobile-prev').disabled=$('prev-step').disabled;$('mobile-next').disabled=$('next-step').disabled;
  $('color-mode').value=step.color;$('exaggeration').value=String(step.exag||1);$('lateral-only').checked=!!step.lateral;$('show-context').checked=!!step.context;
  view=step.view;selectedFile='';$('well-select').value='';selectWell('');rebuild();
  const url=new URL(location.href);url.searchParams.set('tour',tour.id);url.searchParams.set('step',String(stepIndex+1));history.replaceState({},'',url);
}
function changeTour(id,step=0){
  tour=dataset.tours.find(t=>t.id===id)||dataset.tours[0];const c=configs[tour.id];stepIndex=Math.max(0,Math.min(c.steps.length-1,Number.isFinite(step)?Math.trunc(step):0));
  $('title').textContent=c.title;$('subtitle').textContent=c.subtitle;$('description').textContent=c.description;
  document.querySelectorAll('[data-tour]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.tour===tour.id)));
  $('color-mode').querySelector('option[value="formation"]').disabled=tour.id!=='hawkinson';
  $('hawkinson-comparison').hidden=tour.id!=='hawkinson';
  $('well-select').innerHTML='<option value="">All featured wells</option>'+tour.wells.map(w=>`<option value="${escape(w.file)}">${escape(w.name)} · ${escape(w.file)}</option>`).join('');
  const records=tour.wells.reduce((n,w)=>n+defaultBranches(w).length,0),stations=tour.wells.reduce((n,w)=>n+defaultBranches(w).reduce((m,b)=>m+b.points.filter(p=>!b.displayMDRange||(p[3]>=b.displayMDRange[0]&&p[3]<=b.displayMDRange[1])).length,0),0);
  const lateral=tour.wells.reduce((n,w)=>n+(w.lateralLength?.mdFt||0),0);
  $('metrics').innerHTML=`<div><strong>${tour.wells.length}</strong><span>featured ${tour.wells.length===1?'well':'wells'}</span></div><div><strong>${nf(lateral)}</strong><span>mapped lateral ft*</span></div><div><strong>${nf(stations)}</strong><span>selected stations</span></div>`;
  $('source-details').innerHTML=`<p>ND DMR horizontal survey snapshot: October 17, 2026. ${records} selected branch records. *Footage sums valid MD intervals ending in the lateral class, within the selected representative branches. It is not completed footage or a reserve estimate.</p><p>One representative lateral per well plus available VERT context. Owan uses the reviewed STK1 branch; other wells use the longest mapped classified lateral. Other recorded branches are retained in the source data but not drawn in this tour.</p><p>Coordinates use the existing NAD83-based viewer projection. TVD is relative to each well’s source reference. No common elevation correction, terrain, verified formation surfaces or completion status is supplied.</p>${tour.id==='hawkinson'?'<p>The published target mix is 4 Middle Bakken, 3 TF1, 4 TF2 and 3 TF3 wells. <a href="https://www.sec.gov/Archives/edgar/data/732834/000119312514070582/d685311dex991.htm" target="_blank" rel="noopener">Continental’s historical pilot report</a></p>':''}${tour.id==='torpedo'?'<p>Water footprint: ND DMR MissouriRiver dataset, LAKE SAKAKAWEA polygons, clipped to this view. Geographic outline only; clipping boundaries are not shoreline. <a href="https://gis.dmr.nd.gov/gisdownload.asp" target="_blank" rel="noopener">Source downloads</a></p>':''}`;
  if(tour.id==='owan')$('source-details').insertAdjacentHTML('beforeend','<p>Owan also displays the actual LAT1 prefix at MD 10,008–18,450 ft in gray. Its endpoints exactly match the VERT and STK1 records. The alternate LAT1 tail is excluded; the lateral-footage summary remains STK1 only.</p>');
  if(tour.id==='hawkinson')$('source-details').insertAdjacentHTML('beforeend','<p>Historical pilot targets: MB 5, 8, 3, 13; TF1 1, 10, 2; TF2 4, 7, 11, 14; TF3 6, 9, 12. Numbered Hawkinson names are matched to the Continental design reproduced in the <a href="https://ndlegis.gov/files/committees/63-2013nma/appendices/15_5090_03000appendixl.pdf#page=4" target="_blank" rel="noopener">April 2014 EERC presentation, slide 7</a>. The 1,320 ft / 660 ft values describe the published design, not measurements of every mapped branch. Current selected sidetracks may differ from original pilot completions. The earlier upper/lower TVD proxy is retained in the source data for comparison but no longer determines these colors.</p>');
  $('status').textContent='Ready · Actual mapped paths';applyStep();
}
function resize(){const w=$('scene').clientWidth,h=$('scene').clientHeight;if(w&&h){renderer.setSize(w,h,false);if(renderPoints.length){const half=(camera.top-camera.bottom)/2;camera.left=-half*w/h;camera.right=half*w/h;camera.updateProjectionMatrix();}dirty=true;}}
let pointerStart;renderer.domElement.addEventListener('pointerdown',e=>pointerStart=[e.clientX,e.clientY]);
renderer.domElement.addEventListener('pointerup',e=>{if(!pointerStart||Math.hypot(e.clientX-pointerStart[0],e.clientY-pointerStart[1])>5)return;const r=renderer.domElement.getBoundingClientRect();raycaster.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);const hit=raycaster.intersectObjects(meshList)[0];if(hit)selectWell(hit.object.userData.file);});
new ResizeObserver(resize).observe($('scene'));resize();
function animate(){requestAnimationFrame(animate);controls.update();if(dirty){renderer.render(scene,camera);renderer.domElement.dataset.renderedTour=tour?.id||'';renderer.domElement.dataset.renderedStep=String(stepIndex+1);dirty=false;}}animate();
document.querySelectorAll('[data-tour]').forEach(el=>el.onclick=()=>changeTour(el.dataset.tour));
document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>fitCamera(el.dataset.view));
$('prev-step').onclick=()=>{if(stepIndex>0){stepIndex--;applyStep();}};$('next-step').onclick=()=>{if(stepIndex<configs[tour.id].steps.length-1){stepIndex++;applyStep();}};
$('mobile-prev').onclick=$('prev-step').onclick;$('mobile-next').onclick=$('next-step').onclick;
$('show-surveys').onclick=()=>showDesign(false);$('show-design').onclick=()=>showDesign(true);
$('color-mode').onchange=()=>rebuild(false);$('exaggeration').onchange=()=>rebuild();$('lateral-only').onchange=()=>rebuild();$('show-context').onchange=()=>{contextGroup.visible=$('show-context').checked;updateCaption();dirty=true;};
$('reset-view').onclick=()=>fitCamera(view);$('well-select').onchange=e=>selectWell(e.target.value);
$('focus-well').onclick=()=>{const rows=segments.filter(s=>s.w.file===selectedFile);fitCamera(view,rows.flatMap(s=>[transform(s.a,origin,exaggeration),transform(s.p,origin,exaggeration)]));};
try{
  const responses=await Promise.all([fetch('./data/tours.json'),fetch('./data/shoreline.json')]);
  if(!responses[0].ok)throw Error('The tour dataset is unavailable.');
  dataset=await responses[0].json();shoreline=responses[1].ok?await responses[1].json():null;
  const params=new URLSearchParams(location.search);changeTour(params.get('tour')||'owan',Number(params.get('step')||1)-1);
  if(params.get('comparison')==='design')showDesign(true);
}catch(error){$('status').textContent='Could not load this tour: '+error.message;console.error(error);}
