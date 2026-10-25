import * as THREE from 'three';
import {OrbitControls} from '/viewer/vendor/OrbitControls.js';
import {framingRadius,createWellNavigation} from '/viewer/navigation.js';
import {pickScreenSegments} from '/viewer/picking.js';

const $=id=>document.getElementById(id);
const svgNS='http://www.w3.org/2000/svg';
const roles={
  inject:{label:'Injecting',color:'#64c6f3',width:5.5},
  produce:{label:'Producing',color:'#a4d929',width:5},
  hold:{label:'Shut in / hold',color:'#d8b767',width:3.5},
  monitor:{label:'Monitoring',color:'#b8a9d8',width:3.5},
  unknown:{label:'Role unverified',color:'#8b9da9',width:2.5}
};
const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
const fmt=value=>Number(value).toLocaleString('en-US',{maximumFractionDigits:0});
const boundsOf=()=>[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];
const include=(b,p)=>{for(let k=0;k<3;k++){b[k]=Math.min(b[k],p[k]);b[k+3]=Math.max(b[k+3],p[k]);}return b;};
const validBounds=b=>Array.isArray(b)&&b.length===6&&b.every(Number.isFinite)&&b.slice(0,3).every((n,i)=>n<=b[i+3]);
let registry=null,project=null,geometry=null,stageIndex=0,selectedFile=null,loadEpoch=0;
let scene=null,renderer=null,camera=null,controls=null,navigation=null,paths=null,grid=null;
let cameraView='3d',focusScope='lateral',scaleY=1,ready=false,hasWebGL=false;
let playing=false,stageStarted=0,lastFrame=0,flowTime=0;
const stageDuration=9000,renderedWells=new Map(),pickObjects=[],ribbonMaterials=[];
const viewport=new THREE.Vector2(1,1);
const stage=()=>project?.stages?.[stageIndex]??null;
const roleKey=file=>Object.hasOwn(roles,stage()?.roles?.[file])?stage().roles[file]:'unknown';
const roleFor=file=>roles[roleKey(file)];
const sourceWell=file=>project?.wells.find(w=>String(w.fileNumber)===String(file));
const requestedProject=()=>{const query=new URL(location.href).searchParams;return query.get('project')||query.get('id')||registry?.projects[0]?.id;};

function addText(parent,tag,value,className){const node=document.createElement(tag);node.textContent=value??'';if(className)node.className=className;parent.append(node);return node;}
function listText(id,items,fallback){const host=$(id);host.replaceChildren();for(const value of items?.length?items:(fallback?[fallback]:[]))addText(host,'li',value);}
function safeURL(value){try{const url=new URL(value);return url.protocol==='https:'?url.href:null;}catch{return null;}}
function canvasMessage(value,error=false){$('canvasState').textContent=value;$('canvasState').classList.toggle('error',error);$('canvasState').hidden=!value;}
function makeSVG(tag,attrs){const node=document.createElementNS(svgNS,tag);for(const[k,v]of Object.entries(attrs))node.setAttribute(k,String(v));return node;}

