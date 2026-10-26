import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';
import {createReferencePlane} from './reference-plane.js';
import {trajectoryPivot,framingRadius,createWellNavigation,switchCameraOrientation} from './navigation.js';
import {createProductionController} from './production.js';
import {pickScreenSegments} from './picking.js';
import {createGammaController} from './gamma.js';
import {createSurveyColors} from './survey-colors.js';
import {createDSUController} from './dsu.js';
import {createDSUWellController} from './dsu-wells.js';
import {createFootageController} from './footage.js';
import {createMobileControls} from './mobile-controls.js';
import {validateWellNames,createWellSearch} from './well-search.js';
import {validateWellShapes,UTURN_COLOR} from './well-shapes.js';
import {createSidebarController} from './sidebar.js';
const $=id=>document.getElementById(id),palette=['#65b9ff','#b79cff','#ffd84d','#ff665e','#a3ff12','#9fadb8'];
const scene=new THREE.Scene();scene.background=new THREE.Color('#071523');
const perspectiveCamera=new THREE.PerspectiveCamera(45,1,1,10000000);const planCamera=new THREE.OrthographicCamera(-1,1,1,-1,.1,10000000);let camera=perspectiveCamera,planActive=false,referenceReady=Promise.resolve();const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));$('canvasHost').appendChild(renderer.domElement);
const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.1;
const navigation=createWellNavigation(controls,()=>camera);
const root=new THREE.Group();scene.add(root);let grid,manifest,overview,source,epoch=0,selected=null,selectedData=null,highlight=null,overviewLines=[],detail=new Map(),visibleSections=new Set([0,1,2,3,4,5]),lastUpdate=0,busy=false;
const colorFloats=palette.map(c=>new THREE.Color(c));let overviewCounts=[];
let operatorFilter='all',wellContext='normal';
let wellShapes=null,shapeColorsEnabled=true,showUTurnLaterals=true;
const uturnRGB=new THREE.Color(UTURN_COLOR).toArray();
let wellNames=new Map(),wellSearch=null,wellNamesLoading=false;
const pathColors=new WeakMap();
let dsuScope=null,dsuOverlay=null,dsuHighlightVersion=0,lastDsuHighlightKey='';
const reference=createReferencePlane(scene,$('mapLabels'));
const production=createProductionController();
let mobileControls,sidebar,selectionTarget='well',selectionKind=null,viewOrientation='perspective';
const surveyColors=createSurveyColors({sectionColor:(section,id,row,tile)=>{const shape=displayShape(section,id,row,tile);return shape.uturn?uturnRGB:shape.section!==section?colorFloats[shape.section].toArray():null},changed:()=>{production.setSurveyColoring(surveyColors.active());renderSelection();syncGammaContext();mobileControls?.sync();sidebar?.sync()}});
const gamma=createGammaController(root,{changed:syncGammaContext,focus:bounds=>{if(planActive)setPlanMode(false,bounds);fit(bounds,'side');navigation.begin(150);say('Log radius and color on observed vertical survey branches. Drag to orbit; hover for measured value and depth.');},selectWell:permit=>{const w=manifest?.wells.find(w=>w.permit===permit&&w.branch==='VERT');if(w)select(w);}});
const dsuWells=createDSUWellController({changed:syncDSUSelection,visible:operatorVisible,selectWell:w=>select(w,true,{keepDSUScope:true}),play:()=>production.playScope(),clear:()=>dsu.clearSelection()});
const dsu=createDSUController(root,{focus:bounds=>{fit(bounds);navigation.begin(150);say('Centered on the selected DSU. Depth interval is approximate.');},say:s=>$('message').textContent=s,selectionChanged:onDSUSelection,footageRequested:key=>footage.activateDSU(key)});
const footage=createFootageController(scene,{dsu,focus:bounds=>{fit(bounds);navigation.begin(150);say('Centered on the selected township. Metrics cover eligible DSU land.');},say:s=>say(s)});
mobileControls=createMobileControls({surveyColors,production,dsu,footage,setWellContext});
sidebar=createSidebarController({surveyColors,production,dsu,footage,setWellContext,resetView,getSelection,setSelectionTarget,getSelectionTarget:()=>selectionTarget,configureArea});
document.addEventListener('viewer:layers-changed',()=>{normalizeSelectionTarget();sidebar?.sync()});
document.addEventListener('viewer:selection-changed',event=>{
  if(event.detail?.kind!=='township')return;
  if(event.detail.selected&&event.detail.interactive!==false){dsu.clearSelection();clearSelection();selectionKind='township';$('selectedToolbar').hidden=true;setSelectionTarget('township')}
  else if(!event.detail.selected&&selectionKind==='township')selectionKind=selected?'well':dsu.selection()?'dsu':null;
  sidebar?.sync();
});
$('wellContextMode').onchange=e=>setWellContext(e.target.value);
$('mobileWellContext').onchange=e=>setWellContext(e.target.value);
$('surveyColorMode').addEventListener('change',()=>setWellContext('normal'));
let showcase=null;
if(!new URLSearchParams(location.search).has('showcase'))import('./highlights.js').then(({installHighlights})=>installHighlights({state:()=>({camera,controls,manifest,planActive}),fit,select,clearSelection,orientView,surveyColors,setWellContext})).catch(e=>console.warn('Highlights unavailable:',e));
if(new URLSearchParams(location.search).has('showcase'))import(new URLSearchParams(location.search).get('showcase')==='tour'?'./tour.js':'./showcase.js').then(({createShowcase})=>{showcase=createShowcase({state:()=>({renderer,scene,camera,controls,navigation,manifest,detail,busy,surveyColors,production,reference,root}),read,fit,clearSelection,referenceReady:()=>referenceReady,hideGrid(){if(grid)grid.visible=false;},hideReference(){reference.setVisible(false);dsu.setVisible(false);if(grid)grid.visible=false;}})});
function onDSUSelection(unit,{interactive=true}={}){
  dsuWells.select(unit);
  if(unit&&interactive){clearSelection();footage.clearSelection();selectionKind='dsu';$('selectedToolbar').hidden=true;setSelectionTarget('dsu')}
  else if(!unit&&selectionKind==='dsu')selectionKind=selected?'well':footage.selection()?'township':null;
  sidebar?.sync();
}
function getSelection(){
  if(selectionKind==='well'&&selected)return{kind:'well',label:wellSearch?.nameForBranch(selected.id)||`File ${selected.permit}`,zoom:zoomToSelected,clear:clearSelection};
  const unit=dsu.selection(),town=footage.selection();
  if(selectionKind==='dsu'&&unit)return{kind:'dsu',label:unit.properties.label,zoom:()=>dsu.zoomSelection(),clear:()=>dsu.clearSelection()};
  if(selectionKind==='township'&&town)return{kind:'township',label:town.properties?.label||town.label,zoom:()=>footage.zoomSelection(),clear:()=>footage.clearSelection()};
  return null;
}
function normalizeSelectionTarget(){
  if(selectionTarget==='dsu'&&!$('dsuEnabled').checked||selectionTarget==='township'&&!footage.townshipVisible())selectionTarget='well';
  $('dsuInspect').checked=selectionTarget==='dsu';$('townshipInspect').checked=selectionTarget==='township';
}
function setSelectionTarget(value){
  if(!['well','dsu','township'].includes(value))return;
  selectionTarget=value;normalizeSelectionTarget();sidebar?.sync();
}
async function configureArea(value){
  if(!['none','dsu','township'].includes(value))return;
  if(value==='none'){
    footage.setTownshipVisible(false);dsu.setVisible(false);$('footageEnabled').checked=false;$('footageEnabled').dispatchEvent(new Event('change'));setSelectionTarget('well');
  }else if(value==='dsu'){
    footage.setTownshipVisible(false);const ready=dsu.setVisible(true);setSelectionTarget('dsu');setWellContext('faint');await ready;
  }else{
    dsu.setVisible(false);const ready=footage.setTownshipVisible(true);setSelectionTarget('township');setWellContext('faint');await ready;
  }
  normalizeSelectionTarget();sidebar?.sync();
}
function resetView(){
  if(!manifest)return;
  configureArea('none');dsu.clearSelection();footage.clearSelection();clearSelection();production.setEnabled(false);
  // Set all geometry-affecting defaults together, then build the survey paths
  // once. Dispatching each legacy checkbox handler rebuilt millions of points.
  visibleSections=new Set([0,1,2,3,4,5]);showUTurnLaterals=true;shapeColorsEnabled=true;
  $('showUTurnLaterals').checked=true;$('trajectoryShapes').checked=true;$('uturnLegend').hidden=!wellShapes;
  document.querySelectorAll('#legend input').forEach(c=>c.checked=true);
  setOperatorFilter('all',{rebuildGeometry:false});surveyColors.setMode('section');setWellContext('normal');
  $('search').value='';renderWellSearch();$('dsuSearch').value='';$('dsuSearch').dispatchEvent(new Event('input'));$('townshipSearch').value='';$('townshipSearch').dispatchEvent(new Event('input'));
  for(const [id,value] of [['dsuFilter','all'],['dsuLayout','nested'],['dsuDepthSeparation','0'],['dsuColor','acreage'],['footageScenario','base']]){if($(id).value===value)continue;$(id).value=value;$(id).dispatchEvent(new Event('change'))}
  // Depth inputs may contain unapplied edits, so reset their authoritative
  // controller values even when the displayed inputs already read zero.
  $('dsuResetDepth').click();
  $('dsuOpacity').value='9';$('dsuOpacity').dispatchEvent(new Event('input'));
  if(overview)rebuild();showClassifier();$('showState').checked=true;syncReference();
  const previous=root.scale.y;root.scale.y=1;navigation.rescaleDepth(previous,1);$('scale').value='1';$('scaleValue').textContent='1×';
  if(manifest){orientView('perspective');fit(manifest.bounds)}
  const url=new URL(location.href);for(const key of ['color','inventory','scenario','dsu','production'])url.searchParams.delete(key);history.replaceState(null,'',url);
  sidebar?.setTab('wells');sidebar?.sync();say('View reset. All operators, well-section colors, and no area or production overlays.');
}
function displayShape(section,id,row,tile=null){
  return wellShapes?.shapeFor(section,id,row,tile,shapeColorsEnabled)||{section,uturn:false};
}
function pathVisible(section,id,row,tile=null){
  const shape=displayShape(section,id,row,tile);
  return shape.uturn?showUTurnLaterals:visibleSections.has(shape.section);
}
async function loadWellShapes(m,manifestBytes,version){
  wellShapes=null;$('trajectoryShapes').disabled=true;$('uturnLegend').hidden=true;
  $('shapeStatus').textContent='Saved section colors for this dataset.';
  if(!m.sourceSnapshot)return;
  try{
    const [raw,manifestDigest,overviewDigest]=await Promise.all([read('well-shape-overlays.json',true),crypto.subtle.digest('SHA-256',manifestBytes),crypto.subtle.digest('SHA-256',overview.buffer)]);
    if(version!==epoch)return;
    const hex=value=>Array.from(new Uint8Array(value),v=>v.toString(16).padStart(2,'0')).join('');
    wellShapes=validateWellShapes(raw,m,{manifestSHA256:hex(manifestDigest),overviewSHA256:hex(overviewDigest),overview});
    $('trajectoryShapes').disabled=false;$('uturnLegend').hidden=false;
    $('shapeStatus').textContent=`Continuous drillback intervals · ${num(wellShapes.summary.uturnBranches)} U-turn laterals. Toggle off to compare saved sections.`;
  }catch(error){if(version===epoch)$('shapeStatus').textContent='Trajectory refinements unavailable or do not match this snapshot; saved section colors are shown.';}
}
$('trajectoryShapes').onchange=e=>{shapeColorsEnabled=e.target.checked;$('uturnLegend').hidden=!wellShapes||!shapeColorsEnabled;if(overview)rebuild();showClassifier()};
$('showUTurnLaterals').onchange=e=>{showUTurnLaterals=e.target.checked;if(overview)rebuild()};
function setWellContext(value){
  if(!['normal','faint','hidden'].includes(value))return;
  wellContext=value;$('wellContextMode').value=value;$('mobileWellContext').value=value;
  production.setWellContext(value);emphasizeSelection();syncGammaContext();
  sidebar?.sync();
}
function syncGammaContext(){
  const visible=gamma.contextVisible()&&wellContext!=='hidden';
  for(const l of [...overviewLines,...[...detail.values()].flatMap(d=>d.lines)]){
    l.visible=visible;
    if(!l.material.isShaderMaterial){
      if(!pathColors.has(l.material))pathColors.set(l.material,l.material.color.clone());
      const colored=wellContext!=='faint'&&!!l.geometry.attributes.color;
      if(l.material.vertexColors!==colored){l.material.vertexColors=colored;l.material.needsUpdate=true}
      l.material.color.copy(wellContext==='faint'?new THREE.Color('#8fa5b5'):pathColors.get(l.material));
    }
  }
  // Emphasis stays out of the way while the map is the main subject.
  if(highlight)highlight.visible=visible&&wellContext==='normal';
  if(dsuOverlay)dsuOverlay.visible=visible&&wellContext==='normal';
}
function syncDSUSelection(state){
  dsuScope=state?new Set(state.branchIds):null;dsuHighlightVersion++;
  production.setScopeHistory(state?{title:state.label,totalWells:state.rows.length}:null);
  const visible=manifest?.wells.filter(w=>operatorVisible(w.id)),ids=state?state.branchIds:operatorFilter==='all'?null:visible?.map(w=>w.id)||[];
  production.setBranchScope(ids,state?state.label+(operatorFilter==='all'?'':' · operator filter'):'operator filter');production.highlightBranches(state?.branchIds??null);
  emphasizeSelection();refreshDSUHighlight();
}
function refreshDSUHighlight(){
  const key=`${epoch}|${dsuHighlightVersion}|${[...detail.keys()].join(',')}|${operatorFilter}|${[...visibleSections].join(',')}`;
  if(lastDsuHighlightKey===key)return;lastDsuHighlightKey=key;
  if(dsuOverlay){dispose(dsuOverlay);dsuOverlay=null}if(!dsuScope||!manifest)return;
  const positions=[];for(const l of [...overviewLines,...[...detail.values()].flatMap(d=>d.lines)]){const p=l.geometry.attributes.position.array,ids=l.userData.ids;for(let i=0;i<ids.length;i++)if(dsuScope.has(ids[i])){const j=i*6;if(p[j]!==p[j+3]||p[j+1]!==p[j+4]||p[j+2]!==p[j+5])for(let k=0;k<6;k++)positions.push(p[j+k])}}
  if(positions.length){dsuOverlay=line(positions,null,[]);dsuOverlay.material.color.set('#8df5ee');dsuOverlay.material.depthTest=false;dsuOverlay.renderOrder=1;dsuOverlay.visible=gamma.contextVisible()&&wellContext==='normal'}
}