// Screen-space ribbons preserve the source segment endpoints. Width identifies
// a role only; it does not represent a bore diameter, volume, or reservoir plume.
const ribbonVertex=`
attribute vec3 segmentStart;
attribute vec3 segmentEnd;
uniform vec2 viewport;
uniform float displayWidth;
uniform float cameraNear;
void main(){
  vec4 a=modelViewMatrix*vec4(segmentStart,1.0),b=modelViewMatrix*vec4(segmentEnd,1.0);
  float plane=-cameraNear*1.001;
  if((a.z>plane&&b.z>plane)||distance(a.xyz,b.xyz)<0.0001){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  if(a.z>plane)a=mix(a,b,(plane-a.z)/(b.z-a.z));
  if(b.z>plane)b=mix(b,a,(plane-b.z)/(a.z-b.z));
  vec4 ca=projectionMatrix*a,cb=projectionMatrix*b;
  vec2 delta=(cb.xy/cb.w-ca.xy/ca.w)*viewport;
  float span=length(delta);
  if(span<0.0001){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  vec2 normal=vec2(-delta.y,delta.x)/span;
  vec4 clip=mix(ca,cb,position.x);
  clip.xy+=normal*position.y*displayWidth/viewport*clip.w;
  gl_Position=clip;
}`;
const ribbonFragment=`
uniform vec3 tint;
uniform float opacity;
void main(){
  gl_FragColor=vec4(tint,opacity);
  #include <colorspace_fragment>
}`;
function makeRibbon(segments){
  const g=new THREE.InstancedBufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute([0,-1,0,1,-1,0,1,1,0,0,1,0],3));g.setIndex([0,1,2,0,2,3]);
  const endpoints=new THREE.InstancedInterleavedBuffer(new Float32Array(segments),6);
  g.setAttribute('segmentStart',new THREE.InterleavedBufferAttribute(endpoints,3,0));g.setAttribute('segmentEnd',new THREE.InterleavedBufferAttribute(endpoints,3,3));g.instanceCount=segments.length/6;
  const material=new THREE.ShaderMaterial({uniforms:{viewport:{value:viewport},displayWidth:{value:3},cameraNear:{value:1},tint:{value:new THREE.Color(roles.unknown.color)},opacity:{value:1}},vertexShader:ribbonVertex,fragmentShader:ribbonFragment,transparent:true,side:THREE.DoubleSide,depthWrite:false});
  const mesh=new THREE.Mesh(g,material);mesh.frustumCulled=false;mesh.raycast=()=>{};ribbonMaterials.push(material);return mesh;
}
function makeLines(segments,branchId){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(segments,3));const line=new THREE.LineSegments(g,new THREE.LineBasicMaterial({color:'#8295a2',transparent:true,opacity:.65}));line.userData.ids=Array(segments.length/6).fill(branchId);line.userData.sourceBranchId=branchId;line.userData.segmentCount=segments.length/6;return line;}

function initializeScene(){
  try{
    scene=new THREE.Scene();scene.background=new THREE.Color('#20262b');
    renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));
    renderer.domElement.setAttribute('aria-label','Three-dimensional surveyed project well paths. The adjacent view, zoom and well buttons provide alternate controls.');renderer.domElement.setAttribute('role','img');
    $('canvasHost').append(renderer.domElement);
    camera=new THREE.PerspectiveCamera(40,1,.1,10000000);camera.position.set(1000,1000,1000);
    controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.12;controls.screenSpacePanning=true;controls.maxDistance=10000000;controls.minDistance=2;
    navigation=createWellNavigation(controls,()=>camera);paths=new THREE.Group();scene.add(paths);
    new ResizeObserver(()=>{resize();if(ready)fitCurrent();}).observe($('canvasHost'));
    let down=null;
    renderer.domElement.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY];});
    renderer.domElement.addEventListener('pointerup',e=>{
      if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5||e.button!==0||!ready)return;
      const rect=renderer.domElement.getBoundingClientRect();
      const hit=pickScreenSegments(pickObjects,camera,[e.clientX-rect.left,e.clientY-rect.top],rect.width,rect.height,10,()=>9);
      if(hit){const well=geometry.wells.find(w=>w.branches.some(b=>b.id===hit.id));if(well)selectWell(String(well.fileNumber),false);}
    });
    renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();setPlaying(false);hasWebGL=false;ready=false;$('canvasHost').classList.add('no-webgl');canvasMessage('The 3D graphics context was interrupted. Reload to restore it. Project evidence and the plan view remain available.',true);});
    hasWebGL=true;resize();
  }catch(error){hasWebGL=false;$('canvasHost').classList.add('no-webgl');canvasMessage('This device could not start the 3D view. Project evidence, well details and the surveyed plan view remain available. Try a browser with hardware acceleration for 3D.',true);}
}
function resize(){if(!renderer)return;const host=$('canvasHost');const w=Math.max(1,host.clientWidth),h=Math.max(1,host.clientHeight);renderer.setSize(w,h);viewport.set(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();}
function animate(now){
  requestAnimationFrame(animate);
  const delta=lastFrame?Math.min((now-lastFrame)/1000,.1):0;lastFrame=now;
  if(playing){
    if(!motionPreference.matches)flowTime+=delta;
    if(now-stageStarted>=stageDuration){if(stageIndex<(project?.stages?.length??0)-1){stageIndex++;stageStarted=now;updateStage();}else setPlaying(false);}
  }
  if(!renderer||!hasWebGL)return;
  controls.update();navigation.update();for(const material of ribbonMaterials)material.uniforms.cameraNear.value=camera.near;
  updateParticles();updateLabel();renderer.render(scene,camera);
}
function clearGeometry(){
  if(paths){paths.traverse(o=>{o.geometry?.dispose();if(Array.isArray(o.material))o.material.forEach(m=>m.dispose());else o.material?.dispose();});paths.clear();}
  if(grid){scene.remove(grid);grid.geometry.dispose();grid.material.dispose();grid=null;}
  renderedWells.clear();pickObjects.length=0;ribbonMaterials.length=0;$('wellLabel').hidden=true;$('projectMap').replaceChildren();
}
function validateGeometry(data,expectedId){
  if(data?.version!==1||data.projectId!==expectedId||!Array.isArray(data.wells))throw Error('The survey file does not match this project.');
  const permitted=new Set(project.wells.map(w=>String(w.fileNumber))),seenWells=new Set(),seenBranches=new Set();
  for(const well of data.wells){
    well.fileNumber=String(well.fileNumber);
    if(!permitted.has(well.fileNumber)||seenWells.has(well.fileNumber)||!Array.isArray(well.branches))throw Error('Unexpected or duplicate well identity in survey data.');seenWells.add(well.fileNumber);
    for(const branch of well.branches){
      if(!Number.isSafeInteger(branch.id)||seenBranches.has(branch.id)||!Array.isArray(branch.points))throw Error('Invalid survey branch.');seenBranches.add(branch.id);
      for(const p of branch.points)if(!Array.isArray(p)||p.length!==4||!p.every(Number.isFinite)||!Number.isInteger(p[3])||p[3]<0||p[3]>5)throw Error('Invalid survey station.');
    }
  }
  return data;
}

function flowSegments(points,onlyLateral){
  const segments=[];let total=0;
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i];if(onlyLateral&&b[3]!==4)continue;
    const length=Math.hypot(b[0]-a[0],b[1]-a[1],b[2]-a[2]);if(!length)continue;
    segments.push({a,b,start:total,length});total+=length;
  }
  return{segments,total};
}
function buildGeometry(){
  clearGeometry();
  if(!hasWebGL){renderPlanMap();return;}
  for(const well of geometry.wells){
    const group=new THREE.Group(),fullBounds=boundsOf(),lateralBounds=boundsOf(),ribbons=[],baseLines=[],lateralLines=[],flows=[];let anchor=null;
    for(const branch of well.branches){
      const all=[],laterals=[];
      branch.points.forEach(p=>include(fullBounds,p));
      // 0 is Vertical, 4 is Lateral, 5 is Unknown. Section is the incoming
      // segment's classification, never a gap marker. Branches stay separate.
      for(let i=1;i<branch.points.length;i++){
        const a=branch.points[i-1],b=branch.points[i];all.push(...a.slice(0,3),...b.slice(0,3));
        if(b[3]===4){laterals.push(...a.slice(0,3),...b.slice(0,3));include(lateralBounds,a);include(lateralBounds,b);anchor=b.slice(0,3);}
      }
      if(all.length){const line=makeLines(all,branch.id);group.add(line);baseLines.push(line);pickObjects.push(line);}
      if(laterals.length){
        const ribbon=makeRibbon(laterals);group.add(ribbon);ribbons.push(ribbon);
        const line=makeLines(laterals,branch.id);line.material.opacity=0;group.add(line);lateralLines.push(line);pickObjects.push(line);
      }
      const full=flowSegments(branch.points,false),lateral=flowSegments(branch.points,true);
      if(full.total){
        const dotGeometry=new THREE.BufferGeometry();dotGeometry.setAttribute('position',new THREE.Float32BufferAttribute(new Float32Array(9),3));
        const material=new THREE.PointsMaterial({color:'#fff',size:5,sizeAttenuation:false,transparent:true,opacity:.9,depthTest:false});
        const dots=new THREE.Points(dotGeometry,material);dots.frustumCulled=false;dots.renderOrder=5;group.add(dots);flows.push({dots,full,lateral});
      }
    }
    if(!validBounds(fullBounds))continue;
    group.userData.fileNumber=well.fileNumber;paths.add(group);
    renderedWells.set(well.fileNumber,{well,group,fullBounds,lateralBounds:validBounds(lateralBounds)?lateralBounds:null,ribbons,baseLines,lateralLines,flows,anchor:anchor??well.branches.find(b=>b.points.length)?.points.at(-1)?.slice(0,3)});
  }
  paths.scale.y=scaleY;buildGrid();applyAppearance();renderPlanMap();
}
function displayedBounds(file=null){
  const result=boundsOf();
  for(const[id,item]of renderedWells){if(file&&id!==file)continue;const b=focusScope==='lateral'?(item.lateralBounds??item.fullBounds):item.fullBounds;for(let k=0;k<3;k++){result[k]=Math.min(result[k],b[k]);result[k+3]=Math.max(result[k+3],b[k+3]);}}
  return validBounds(result)?result:null;
}
function buildGrid(){
  if(!scene)return;if(grid){scene.remove(grid);grid.geometry.dispose();grid.material.dispose();grid=null;}
  const b=displayedBounds();if(!b)return;
  const size=Math.max(b[3]-b[0],b[5]-b[2],500)*1.22;
  grid=new THREE.GridHelper(size,10,'#40535f','#34424b');grid.material.transparent=true;grid.material.opacity=.35;grid.material.depthWrite=false;
  grid.position.set((b[0]+b[3])/2,b[1]*scaleY-Math.max(size*.012,25),(b[2]+b[5])/2);scene.add(grid);
}
function fitCurrent(){
  if(!hasWebGL||!renderedWells.size)return;
  const b=displayedBounds(selectedFile)||displayedBounds();if(!b)return;
  navigation.reset();const damping=controls.enableDamping;controls.enableDamping=false;controls.update();
  const center=new THREE.Vector3((b[0]+b[3])/2,(b[1]+b[4])/2*scaleY,(b[2]+b[5])/2);
  const radius=framingRadius(b,center,scaleY),vFov=THREE.MathUtils.degToRad(camera.fov),hFov=2*Math.atan(Math.tan(vFov/2)*camera.aspect),distance=radius/Math.sin(Math.min(vFov,hFov)/2)*1.15;
  camera.up.set(0,1,0);const direction=new THREE.Vector3(.8,.58,.65).normalize();
  if(cameraView==='plan'){direction.set(0,1,.000001);camera.up.set(0,0,-1);}else if(cameraView==='side')direction.set(1,.025,0);
  controls.enableRotate=cameraView!=='plan';controls.target.copy(center);camera.position.copy(center).addScaledVector(direction,distance);
  camera.near=Math.max(.1,radius/100000);camera.far=Math.max(1000000,distance*20);camera.updateProjectionMatrix();controls.update();controls.enableDamping=damping;navigation.begin(100);
}
function applyAppearance(){
  for(const[file,item]of renderedWells){
    const role=roleFor(file),emphasis=!selectedFile||file===selectedFile?1:.27;
    for(const mesh of item.ribbons){mesh.material.uniforms.tint.value.set(role.color);mesh.material.uniforms.displayWidth.value=role.width+(file===selectedFile?1:0);mesh.material.uniforms.opacity.value=emphasis;}
    for(const line of item.baseLines){line.visible=focusScope==='whole'||!item.lateralBounds;line.material.opacity=.65*emphasis;line.material.color.set(item.lateralBounds?'#8295a2':role.color);}
    for(const line of item.lateralLines)line.visible=focusScope==='lateral';
    for(const flow of item.flows){flow.dots.material.opacity=.95*emphasis;flow.dots.material.color.set(role.color);}
  }
}
function updateParticles(){
  for(const[file,item]of renderedWells){
    const role=roleKey(file),active=playing&&!motionPreference.matches&&(role==='inject'||role==='produce');
    for(const flow of item.flows){
      const route=focusScope==='lateral'?flow.lateral:flow.full;flow.dots.visible=active&&route.total>0;if(!flow.dots.visible)continue;
      const array=flow.dots.geometry.attributes.position.array;
      for(let i=0;i<3;i++){
        let fraction=(flowTime/6+i/3)%1;if(role==='produce')fraction=1-fraction;
        const distance=fraction*route.total,segment=route.segments.find(s=>distance<=s.start+s.length)??route.segments.at(-1),t=Math.max(0,Math.min(1,(distance-segment.start)/segment.length));
        for(let k=0;k<3;k++)array[i*3+k]=segment.a[k]+(segment.b[k]-segment.a[k])*t;
      }
      flow.dots.geometry.attributes.position.needsUpdate=true;
    }
  }
}
function updateLabel(){
  const item=renderedWells.get(selectedFile);if(!item?.anchor||!ready){$('wellLabel').hidden=true;return;}
  const p=new THREE.Vector3(...item.anchor);p.y*=scaleY;p.project(camera);
  if(p.z<-1||p.z>1||Math.abs(p.x)>.95||Math.abs(p.y)>.95){$('wellLabel').hidden=true;return;}
  $('wellLabel').style.left=Math.max(85,Math.min(viewport.x-85,(p.x+1)*viewport.x/2))+'px';$('wellLabel').style.top=Math.max(65,(1-p.y)*viewport.y/2-12)+'px';$('wellLabel').hidden=false;
}