const num=n=>n.toLocaleString('en-US');const say=s=>$('message').textContent=s;
function buildWellSearch(){
  wellSearch=createWellSearch(manifest,{names:wellNames,operatorNameForBranch:id=>surveyColors.operatorModel()?.nameForBranch(id)||'',operatorGroupForBranch:id=>surveyColors.operatorModel()?.forBranch(id)?.label||'',visible:operatorVisible});
}
function renderWellSearch(){
  const host=$('results'),query=$('search').value;host.replaceChildren();
  if(!query.trim()||!wellSearch)return;
  const {rows,total}=wellSearch.search(query,30),status=document.createElement('p');status.setAttribute('role','status');
  status.textContent=total?`${num(total)} mapped well${total===1?'':'s'}${total>rows.length?` · showing ${rows.length}`:''}`:wellNamesLoading?'No matches yet. Well names are still loading.':'No matching mapped wells. Try part of a name, a file number, or an API.';host.append(status);
  if(!total&&operatorFilter!=='all'){const clear=document.createElement('button');clear.textContent='Search all operators';clear.onclick=()=>setOperatorFilter('all');host.append(clear)}
  for(const {well,name,branchCount}of rows){
    const button=document.createElement('button');button.type='button';
    const title=document.createElement('strong');title.className='search-result-title';title.textContent=name||`File ${well.permit}`;
    const details=document.createElement('small');details.textContent=`${name?`File ${well.permit} · `:''}API ${well.api} · ${branchCount} branch${branchCount===1?'':'es'}`;
    button.append(title,details);button.onclick=()=>{if(matchMedia('(max-width:560px)').matches){$('search').blur();$('viewport').scrollIntoView({block:'start'})}select(well,true)};host.append(button);
  }
}
function renderWellIdentity(){
  if(!selected)return;const w=selected,name=wellSearch?.nameForBranch(w.id)||'';
  const title=$('selectedWellTitle'),info=$('selectedWellIdentity');
  if(title)title.textContent=name||`File ${w.permit}`;
  if(info)info.textContent=`${name?`File ${w.permit} · `:''}API ${w.api} · ${w.branch}`;
  $('selectedName').textContent=name?`${name} · ${w.permit}`:`${w.permit} · ${w.branch}`;
  $('selectedName').title=name?`${name} · File ${w.permit} · ${w.branch}`:`File ${w.permit} · ${w.branch}`;
  sidebar?.sync();
}
async function startWellSearch(m,manifestBytes,getter,version){
  wellNamesLoading=true;buildWellSearch();$('search').disabled=false;$('mobileWellSearch').disabled=false;
  $('wellNameStatus').textContent='Loading well names… File numbers and APIs are searchable now.';
  try{
    const [raw,digest]=await Promise.all([getter('well-names.json'),crypto.subtle.digest('SHA-256',manifestBytes)]);
    if(version!==epoch)return;
    const hash=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');
    wellNames=validateWellNames(JSON.parse(new TextDecoder().decode(raw)),m,hash);buildWellSearch();
    $('wellNameStatus').textContent=`Names available for ${num(wellSearch.namedCount)} of ${num(wellSearch.totalCount)} mapped wells. Results follow the operator filter.`;
    renderWellIdentity();
  }catch(error){if(version!==epoch)return;$('wellNameStatus').textContent='Well names are unavailable for this dataset. File number, API, branch and operator searches still work.';}
  finally{if(version===epoch){wellNamesLoading=false;renderWellSearch()}}
}
function dispose(obj){obj.traverse(child=>{child.geometry?.dispose();if(Array.isArray(child.material))child.material.forEach(m=>m.dispose());else child.material?.dispose()});obj.removeFromParent()}
function clear(){overviewLines.forEach(dispose);overviewLines=[];for(const a of detail.values())a.lines.forEach(dispose);detail.clear();if(highlight){dispose(highlight);highlight=null}if(dsuOverlay){dispose(dsuOverlay);dsuOverlay=null}lastDsuHighlightKey=''}
async function read(name,json=false){const r=await source(name);return json?JSON.parse(new TextDecoder().decode(r)):r}
function line(positions,colors,ids){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));if(colors)g.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));g.computeBoundingSphere();const l=new THREE.LineSegments(g,new THREE.LineBasicMaterial({vertexColors:!!colors,color:colors?0xffffff:0xffffff,transparent:true,opacity:1}));l.userData.ids=ids;root.add(l);return l}
function buildSegments(data,isOverview=false,wells=[]){
  const pos=Array.from({length:6},()=>[]),ids=Array.from({length:6},()=>[]),rows=Array.from({length:6},()=>[]);
  const push=(a,b,sec,id,row)=>{if(!pathVisible(sec,id,row,isOverview?null:wells[0]?.tile)||!operatorVisible(id))return;pos[sec].push(...a,...b);ids[sec].push(id);rows[sec].push(row)};
  if(isOverview){for(let i=0;i<data.length;i+=8)push(data.subarray(i,i+3),data.subarray(i+3,i+6),data[i+6],data[i+7],i/8)}
  else for(const w of wells)for(let i=w.offset+1;i<w.offset+w.count;i++){const j=i*4;push(data.subarray(j-4,j-1),data.subarray(j,j+3),data[j+3],w.id,i)}
  return pos.map((p,section)=>{if(!p.length)return null;const l=line(p,null,ids[section]);l.userData.section=section;l.userData.uturnMask=Uint8Array.from(rows[section],(row,i)=>displayShape(section,ids[section][i],row,isOverview?null:wells[0].tile).uturn?1:0);surveyColors.decorate(l,rows[section],isOverview?null:wells[0].tile);if(section===4)production.decorate(l);return l}).filter(Boolean);
}
function rebuild(){overviewLines.forEach(dispose);overviewLines=buildSegments(overview,true);for(const [key,d] of detail){d.lines.forEach(dispose);d.lines=buildSegments(d.data,false,manifest.wells.filter(w=>w.tile===key))}renderSelection();updateOverview();}
function updateOverview(){const loaded=new Set(detail.keys());for(const l of overviewLines){const id=l.userData.ids,p=l.geometry.attributes.position; // Collapse overview segments replaced by detailed tiles, retaining the originals for unload.
if(!l.userData.original)l.userData.original=p.array.slice();const orig=l.userData.original;for(let i=0;i<id.length;i++){const j=i*6;const hidden=loaded.has(manifest.wells[id[i]].tile);for(let k=0;k<6;k++)p.array[j+k]=hidden?orig[j+(k%3)]:orig[j+k]}p.needsUpdate=true;}emphasizeSelection();refreshDSUHighlight();syncGammaContext();stats()}
function stats(){const count=overviewLines.reduce((n,l)=>n+l.userData.ids.length,0)+[...detail.values()].reduce((n,d)=>n+d.lines.reduce((v,l)=>v+l.userData.ids.length,0),0);$('renderInfo').textContent=`${num(count)} segments · ${detail.size} detail chunks`;}
function operatorVisible(id){return operatorFilter==='all'||!!surveyColors.operatorModel()?.matches(id,operatorFilter)}
function operatorBounds(){
  if(!manifest)return null;if(operatorFilter==='all')return manifest.bounds;
  const box=[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];let count=0;
  for(const w of manifest.wells)if(operatorVisible(w.id)){count++;for(let i=0;i<3;i++){box[i]=Math.min(box[i],w.bounds[i]);box[i+3]=Math.max(box[i+3],w.bounds[i+3])}}
  return count?box:null;
}
function operatorSummary(){
  const model=surveyColors.operatorModel();if(!model||!manifest)return;
  const group=model.groups.find(g=>g.key===operatorFilter),wells=group?.wellCount??new Set(manifest.wells.map(w=>`${w.permit}|${w.api.slice(0,10)}`)).size,branches=group?.branchCount??manifest.wells.length;
  $('operatorFilterSummary').textContent=`${num(wells)} well${wells===1?'':'s'} · ${num(branches)} branch${branches===1?'':'es'}${group?' · '+group.label:' · all operators'}`;
  $('operatorFit').disabled=branches===0;
  document.querySelectorAll('#operatorLegend button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.operator===operatorFilter)));
}
function setOperatorFilter(key,{rebuildGeometry=true}={}){
  const model=surveyColors.operatorModel();if(key!=='all'&&!model?.groups.some(g=>g.key===key))return;
  operatorFilter=key;$('operatorFilter').value=key;
  if(selected&&!operatorVisible(selected.id))clearSelection();
  if(overview&&rebuildGeometry)rebuild();const visible=operatorFilter==='all'?null:manifest.wells.filter(w=>operatorVisible(w.id));production.setBranchScope(visible?.map(w=>w.id)??null);gamma.setPermitFilter(visible?.map(w=>w.permit)??null);dsuWells.refresh();surveyColors.refresh();operatorSummary();renderWellSearch();
}
function setupOperators(){
  dsuWells.refresh();
  const model=surveyColors.operatorModel(),all=document.createElement('option');all.value='all';all.textContent='All operators';$('operatorFilter').replaceChildren(all);$('operatorLegend').replaceChildren();
  if(!model)return;
  for(const g of model.groups){
    const option=document.createElement('option');option.value=g.key;option.textContent=`${g.label} (${num(g.wellCount)} well${g.wellCount===1?'':'s'})`;$('operatorFilter').append(option);
    if(!g.branchCount)continue;
    const button=document.createElement('button');button.type='button';button.dataset.operator=g.key;button.setAttribute('aria-label',`Show ${g.label}`);button.setAttribute('aria-pressed','false');
    const swatch=document.createElement('i');swatch.style.background=g.color;const name=document.createElement('span');name.textContent=g.label;const count=document.createElement('small');count.textContent=num(g.wellCount);button.append(swatch,name,count);button.onclick=()=>{setOperatorFilter(g.key);surveyColors.setMode('operator')};$('operatorLegend').append(button);
  }
  operatorSummary();
}
$('operatorFilter').onchange=e=>setOperatorFilter(e.target.value);$('operatorAll').onclick=()=>setOperatorFilter('all');$('operatorFit').onclick=()=>{const box=operatorBounds();if(box)fit(box)};
function fit(bounds=manifest.bounds,view=viewOrientation,pivot=null){navigation.reset();if(planActive){fitPlan(bounds,pivot);return}const damping=controls.enableDamping;controls.enableDamping=false;controls.update();const b=bounds,s=root.scale.y,c=pivot?.clone()||new THREE.Vector3((b[0]+b[3])/2,(b[1]+b[4])/2*s,(b[2]+b[5])/2);const radius=framingRadius(b,c,s);const verticalFov=THREE.MathUtils.degToRad(camera.fov),horizontalFov=2*Math.atan(Math.tan(verticalFov/2)*camera.aspect);const d=radius/Math.sin(Math.min(verticalFov,horizontalFov)/2)*1.15;controls.target.copy(c);const direction=view==='top'?new THREE.Vector3(0,1,.00001):view==='side'?new THREE.Vector3(0,0,1):new THREE.Vector3(.65,.42,.75).normalize();camera.position.copy(c).addScaledVector(direction,d);camera.near=Math.max(.5,radius/100000);camera.far=Math.max(10000000,d*10);camera.updateProjectionMatrix();controls.update();controls.enableDamping=damping;lastUpdate=0;}
function canvasAspect(){const el=$('canvasHost');return Math.max(.1,el.clientWidth/Math.max(1,el.clientHeight))}
function planViewInsets(){
  const canvas=renderer.domElement.getBoundingClientRect();
  if(!matchMedia('(max-width:560px)').matches)return{top:0,bottom:0,height:Math.max(1,canvas.height)};
  const visible=el=>el&&!el.hidden&&el.getClientRects().length;
  const above=[document.querySelector('#viewport .view-top'),$('selectedToolbar'),$('message').textContent.trim()?$('message'):null].filter(visible);
  const below=[document.querySelector('.mobile-bottom-controls'),document.querySelector('#viewport .view-bottom')].filter(visible);
  const top=Math.max(0,...above.map(el=>el.getBoundingClientRect().bottom-canvas.top))+12;
  const bottom=Math.max(0,...below.map(el=>canvas.bottom-el.getBoundingClientRect().top))+12;
  return{top,bottom,height:Math.max(1,canvas.height)};
}
function fitPlan(b,pivot=null){
  const damping=controls.enableDamping;controls.enableDamping=false;controls.update();
  const cx=pivot?.x??(b[0]+b[3])/2,cz=pivot?.z??(b[2]+b[5])/2,width=Math.max(200,2*Math.max(Math.abs(b[0]-cx),Math.abs(b[3]-cx))),height=Math.max(200,2*Math.max(Math.abs(b[2]-cz),Math.abs(b[5]-cz)));
  const insets=planViewInsets(),available=Math.max(.1,1-(insets.top+insets.bottom)/insets.height);
  const half=Math.max(height/(2*available),width/(2*canvasAspect()))*1.15,shift=(insets.top-insets.bottom)/insets.height*half;
  planCamera.left=-half*canvasAspect();planCamera.right=half*canvasAspect();planCamera.top=half+shift;planCamera.bottom=-half+shift;planCamera.zoom=1;
  const altitude=Math.max(width,height,10000)*2+100000;planCamera.far=Math.max(10000000,altitude+Math.abs(manifest.bounds[1])*8+100000);
  controls.target.set(cx,0,cz);planCamera.position.set(cx,altitude,cz+.001);planCamera.updateProjectionMatrix();controls.update();controls.enableDamping=damping;lastUpdate=0;
}
function planFootprint(){const c=controls.target,z=planCamera.zoom;return[c.x+planCamera.left/z,manifest.bounds[1],c.z-planCamera.top/z,c.x+planCamera.right/z,0,c.z-planCamera.bottom/z]}
function setPlanMode(enabled,bounds){
  orientView(enabled?'plan':'perspective');
  if(manifest&&bounds)fit(bounds);
}
function orientView(view){
  if(!manifest)return;
  const enabled=view==='plan',nextCamera=enabled?planCamera:perspectiveCamera;
  switchCameraOrientation(controls,nextCamera,view,canvasAspect());
  camera=nextCamera;planActive=enabled;viewOrientation=view;
  controls.enableRotate=!enabled;controls.screenSpacePanning=true;
  controls.mouseButtons.LEFT=enabled?THREE.MOUSE.PAN:THREE.MOUSE.ROTATE;
  controls.touches.ONE=enabled?THREE.TOUCH.PAN:THREE.TOUCH.ROTATE;
  $('top').setAttribute('aria-pressed',String(enabled));$('perspective').setAttribute('aria-pressed',String(view==='perspective'));$('side').setAttribute('aria-pressed',String(view==='side'));
  $('mode').textContent=enabled?'PLAN VIEW · NORTH UP':view==='side'?'SIDE VIEW':'3D EXPLORER';
  $('navigationHelp').textContent=enabled?'Drag to pan · Scroll to zoom · North up':'Drag to orbit · Right-drag to pan · Scroll to move closer · Double-click to center';
  $('axisReadout').innerHTML=enabled?'N ↑<span>Orthographic plan view</span>':'Reference: TVD 0<span>Plan view: north up</span>';
  lastUpdate=0;
}
function fitVisible(){
  if(!manifest)return;
  const bounds=[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];
  const include=b=>{if(b)for(let k=0;k<3;k++){bounds[k]=Math.min(bounds[k],b[k]);bounds[k+3]=Math.max(bounds[k+3],b[k+3])}};
  for(const line of [...overviewLines,...[...detail.values()].flatMap(d=>d.lines)]){
    if(!line.visible)continue;const p=line.geometry.attributes.position.array;
    for(let j=0;j<p.length;j+=6){if(p[j]===p[j+3]&&p[j+1]===p[j+4]&&p[j+2]===p[j+5])continue;
      for(let k=0;k<3;k++){bounds[k]=Math.min(bounds[k],p[j+k],p[j+k+3]);bounds[k+3]=Math.max(bounds[k+3],p[j+k],p[j+k+3])}}
  }
  include(dsu.visibleBounds());include(footage.visibleBounds());if(gamma.enabled())include(gamma.limits());
  if(bounds.every(Number.isFinite))fit(bounds,viewOrientation);else say('No visible paths or areas. Turn on a layer or use North Dakota.');
}
function visibleSpan(){return planActive?(planCamera.top-planCamera.bottom)/planCamera.zoom:camera.position.distanceTo(controls.target)}
function syncReference(){reference.setVisible($('showState').checked);if(grid)grid.visible=!(reference.visible&&reference.bounds)}
async function viewState(){await referenceReady;if(!manifest)return;if(reference.bounds){$('showState').checked=true;syncReference();setPlanMode(true,reference.bounds)}else setPlanMode(true,manifest.bounds)}
async function load(getter){const version=++epoch;wellShapes=null;shapeColorsEnabled=true;showUTurnLaterals=true;$('trajectoryShapes').checked=true;$('trajectoryShapes').disabled=true;$('showUTurnLaterals').checked=true;$('uturnLegend').hidden=true;operatorFilter='all';footage.setDataset(null);dsu.setDataset(null);dsuWells.setDataset(null);surveyColors.reset();gamma.setPermitFilter(null);gamma.reset();production.reset();production.setSurveyColoring(false);source=getter;selected=null;wellNames=new Map();wellSearch=null;wellNamesLoading=false;$('search').disabled=true;$('mobileWellSearch').disabled=true;$('wellNameStatus').textContent='Loading survey data…';$('results').replaceChildren();clear();manifest=null;overview=null;say('Loading survey paths…');try{const manifestBytes=await read('manifest.json');const m=JSON.parse(new TextDecoder().decode(manifestBytes));if(version!==epoch)return;if(m.version!==1||!m.wells?.length)throw Error('Choose a prepared dataset folder containing manifest.json and binary chunks.');manifest=m;footage.setDataset(m,manifestBytes);dsuWells.setDataset(m,manifestBytes);dsu.setDataset(m);overview=new Float32Array(await read('overview.bin'));if(version!==epoch)return;if(overview.length%8)throw Error('Invalid overview data');await loadWellShapes(m,manifestBytes,version);if(version!==epoch)return;await production.load(async(name,json=false)=>{const buffer=await getter(name);return json?JSON.parse(new TextDecoder().decode(buffer)):buffer},m);if(version!==epoch)return;dsuWells.refresh();await surveyColors.load(async(name,json=false)=>{const buffer=await getter(name);return json?JSON.parse(new TextDecoder().decode(buffer)):buffer},m);if(version!==epoch)return;setupOperators();mobileControls.sync();startWellSearch(m,manifestBytes,getter,version);$('source').textContent=m.source+(m.sourceSnapshot?.date?' · '+m.sourceSnapshot.date:'');$('wellCount').textContent=num(m.wells.length);$('stationCount').textContent=num(m.stations);$('quality').textContent=`${m.sourceCRS} · ${num(m.skipped)} skipped records · ${num(m.duplicateMD)} duplicate measured depths removed. Original TVD convention: ${m.tvdSign}.`;overviewCounts=new Array(6).fill(0);for(let i=6;i<overview.length;i+=8)overviewCounts[overview[i]]++;visibleSections=new Set([0,1,2,3,4,5]);$('legend').replaceChildren();m.labels.forEach((label,i)=>{const row=document.createElement('label');row.className='legend-row';row.innerHTML=`<input type="checkbox" checked><i class="swatch" style="background:${palette[i]}"></i><span>${label}</span>`;row.querySelector('input').onchange=e=>{e.target.checked?visibleSections.add(i):visibleSections.delete(i);rebuild()};$('legend').append(row)});$('search').value='';$('results').replaceChildren();clearSelection();showClassifier();$('fitState').disabled=true;$('referenceStatus').textContent='Loading state outline…';referenceReady=reference.setDataset(m).then(()=>{if(epoch!==version)return;$('fitState').disabled=false;$('referenceStatus').textContent='Census 2026 · Williston, Dickinson, Minot, Bismarck';syncReference()}).catch(e=>{if(epoch===version)$('referenceStatus').textContent=e.message});if(grid)dispose(grid);const extent=Math.max(m.bounds[3]-m.bounds[0],m.bounds[5]-m.bounds[2],10000)*1.4;grid=new THREE.GridHelper(extent,20,'#294759','#172d3d');grid.position.set((m.bounds[0]+m.bounds[3])/2,0,(m.bounds[2]+m.bounds[5])/2);scene.add(grid);syncReference();rebuild();fit();say('');lastUpdate=0;gamma.load(m);const requestedColor=new URLSearchParams(location.search).get('color');if(requestedColor)surveyColors.setMode(requestedColor);const requestedDSU=new URLSearchParams(location.search).get('dsu');if(requestedDSU)await dsu.openUnit(requestedDSU);const requestedArea=new URLSearchParams(location.search).get('inventory');if(requestedArea&&!requestedDSU)setSelectionTarget(requestedArea);sidebar?.sync();}catch(e){say('Could not open dataset: '+e.message)}}
async function updateDetail(){if(!manifest||busy)return;busy=true;const version=epoch;try{const center=controls.target,distance=visibleSpan();const candidates=manifest.tiles.map(t=>{const b=t.bounds;const cx=Math.max(b[0],Math.min(center.x,b[3])),cz=Math.max(b[2],Math.min(center.z,b[5]));return {t,d:Math.hypot(cx-center.x,cz-center.z)}}).filter(v=>v.d<distance*.65).sort((a,b)=>a.d-b.d);let total=0;const wanted=new Set();if(selected){wanted.add(selected.tile);total=manifest.tiles.find(t=>t.id===selected.tile).stations}for(const {t} of candidates){if(wanted.has(t.id))continue;if(total+t.stations<=250000 && wanted.size<8){wanted.add(t.id);total+=t.stations}}
for(const [k,d] of detail)if(!wanted.has(k)){d.lines.forEach(dispose);detail.delete(k)}
for(const k of wanted){if(detail.has(k))continue;const t=manifest.tiles.find(v=>v.id===k);const data=new Float32Array(await read(t.file));if(epoch!==version)return;if(data.length!==t.stations*4)throw Error('Incomplete chunk '+t.file);detail.set(k,{data,lines:buildSegments(data,false,manifest.wells.filter(w=>w.tile===k))});emphasizeSelection();syncGammaContext();try{await surveyColors.tileReady(k)}catch(e){$('surveyColorStatus').textContent=e.message}if(epoch!==version)return;}surveyColors.releaseTiles(new Set([...detail.keys(),selected?.tile]));updateOverview();}catch(e){say('Detail loading failed: '+e.message)}finally{busy=false}}
function showClassifier(){const classifier=manifest?.classifier;const el=$('classifier');if(!classifier){el.textContent='';return}el.textContent=typeof classifier==='string'?classifier:[classifier.name,classifier.version?`v${classifier.version}`:''].filter(Boolean).join(' · ');if(classifier.drillbackMeaning)el.textContent+=`. ${classifier.drillbackMeaning}`;if(wellShapes&&shapeColorsEnabled)el.textContent+=' Display refinements v1: continuous drillback intervals and U-turn laterals; saved sections and survey metrics retained.';}
function emphasizeSelection(){for(const l of [...overviewLines,...[...detail.values()].flatMap(d=>d.lines)]){const opacity=dsuScope!==null ? .16 : (selected&&selectedData?.length ? .28 : 1);l.material.opacity=wellContext==='faint'?.16:opacity;production.syncLine(l,opacity)}}
function renderSelection(){
  if(highlight){dispose(highlight);highlight=null}
  if(!selected||!selectedData)return;
  const w=selected,d=selectedData,positions=[],colors=[],ends=[],endColors=[];
  for(let i=w.offset+1;i<w.offset+w.count;i++){
    const sec=d[i*4+3];if(!pathVisible(sec,w.id,i,w.tile)||(sec===4&&production.ready()))continue;
    positions.push(...d.subarray((i-1)*4,(i-1)*4+3),...d.subarray(i*4,i*4+3));
    const c=surveyColors.stationRGB(sec,w.tile,i,d,w.id);colors.push(...c,...c);
  }
  highlight=new THREE.Group();root.add(highlight);
  if(positions.length){const path=line(positions,colors,[]);path.material.depthTest=false;path.renderOrder=2;highlight.add(path)}
  for(const i of new Set([w.offset,w.offset+w.count-1])){
    const sec=d[i*4+3];if(!pathVisible(sec,w.id,i,w.tile))continue;const c=surveyColors.stationRGB(sec,w.tile,i,d,w.id);ends.push(...d.subarray(i*4,i*4+3));endColors.push(...c);
  }
  if(ends.length){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(ends,3));g.setAttribute('color',new THREE.Float32BufferAttribute(endColors,3));const dots=new THREE.Points(g,new THREE.PointsMaterial({vertexColors:true,size:7,sizeAttenuation:false,depthTest:false}));dots.renderOrder=3;highlight.add(dots)}
  emphasizeSelection();syncGammaContext();
}
function wellScope(w){const siblings=manifest.wells.filter(v=>v.permit===w.permit&&v.api===w.api);const bounds=[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];for(const branch of siblings)for(let axis=0;axis<3;axis++){bounds[axis]=Math.min(bounds[axis],branch.bounds[axis]);bounds[axis+3]=Math.max(bounds[axis+3],branch.bounds[axis+3])}return{bounds,count:siblings.length}}
async function zoomToSelected(){
  if(!selected)return;
  const w=selected,version=epoch,bounds=wellScope(w).bounds;
  try{
    let data=selectedData||detail.get(w.tile)?.data;
    if(!data)data=new Float32Array(await read(manifest.tiles.find(t=>t.id===w.tile).file));
    if(version!==epoch||selected!==w)return;
    const pivot=trajectoryPivot(data,w,bounds,root.scale.y);
    say('Centered on wellbore. Double-click any path to center on that point.');
    fit(bounds,viewOrientation,pivot);navigation.begin(framingRadius(bounds,pivot,root.scale.y)*.015);
  }catch(e){say('Could not center on well: '+e.message)}
}
function clearSelection(){selected=null;selectedData=null;production.selection(null);surveyColors.selection(null,null);if(highlight){dispose(highlight);highlight=null}$('selection').innerHTML='<div class="eyebrow">INSPECT A WELL</div><p>Click a path or choose a search result to see its survey details and zoom to it.</p>';$('clearSelection').hidden=true;$('selectedToolbar').hidden=true;if(selectionKind==='well')selectionKind=dsu.selection()?'dsu':footage.selection()?'township':null;emphasizeSelection();sidebar?.sync();}
async function select(w,focus=false,{keepDSUScope=false}={}){
  if(!w||!operatorVisible(w.id))return;
  if(!keepDSUScope)dsu.clearSelection();footage.clearSelection();
  $('results').replaceChildren();
  selectionKind='well';setSelectionTarget('well');
  selected=w;selectedData=null;gamma.selected(w);renderSelection();emphasizeSelection();const version=epoch;
  $('selection').replaceChildren();const tag=document.createElement('div');tag.className='eyebrow';tag.textContent='SELECTED WELL';const title=document.createElement('h3');title.id='selectedWellTitle';const info=document.createElement('p');info.id='selectedWellIdentity';
  const scope=wellScope(w),zoom=document.createElement('button');zoom.id='zoomWell';zoom.className='primary zoom-well';zoom.textContent='Zoom to well';zoom.onclick=zoomToSelected;zoom.title=`Center navigation on this wellbore and fit all ${scope.count} survey branch${scope.count===1?'':'es'}.`;$('viewZoomWell').title=zoom.title;
  const dl=document.createElement('dl');for(const [label,value] of [['Stations',num(w.count)],['Max TVD',num(w.maxTVD)+' ft'],['Max MD',num(w.maxMD)+' ft']]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;dl.append(dt,dd)}
  $('selection').append(tag,title,info,zoom);if(scope.count>1){const scopeNote=document.createElement('p');scopeNote.className='caption';scopeNote.textContent=`Zoom includes all ${num(scope.count)} branches of this well.`;$('selection').append(scopeNote)}$('selection').append(dl);
  const operators=surveyColors.operatorModel();if(operators){const identity=document.createElement('div');identity.className='operator-identity';const raw=document.createElement('strong');raw.textContent=operators.nameForBranch(w.id)||'Operator unavailable';const group=document.createElement('span');group.textContent='Display group: '+(operators.forBranch(w.id)?.label||'Unknown');identity.append(raw,group);$('selection').append(identity)}
  if(Array.isArray(w.drillbackIntervals)){
    const note=document.createElement('p');note.className='classification-note';note.textContent=w.drillbackIntervals.length?`${num(w.drillbackIntervals.length)} drillback candidate interval${w.drillbackIntervals.length===1?'':'s'}.`:'No drillback candidate intervals detected.';$('selection').append(note);
    const reasons=[...new Set(w.drillbackIntervals.map(v=>v.reason).filter(Boolean))];if(reasons.length){const reason=document.createElement('p');reason.className='caption';reason.textContent=reasons.join(' · ');$('selection').append(reason)}
    if(w.drillbackIntervals.length){const caveat=document.createElement('p');caveat.className='caption';caveat.textContent='Geometry-based candidates; these do not confirm redrilling.';$('selection').append(caveat)}
  }
  const shape=wellShapes?.describe(w.id);
  if(shape){
    const note=document.createElement('p');note.className='classification-note';
    const parts=[];if(shape.drillbackRanges.length)parts.push('Continuous drillback coloring available');if(shape.uturnRanges.length)parts.push('U-turn lateral · cyan in Well section view');
    note.textContent=parts.join(' · ');$('selection').append(note);
    if(shape.uturnRanges.length){const caveat=document.createElement('p');caveat.className='caption';caveat.textContent='U-turn identifies a supported reversal in survey geometry. It does not establish completion or abandonment status.';$('selection').append(caveat)}
  }
  $('clearSelection').hidden=false;$('selectedToolbar').hidden=false;renderWellIdentity();
  const productionInfo=document.createElement('div');productionInfo.id='wellProduction';$('selection').append(productionInfo);production.selection(w);const metricInfo=document.createElement('div');metricInfo.id='wellSurveyMetric';$('selection').append(metricInfo);
  try{let d=detail.get(w.tile)?.data;if(!d)d=new Float32Array(await read(manifest.tiles.find(t=>t.id===w.tile).file));if(epoch!==version||selected!==w)return;selectedData=d;try{await surveyColors.ensureTile(w.tile)}catch(e){$('surveyColorStatus').textContent=e.message}if(epoch!==version||selected!==w)return;surveyColors.selection(w,d);renderSelection();if(focus)await zoomToSelected();lastUpdate=0;}catch(e){say('Could not inspect well: '+e.message)}
}
function pickWell(e){
  if(!manifest)return null;
  const rect=renderer.domElement.getBoundingClientRect();
  const gammaHit=gamma.intersection(e,camera,rect);if(gammaHit){const well=manifest.wells.find(w=>w.permit===gammaHit.entry.permit&&w.branch===gammaHit.branch);if(well&&operatorVisible(well.id))return{well,point:gammaHit.point};}
  if(wellContext==='hidden'||!gamma.contextVisible())return null;
  const objects=[...overviewLines,...[...detail.values()].flatMap(d=>d.lines)];
  const hit=pickScreenSegments(objects,camera,[e.clientX-rect.left,e.clientY-rect.top],rect.width,rect.height,production.pickPixels(),(object,id)=>object.userData.section===4?production.pickPixels(manifest.wells[id]):5);
  return hit?{well:manifest.wells[hit.id],point:hit.point}:null;
}
renderer.domElement.addEventListener('pointermove',e=>gamma.hover(e,camera,renderer.domElement.getBoundingClientRect()));renderer.domElement.addEventListener('pointerleave',()=>{$('gammaHover').hidden=true});
let down;renderer.domElement.addEventListener('pointerdown',e=>down=[e.clientX,e.clientY]);
renderer.domElement.addEventListener('pointerup',e=>{if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>4||e.button!==0)return;if(selectionTarget==='dsu'){dsu.pick(e,camera,renderer.domElement.getBoundingClientRect());return}if(selectionTarget==='township'){footage.pick(e,camera,renderer.domElement.getBoundingClientRect());return}const hit=pickWell(e);if(hit)select(hit.well)});
renderer.domElement.addEventListener('dblclick',e=>{
  if(e.button!==0||selectionTarget!=='well')return;const hit=pickWell(e);if(!hit)return;
  select(hit.well);const point=hit.point.clone();if(planActive)point.y=0;
  navigation.centerHere(point);lastUpdate=0;
  say('Navigation centered here. Drag to explore around this point.');
});
$('search').addEventListener('input',renderWellSearch);
$('mobileWellSearch').onclick=()=>{$('wellSearchPanel').scrollIntoView({block:'start'});$('search').focus({preventScroll:true})};
$('fit').onclick=fitVisible;$('top').onclick=()=>orientView('plan');$('fitState').onclick=viewState;$('showState').onchange=syncReference;$('perspective').onclick=()=>orientView('perspective');$('side').onclick=()=>orientView('side');$('scale').oninput=()=>{const previous=root.scale.y;root.scale.y=+$('scale').value;navigation.rescaleDepth(previous,root.scale.y);$('scaleValue').textContent=$('scale').value+'×';};$('viewZoomWell').onclick=zoomToSelected;$('clearSelection').onclick=clearSelection;$('allSections').onclick=()=>{visibleSections=new Set([0,1,2,3,4,5]);showUTurnLaterals=true;$('showUTurnLaterals').checked=true;document.querySelectorAll('#legend input').forEach(c=>c.checked=true);if(overview)rebuild()};
async function sample(){await load(async name=>{const r=await fetch('./data/sample/'+name);if(!r.ok)throw Error('Missing '+name);return r.arrayBuffer()})}$('sample').onclick=sample;
$('folder').onchange=e=>{const files=new Map([...e.target.files].map(f=>[f.name,f]));if(!files.has('manifest.json')){say('Choose the converted dataset folder containing manifest.json.');return}load(async name=>{const f=files.get(name);if(!f)throw Error('Missing '+name);return f.arrayBuffer()});e.target.value=''};
new ResizeObserver(()=>{const el=$('canvasHost');renderer.setSize(el.clientWidth,el.clientHeight);perspectiveCamera.aspect=canvasAspect();perspectiveCamera.updateProjectionMatrix();const half=(planCamera.top-planCamera.bottom)/2;planCamera.left=-half*canvasAspect();planCamera.right=half*canvasAspect();planCamera.updateProjectionMatrix()}).observe($('canvasHost'));
function animate(t){requestAnimationFrame(animate);controls.update();navigation.update();reference.updateLabels(camera);production.update(t,camera,renderer.domElement.clientWidth,renderer.domElement.clientHeight);showcase?.beforeRender(t);renderer.render(scene,showcase?.camera?.()||camera);showcase?.afterRender(t);if(t-lastUpdate>700){lastUpdate=t;updateDetail()}}requestAnimationFrame(animate);if(new URLSearchParams(location.search).get('dataset')!=='sample'&&!['cluster','tour'].includes(new URLSearchParams(location.search).get('showcase'))){load(async name=>{const r=await fetch('../full-dataset/'+name);if(!r.ok)throw Error('Missing '+name);return r.arrayBuffer()})}else if(['cluster','tour'].includes(new URLSearchParams(location.search).get('showcase'))){load(async name=>{const r=await fetch('./data/showcase/'+name);if(!r.ok)throw Error('Missing '+name);return r.arrayBuffer()})}else sample();