function renderPlanMap(){
  const host=$('projectMap');host.replaceChildren();if(!geometry)return;
  const points=geometry.wells.flatMap(w=>w.branches.flatMap(b=>b.points));if(!points.length){$('mapInset').hidden=true;return;}$('mapInset').hidden=false;
  let minX=Infinity,maxX=-Infinity,minZ=Infinity,maxZ=-Infinity;for(const p of points){minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);minZ=Math.min(minZ,p[2]);maxZ=Math.max(maxZ,p[2]);}
  const width=Math.max(50,maxX-minX),height=Math.max(50,maxZ-minZ),scale=Math.min(158/width,104/height),ox=90-(minX+maxX)/2*scale,oy=62-(minZ+maxZ)/2*scale;
  for(let n=20;n<180;n+=35)host.append(makeSVG('path',{d:`M${n} 0V124`,stroke:'#354650','stroke-width':.6}));
  for(let n=10;n<124;n+=30)host.append(makeSVG('path',{d:`M0 ${n}H180`,stroke:'#354650','stroke-width':.6}));
  for(const well of geometry.wells){
    for(const branch of well.branches){
      if(branch.points.length<2)continue;
      const d=branch.points.map((p,i)=>`${i?'L':'M'}${(p[0]*scale+ox).toFixed(3)} ${(p[2]*scale+oy).toFixed(3)}`).join(' ');
      const path=makeSVG('path',{d,fill:'none',stroke:roleFor(well.fileNumber).color,'stroke-width':selectedFile===well.fileNumber?2.7:1.7,opacity:(selectedFile&&selectedFile!==well.fileNumber)? .3:1});
      host.append(path);
    }
  }
  host.setAttribute('aria-label',`${project.title}: north-up plan of surveyed well paths; branches retained.`);
  $('mapScale').textContent=`${fmt(width)} ft E–W · ${fmt(height)} ft N–S`;
}

function renderProjectInformation(){
  document.title=`${project.title} | EOR Projects · Bakken Subsurface Analytics`;
  updatePublishedProjectMetadata(project);
  $('projectTitle').textContent=project.title;$('projectMeta').textContent=[project.operator,project.location].filter(Boolean).join(' · ');
  $('projectSummary').textContent=project.summary??'';$('projectStatus').textContent=project.status??'Public project record';$('statusDetail').textContent=project.statusDetail??'';
  $('reviewedAt').textContent=[project.statusDate?`Record date ${project.statusDate}`:'',registry.reviewedAt?`Sources reviewed ${registry.reviewedAt}`:''].filter(Boolean).join(' · ');
  listText('findingsList',project.findings,'No detailed findings have been established in the sources reviewed.');listText('watchList',project.watch,'Current operating data have not been verified.');listText('limitationsList',project.limitations);
  const host=$('sourceList');host.replaceChildren();
  for(const source of project.sources??[]){const url=safeURL(source.url);if(!url)continue;const li=document.createElement('li'),link=addText(li,'a',source.label||'Project source');link.href=url;link.target='_blank';link.rel='noopener noreferrer';if(source.date)addText(li,'small',source.date);if(source.evidence)addText(li,'p',source.evidence);if(source.qualification)addText(li,'p',source.qualification,'qualification');host.append(li);}
}
function renderWellList(){
  const host=$('wellList');host.replaceChildren();if(!project)return;
  for(const metadata of project.wells){
    const file=String(metadata.fileNumber),well=geometry?.wells.find(w=>w.fileNumber===file),available=well?.branches.some(b=>b.points.length>1),role=roleFor(file);
    const button=document.createElement('button');button.type='button';button.className='well-row';button.dataset.file=file;button.setAttribute('aria-pressed',String(selectedFile===file));
    button.setAttribute('aria-label',`${metadata.name}, file ${file}, ${geometry?(available?role.label:'survey unavailable'):'survey loading'}`);
    const swatch=document.createElement('i');swatch.className='well-role-swatch';swatch.style.background=role.color;swatch.setAttribute('aria-hidden','true');button.append(swatch);
    const identity=document.createElement('span');addText(identity,'strong',metadata.shortName||metadata.name);addText(identity,'small',`File ${file}${metadata.formation?' · '+metadata.formation:''}`);button.append(identity);
    addText(button,'span',geometry?(available?role.label:'No survey'):role.label,'role-text');button.onclick=()=>selectWell(file,true);host.append(button);
  }
}
function selectWell(file,focus=true){
  if(!project)return;selectedFile=file;
  const data=geometry?.wells.find(w=>w.fileNumber===file),metadata=sourceWell(file),role=roleFor(file),detail=$('wellDetails');detail.replaceChildren();detail.hidden=!file;$('clearWell').hidden=!file;
  if(metadata){
    addText(detail,'strong',metadata.name);addText(detail,'p',`NDIC file ${file}${data?.api?' · API '+data.api:''}`,'identity');
    if(data?.operator)addText(detail,'p',`Survey snapshot operator: ${data.operator}`,'identity');
    if(data?.branches.length){
      const maxTVD=Math.max(0,...data.branches.map(b=>Number(b.maxTVD)||0)),maxMD=Math.max(0,...data.branches.map(b=>Number(b.maxMD)||0));
      addText(detail,'p',`${data.branches.length} survey branches · Max TVD ${fmt(maxTVD)} ft · Max MD ${fmt(maxMD)} ft`,'identity');
    }else addText(detail,'p','No matching surveyed path is available. No substitute geometry has been drawn.','identity');
    addText(detail,'p',`Illustrative stage role: ${role.label}.`);if(metadata.roleNote)addText(detail,'p',metadata.roleNote,'identity');
    $('wellLabel').textContent=`${metadata.shortName||metadata.name} · ${file}`;
  }
  renderWellList();applyAppearance();renderPlanMap();updateMechanism();if(focus)fitCurrent();
}
function updateMechanism(){
  const current=stage();let flow=selectedFile?roleKey(selectedFile):null;
  if(!flow)flow=Object.values(current?.roles??{}).includes('inject')?'inject':Object.values(current?.roles??{}).includes('produce')?'produce':'unknown';
  $('mechanismPanel').dataset.flow=flow;
  const words={inject:['Injection creates an opportunity for contact','Fluid enters the well'],produce:['Drawdown returns fluids to the well','Fluids return through the well'],hold:['A pause in the illustrated cycle','No flow is illustrated'],monitor:['Observe the reservoir response','Monitor; no flow is implied'],unknown:['Operating role is unverified','No flow assignment']};
  const selected=sourceWell(selectedFile);
  $('mechanismTitle').textContent=`${selected?'Selected well '+(selected.shortName||selected.name)+': ':''}${words[flow][0]}`;$('mechanismDirection').textContent=words[flow][1];$('mechanismDirection').setAttribute('fill',roles[flow].color);
  listText('reservoirEffects',current?.reservoirEffects,['The surveyed paths locate the wells. Reservoir contact and recovery cannot be inferred from well geometry alone.']);
  $('mechanismSVGTitle').textContent=words[flow][0];
}
function updateStage(){
  const current=stage(),stages=project?.stages??[];
  $('stageCount').textContent=current?`${stageIndex+1} / ${stages.length}`:'Survey';
  $('sequenceTitle').textContent=current?current.label:'Survey view · sequence unavailable';
  $('stageDescription').textContent=current?current.description:'The project wells are shown in their surveyed positions. An operating sequence has not been established from the available sources.';
  $('stageBasis').textContent=current?(current.basis||'Illustrative method explanation; no measured dates or rates.'): 'Roles remain unassigned. This display does not imply that the wells are currently injecting or producing.';
  $('previousStage').disabled=!current||stageIndex===0;$('nextStage').disabled=!current||stageIndex===stages.length-1;$('playStages').disabled=stages.length<1;
  $('canvasMode').textContent=playing?'Illustrative flow direction':'Illustrative well roles';
  const host=$('stageDots');host.replaceChildren();stages.forEach((entry,index)=>{const button=document.createElement('button');button.type='button';button.textContent=String(index+1);button.setAttribute('aria-label',`Stage ${index+1}: ${entry.label}`);if(index===stageIndex)button.setAttribute('aria-current','step');button.onclick=()=>{setPlaying(false);stageIndex=index;updateStage();};host.append(button);});
  applyAppearance();renderWellList();renderPlanMap();updateMechanism();if(selectedFile)selectWell(selectedFile,false);
  $('playStatus').textContent=playing?`Playing · stage ${stageIndex+1} of ${stages.length}`:'Step through the concept';
}
function setPlaying(value){
  playing=Boolean(value&&project?.stages?.length);stageStarted=performance.now();
  $('playStages').setAttribute('aria-pressed',String(playing));$('playStages').textContent=playing?'Ⅱ Pause':'▶ Play stages';
  $('canvasMode').textContent=playing?'Illustrative flow direction':'Illustrative well roles';
  $('playStatus').textContent=playing?`Playing · stage ${stageIndex+1} of ${project.stages.length}`:'Step through the concept';
  if(!playing)updateParticles();
}

async function loadProject(id,pushURL=false){
  const target=registry.projects.find(p=>p.id===id);
  if(!target){
    ++loadEpoch;setPlaying(false);project=null;geometry=null;ready=false;selectedFile=null;clearGeometry();
    $('projectSelect').selectedIndex=-1;$('mapInset').hidden=true;$('wellDetails').hidden=true;$('clearWell').hidden=true;
    $('projectTitle').textContent='Project not found';$('projectMeta').textContent='Choose an available project from the selector.';
    $('projectSummary').textContent='';$('statusDetail').textContent='';$('reviewedAt').textContent='';$('projectStatus').textContent='No project selected';$('geometrySummary').textContent='No survey loaded';
    for(const id of ['wellList','findingsList','watchList','limitationsList','sourceList'])$(id).replaceChildren();
    updateStage();canvasMessage('This project was not found. Choose an available project above.',true);return;
  }
  const epoch=++loadEpoch;setPlaying(false);project=target;geometry=null;stageIndex=0;selectedFile=null;ready=false;clearGeometry();$('mapInset').hidden=true;$('wellDetails').hidden=true;$('clearWell').hidden=true;$('projectSelect').value=id;
  if(pushURL){const url=new URL(location.href);url.searchParams.delete('id');url.searchParams.set('project',id);history.pushState({id},'',url);}
  renderProjectInformation();updateStage();$('geometrySummary').textContent='Reading survey snapshot…';$('geometryProvenance').textContent='Loading source metadata…';
  if(hasWebGL)canvasMessage('Loading the project’s surveyed well paths…');
  try{
    const response=await fetch(`/eor/data/${encodeURIComponent(id)}.json`);if(!response.ok)throw Error('Project survey data are unavailable.');
    const raw=await response.json();if(epoch!==loadEpoch)return;geometry=validateGeometry(raw,id);buildGeometry();
    const available=geometry.wells.filter(w=>w.branches.some(b=>b.points.length>1)).length,missing=project.wells.length-available,branches=geometry.wells.reduce((n,w)=>n+w.branches.length,0);
    $('geometrySummary').textContent=`${available} of ${project.wells.length} wells · ${branches} survey branches${missing?' · '+missing+' missing':''}`;
    $('geometryProvenance').textContent=`Survey snapshot ${geometry.source?.snapshotDate||'date unavailable'}. Exact station subsets from the regional viewer; no smoothing or surface extension. ${geometry.source?.coordinates||''}`;
    const url=safeURL(geometry.source?.sourceURL);if(url){const li=document.createElement('li'),link=addText(li,'a','North Dakota DMR · survey geometry source');link.href=url;link.target='_blank';link.rel='noopener noreferrer';$('sourceList').append(li);}
    ready=hasWebGL&&renderedWells.size>0;renderWellList();updateStage();
    if(ready){canvasMessage('');fitCurrent();}else if(hasWebGL)canvasMessage('No matching survey paths are available in this snapshot. Verified well identities and project sources remain listed beside this view.');
  }catch(error){if(epoch!==loadEpoch)return;canvasMessage(`Could not load the survey: ${error.message}`,true);$('geometrySummary').textContent='Survey geometry unavailable';$('geometryProvenance').textContent='The geometry could not be loaded. No substitute paths have been drawn.';renderWellList();}
}
function setCameraView(value){cameraView=value;for(const[id,key]of[['view3D','3d'],['viewPlan','plan'],['viewSide','side']])$(id).setAttribute('aria-pressed',String(key===value));$('viewOrientation').textContent=value==='plan'?'Plan · north up':value==='side'?'Side · looking west':'3D perspective';fitCurrent();}
function zoom(factor){if(!ready)return;const offset=camera.position.clone().sub(controls.target).multiplyScalar(factor);camera.position.copy(controls.target).add(offset);controls.update();}

$('projectSelect').onchange=e=>loadProject(e.target.value,true);
$('view3D').onclick=()=>setCameraView('3d');$('viewPlan').onclick=()=>setCameraView('plan');$('viewSide').onclick=()=>setCameraView('side');
$('fitProject').onclick=()=>{selectWell(null,false);setCameraView('3d');};$('clearWell').onclick=()=>{selectWell(null,false);fitCurrent();};
$('zoomIn').onclick=()=>zoom(.78);$('zoomOut').onclick=()=>zoom(1.28);
$('pathScope').onchange=e=>{focusScope=e.target.value;applyAppearance();buildGrid();fitCurrent();};
$('depthScale').oninput=e=>{scaleY=Number(e.target.value);$('depthValue').textContent=`${scaleY}×`;$('scaleNote').textContent=`Relative TVD · ${scaleY}× vertical scale`;if(paths)paths.scale.y=scaleY;buildGrid();fitCurrent();};
$('previousStage').onclick=()=>{setPlaying(false);stageIndex=Math.max(0,stageIndex-1);updateStage();};
$('nextStage').onclick=()=>{setPlaying(false);stageIndex=Math.min((project?.stages?.length??1)-1,stageIndex+1);updateStage();};
$('playStages').onclick=()=>{if(playing){setPlaying(false);return;}if(stageIndex===(project?.stages?.length??0)-1){stageIndex=0;updateStage();}setPlaying(true);};
document.addEventListener('visibilitychange',()=>{if(document.hidden)setPlaying(false);});
motionPreference.addEventListener('change',()=>{$('motionNote').hidden=!motionPreference.matches;if(motionPreference.matches)setPlaying(false);});
$('motionNote').hidden=!motionPreference.matches;
window.addEventListener('popstate',()=>{if(registry)loadProject(requestedProject());});

async function start(){
  initializeScene();
  requestAnimationFrame(animate);
  try{
    const response=await fetch('/eor/projects.json');if(!response.ok)throw Error('The project registry is unavailable.');
    registry=await response.json();if(![1,2].includes(registry?.version)||!Array.isArray(registry.projects)||!registry.projects.length)throw Error('No project records are available.');
    const selector=$('projectSelect');selector.replaceChildren();for(const entry of registry.projects){const option=document.createElement('option');option.value=entry.id;option.textContent=entry.title;selector.append(option);}selector.disabled=false;
    await loadProject(requestedProject());
  }catch(error){$('projectTitle').textContent='Project explorer unavailable';$('projectMeta').textContent=error.message;$('sequenceTitle').textContent='Project record unavailable';$('stageDescription').textContent='Return to the project directory or reload this page to try again.';canvasMessage(error.message,true);$('geometrySummary').textContent='No survey loaded';}
}
start();


// Public project metadata follows the validated registry selection. Query URLs
// use one shared app shell; crawlers must execute JS for project-specific tags.
function updatePublishedProjectMetadata(entry){
  const canonical=new URL('/eor/project/', 'https://bakkensubsurface.com');
  canonical.searchParams.set('project',entry.id);
  const title=`${entry.title} EOR Project | Bakken Subsurface Analytics`;
  const description=`${entry.title}: ${entry.summary} Explore surveyed well paths and illustrative operating concepts.`;
  document.title=title;
  document.querySelector('link[rel="canonical"]').href=canonical.href;
  for(const [selector,content] of [
    ['meta[name="description"]',description],['meta[property="og:title"]',title],
    ['meta[property="og:description"]',description],['meta[property="og:url"]',canonical.href],
    ['meta[name="twitter:title"]',title],['meta[name="twitter:description"]',description]
  ])document.querySelector(selector).content=content;
}
