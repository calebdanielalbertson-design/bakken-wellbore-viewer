import * as THREE from 'three';
import {createProductionModel,symbolWidth,playbackPeriods} from './production-model.js';
import {createActivityModel,validateActivitySnapshot} from './activity-model.js';
import {renderScopeHistory} from './production-history.js';

const $=id=>document.getElementById(id),fmt=n=>n.toLocaleString('en-US',{maximumFractionDigits:0});
const monthLabel=s=>new Date(s+'-01T12:00:00Z').toLocaleDateString('en-US',{month:'short',year:'numeric',timeZone:'UTC'});
const maskLookup=`
uniform sampler2D activityTexture;
uniform vec2 activitySize;
uniform float activityEnabled;
attribute float activityIndex;
varying float activityVisible;
float visibleAt(float index){
  if(activityEnabled<0.5)return 1.0;
  if(index<0.0)return 0.0;
  return texture2D(activityTexture,(vec2(mod(index,activitySize.x),floor(index/activitySize.x))+0.5)/activitySize).r;
}`;
const lookup=`${maskLookup}
uniform sampler2D oilTexture;
uniform vec2 textureSize;
uniform float productionEnabled;
uniform float wellContext;
attribute float productionIndex;
attribute vec3 surveyColor;
attribute float groupSelected;
attribute float uturnLateral;
varying float uturnTint;
varying vec3 surveyTint;
varying float groupEmphasis;
varying float quantity;
varying float wellIndex;
float oilAt(float index){
  if(index<0.0)return -1.0;
  vec2 uv=(vec2(mod(index,textureSize.x),floor(index/textureSize.x))+0.5)/textureSize;
  return texture2D(oilTexture,uv).r;
}`;
const fragment=`
uniform float activityMode;
uniform float activityEnabled;
varying float activityVisible;
uniform vec3 lime;
varying float uturnTint;
uniform vec3 missingColor;
uniform float productionEnabled;
uniform float opacity;
uniform float selectedIndex;
uniform float ribbon;
uniform float surveyColorEnabled;
uniform float wellContext;
uniform vec3 faintColor;
varying vec3 surveyTint;
varying float quantity;
varying float wellIndex;
varying float groupEmphasis;
void main(){
  if(activityVisible<0.5)discard;
  if(wellContext>1.5||(wellContext>0.5&&ribbon>0.5))discard;
  if(ribbon>0.5&&(productionEnabled<0.5||quantity<=0.0))discard;
  vec3 color=lime;
  if(productionEnabled>0.5){if(quantity<0.0)color=missingColor;else if(quantity==0.0)color=lime*0.32;}
  if(surveyColorEnabled>0.5||uturnTint>0.5)color=surveyTint;
  float alpha=opacity;
  if(activityEnabled>0.5){
    color=quantity>0.0?vec3(0.10,0.68,0.98):quantity>-1.5&&quantity<0.0?vec3(1.0,0.56,0.12):vec3(0.30,0.43,0.50);
    if(quantity<=0.0)alpha*=0.35;
  }
  if(selectedIndex!=-1.0&&abs(wellIndex-selectedIndex)<0.25)alpha=1.0;
  if(groupEmphasis>0.5)alpha=1.0;
  // Context is a display override; selection and DSU emphasis must not brighten it.
  if(wellContext>0.5){color=faintColor;alpha=0.16;}
  gl_FragColor=vec4(color,alpha);
  #include <colorspace_fragment>
}`;
const ribbonVertex=`${lookup}
attribute vec3 segmentStart;
attribute vec3 segmentEnd;
uniform vec2 viewport;
uniform float referenceWidth;
uniform float referenceQuantity;
uniform float cameraNear;
void main(){
  activityVisible=visibleAt(activityIndex);quantity=oilAt(productionIndex);wellIndex=productionIndex;surveyTint=surveyColor;groupEmphasis=groupSelected;uturnTint=uturnLateral;
  vec4 a=modelViewMatrix*vec4(segmentStart,1.0);
  vec4 b=modelViewMatrix*vec4(segmentEnd,1.0);
  float plane=-cameraNear*1.001;
  if(wellContext>0.5||productionEnabled<0.5||quantity<=0.0||(a.z>plane&&b.z>plane)||distance(a.xyz,b.xyz)<0.0001){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  // Clip before projection so close navigation cannot produce unbounded quads.
  if(a.z>plane)a=mix(a,b,(plane-a.z)/(b.z-a.z));
  if(b.z>plane)b=mix(b,a,(plane-b.z)/(a.z-b.z));
  vec4 ca=projectionMatrix*a,cb=projectionMatrix*b;
  vec2 delta=(cb.xy/cb.w-ca.xy/ca.w)*viewport;
  float span=length(delta);
  if(span<0.0001){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}
  vec2 normal=vec2(-delta.y,delta.x)/span;
  vec4 clip=mix(ca,cb,position.x);
  float width=referenceWidth*sqrt(quantity/referenceQuantity);
  clip.xy+=normal*position.y*width/viewport*clip.w;
  gl_Position=clip;
}`;

export function createProductionController(){
  const params=new URLSearchParams(globalThis.location?.search||'');
  const initialEnabled=['1','on','true'].includes((params.get('production')||'').toLowerCase())||(!params.has('production')&&params.has('showcase'));
  let mode=params.get('timeline')==='activity'?'activity':'oil';
  let requestedEnabled=initialEnabled||mode==='activity',oilModel=null,activityModel=null,includeUnknown=false,activityError='',surveyWells=[];
  let activityTexture=new THREE.DataTexture(new Float32Array([1]),1,1,THREE.RedFormat,THREE.FloatType);activityTexture.needsUpdate=true;
  let model=null,month=0,enabled=false,playing=false,lastTick=0,selected=null,generation=0,periods=[],period={start:0,end:0},scopeLabel='',scopeHistory=null,highlightIds=null,requestedScopeIds=null;
  let texture=new THREE.DataTexture(new Float32Array([-1]),1,1,THREE.RedFormat,THREE.FloatType);texture.needsUpdate=true;
  const views=new Set();
  const uniforms={activityTexture:{value:activityTexture},activitySize:{value:new THREE.Vector2(1,1)},activityEnabled:{value:0},activityMode:{value:0},referenceQuantity:{value:10000},oilTexture:{value:texture},textureSize:{value:new THREE.Vector2(1,1)},productionEnabled:{value:0},wellContext:{value:0},faintColor:{value:new THREE.Color('#8fa5b5')},surveyColorEnabled:{value:0},lime:{value:new THREE.Color('#a3ff12')},missingColor:{value:new THREE.Color('#708391')},selectedIndex:{value:-1},viewport:{value:new THREE.Vector2(1,1)},referenceWidth:{value:10},cameraNear:{value:1}};
  function material(ribbon){return new THREE.ShaderMaterial({uniforms:{...uniforms,opacity:{value:1},ribbon:{value:ribbon?1:0}},vertexShader:ribbon?ribbonVertex:`${lookup}\nvoid main(){activityVisible=visibleAt(activityIndex);quantity=oilAt(productionIndex);wellIndex=productionIndex;surveyTint=surveyColor;groupEmphasis=groupSelected;uturnTint=uturnLateral;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,fragmentShader:fragment,transparent:true,depthWrite:false,side:THREE.DoubleSide})}
  function stop(){playing=false;$('productionPlay').textContent='Play';$('productionPlay').setAttribute('aria-pressed','false')}
  function setWellContext(mode='normal'){const modes={normal:0,faint:1,hidden:2};if(!Object.hasOwn(modes,mode))throw Error('Well context must be normal, faint or hidden.');uniforms.wellContext.value=modes[mode];}
  function setEnabled(value,{remember=true}={}){if(remember)requestedEnabled=!!value;enabled=!!value&&!!model;uniforms.productionEnabled.value=enabled?1:0;uniforms.activityEnabled.value=activityActive()?1:0;$('productionEnabled').checked=enabled;$('productionDetails').hidden=!enabled;$('productionTimeline').hidden=!enabled;for(const v of views)v.mesh.visible=enabled;if(!enabled)stop();selection(selected);announce();document.dispatchEvent(new CustomEvent('viewer:production-changed',{detail:{enabled,ready:!!model,playing}}))}
  function reset(){generation++;stop();model=null;oilModel=null;activityModel=null;activityError='';selected=null;scopeLabel='';scopeHistory=null;highlightIds=null;requestedScopeIds=null;uniforms.selectedIndex.value=-1;setEnabled(false,{remember:false});$('productionEnabled').disabled=true;$('productionStatus').textContent='Checking monthly production…';$('productionDetails').hidden=true}
  function drawScopeHistory(){const host=$('dsuProduction');if(!host)return;if(mode==='activity'){host.replaceChildren();if(scopeHistory)host.textContent='The timeline shows frac activity for the selected area. Switch to Monthly oil for the production history.';return;}if(!model||!scopeHistory){host.replaceChildren();if(scopeHistory)host.textContent='Monthly production is unavailable for this dataset.';return}renderScopeHistory(host,{...scopeHistory,matchedWells:model.scopeIndices.length,months:model.metadata.months,summaries:model.summaries,period,month})}
  function activityActive(){return enabled&&mode==='activity'&&!!activityModel}
  function visible(w){return !activityActive()||!!w&&activityModel.visible(w,month,includeUnknown)}
  function announce(){document.dispatchEvent(new CustomEvent('viewer:timeline-changed',{detail:{mode,enabled,date:model?.metadata.months[month]}}))}
  function drawLegend(){
    const water=mode==='activity',width=uniforms.referenceWidth.value,reference=water?10000000:10000;
    $('productionSizeValue').textContent=`${width} px at ${water?'10 million gal':'10,000 bbl'}`;
    $('productionLegend').replaceChildren();for(const value of [reference/10,reference,reference*4]){
      const row=document.createElement('div');row.className='production-key';const bar=document.createElement('i');bar.style.height=(width*Math.sqrt(value/reference))+'px';if(water)bar.style.background='#43c3ff';
      const label=document.createElement('span');label.textContent=fmt(value)+(water?' gal':' bbl');row.append(bar,label);$('productionLegend').append(row);
    }
    $('timelineWidthNote').textContent=water?'Width ∝ √reported carrier-water gallons, using one fixed scale across months. Blue width = reported frac water; thin amber = event with unavailable or review-required water; thin gray = no recorded event or reported zero.':'Width ∝ √monthly oil barrels, using one fixed scale across months. Thin muted lime = reported zero; gray = unavailable. Survey color options still apply.';
  }
  function updateVisibility(){
    if(!activityModel)return;
    const date=model?.metadata.months[month];activityTexture.image.data.fill(0);
    for(let i=0;i<activityModel.count;i++)activityTexture.image.data[i]=activityModel.visible(activityModel.metadata.wells[i],date,includeUnknown)?1:0;
    activityTexture.needsUpdate=true;
  }
  function statusText(){
    if(!model)return mode==='activity'?'Spud & frac activity unavailable: '+activityError:'Monthly oil unavailable for this dataset.';
    return `${monthLabel(model.metadata.months[0])}–${monthLabel(model.metadata.months.at(-1))} · ${fmt(model.scopeIndices.length)} mapped wells${scopeLabel?' in '+scopeLabel:''}`;
  }
  function setMonth(value){
    if(!model)return;month=Math.max(period.start,Math.min(period.end,Number(value)||0));
    model.uploadMonth(month,texture.image.data);texture.needsUpdate=true;updateVisibility();
    const date=model.metadata.months[month],s=model.summaries[month];$('productionMonth').value=String(month);$('productionMonth').setAttribute('aria-valuetext',monthLabel(date));$('productionDate').value=date;$('productionDateLabel').textContent=monthLabel(date);
    if(mode==='oil'){$('productionSummary').textContent=(scopeHistory&&scopeLabel?scopeLabel+' · ':'')+(s.reported?`${fmt(s.barrels)} bbl · ${fmt(s.producing)} producing well${s.producing===1?'':'s'}`:'No reported values for this month');
    $('productionCoverage').textContent=`${fmt(s.reported)} of ${fmt(model.scopeIndices.length)} matched well${model.scopeIndices.length===1?'':'s'} reported. Totals count each well once.`;
    }
    if(mode==='activity'){
      const missing=s.unavailableWaterWells,hidden=s.hiddenFracWells;
      $('productionSummary').textContent=(scopeLabel?scopeLabel+' · ':'')+`${fmt(s.knownGallons)} known gal · ${fmt(s.fracWells)} wells with disclosures · ${fmt(s.spudded)} spuds`;
      $('productionCoverage').textContent=`${fmt(s.visibleWells)} wells shown · ${fmt(s.fracEvents)} disclosures. ${missing?fmt(missing)+(missing===1?' well lacks':' wells lack')+' usable water; sum is partial. ':''}${hidden?fmt(hidden)+' wells with events hidden by unknown spud date. ':''}${fmt(s.unknownSpudWells)} spud dates unavailable. Full volume assigned once to job-end month.`;
      const cutoff=activityModel.metadata.provenance.latest_job_end?.slice(0,7);
      if(cutoff&&date>cutoff){$('productionSummary').textContent=`${fmt(s.spudded)} spuds · Frac coverage unavailable after ${cutoff}`;$('productionCoverage').textContent=`${fmt(s.visibleWells)} wells shown. Supplied FracFocus history ends ${cutoff}; later treatment activity is unknown.`;}
    }
    $('productionPrevious').disabled=month===period.start;$('productionNext').disabled=month===period.end;
    selection(selected);drawScopeHistory();announce();
  }
  function setPeriod(index){
    stop();period=periods[index];$('productionPeriod').value=String(index);
    $('productionMonth').min=period.start;$('productionMonth').max=period.end;
    $('productionDate').min=model.metadata.months[period.start];$('productionDate').max=model.metadata.months[period.end];
    $('productionRangeStart').textContent=model.metadata.months[period.start];$('productionRangeEnd').textContent=model.metadata.months[period.end];
    setMonth(period.end);
  }
  function setMode(value,{preserve=true}={}){
    const previous=preserve?model?.metadata.months[month]:null;stop();mode=value==='activity'?'activity':'oil';
    model=mode==='activity'?activityModel:oilModel;
    $('timelineMode').value=mode;$('activityOptions').hidden=mode!=='activity';
    uniforms.activityMode.value=mode==='activity'?1:0;uniforms.referenceQuantity.value=mode==='activity'?10000000:10000;
    $('productionEnabled').disabled=!model;$('productionStatus').textContent=statusText();
    $('productionSourceNote').textContent=mode==='activity'?'Local GIS spud dates + FracFocus disclosures. The whole current mapped trajectory appears from its reported spud month: a timing proxy, not as-drilled geometry. The full reported carrier-water volume is assigned once to the job END month, not spread across days. No event does not establish no frac. Ambiguous disclosures and missing volumes are excluded from the known-volume sum.':model?.metadata.displayNote||'Historical monthly oil. Missing records do not establish a drilling date.';
    if(mode==='activity'&&activityModel){const p=activityModel.metadata.provenance;$('productionSourceNote').textContent+=` FracFocus source includes jobs ending through ${p.latest_job_end||'unknown'}; snapshot coverage is not proof of completeness.`;}
    if(!model){setEnabled(false,{remember:false});return;}
    model.setBranchScope(requestedScopeIds);
    $('productionStatus').textContent=statusText();
    texture.dispose();const width=Math.min(1024,Math.max(1,model.count)),height=Math.max(1,Math.ceil(model.count/width));
    texture=new THREE.DataTexture(new Float32Array(width*height).fill(-1),width,height,THREE.RedFormat,THREE.FloatType);texture.needsUpdate=true;texture.minFilter=texture.magFilter=THREE.NearestFilter;
    uniforms.oilTexture.value=texture;uniforms.textureSize.value.set(width,height);
    for(const v of views)for(let i=0;i<v.ids.length;i++){
      const index=model.renderByBranch[v.ids[i]]??-1;v.line.geometry.attributes.productionIndex.setX(i*2,index);v.line.geometry.attributes.productionIndex.setX(i*2+1,index);v.mesh.geometry.attributes.productionIndex.setX(i,index);
      v.line.geometry.attributes.productionIndex.needsUpdate=true;v.mesh.geometry.attributes.productionIndex.needsUpdate=true;
    }
    periods=playbackPeriods(model.metadata.months);
    if(mode==='activity'){
      const first=model.metadata.months.findIndex(m=>m>=('2009-01'));
      if(first>0)periods.push({start:first,end:model.metadata.months.length-1,label:'2009–present · FracFocus era'});
    }
    $('productionPeriod').replaceChildren();periods.forEach((p,i)=>{const option=document.createElement('option');option.value=i;option.textContent=p.label;$('productionPeriod').append(option)});
    const target=params.get('month')&&!preserve?params.get('month'):previous||(mode==='activity'?activityModel.metadata.provenance.latest_job_end?.slice(0,7):null);
    const targetIndex=target?model.metadata.months.indexOf(target):-1;
    const pi=targetIndex>=0?periods.findIndex(p=>targetIndex>=p.start&&targetIndex<=p.end):periods.length-1;
    setPeriod(Math.max(0,pi));if(targetIndex>=0)setMonth(targetIndex);
    setEnabled(requestedEnabled,{remember:false});drawLegend();
  }
  async function load(read,survey,manifestBytes){
    reset();const version=generation;surveyWells=survey.wells;
    const results=await Promise.allSettled([
      (async()=>{const raw=await read('production.json',true);const data=new Float32Array(await read(raw.valuesFile||raw.file||'oil.bin'));return createProductionModel(raw,data,survey.wells)})(),
      (async()=>{const response=await fetch('./activity.json');if(!response.ok)throw Error('Local activity snapshot is not prepared.');const raw=await response.json();await validateActivitySnapshot(raw,manifestBytes);return createActivityModel(raw,survey.wells)})()
    ]);
    if(version!==generation)return;
    if(results[0].status==='fulfilled')oilModel=results[0].value;
    if(results[1].status==='fulfilled'){
      activityModel=results[1].value;activityModel.setIncludeUnknown(includeUnknown);const width=Math.min(1024,Math.max(1,activityModel.count)),height=Math.max(1,Math.ceil(activityModel.count/width));activityTexture.dispose();
      activityTexture=new THREE.DataTexture(new Float32Array(width*height).fill(1),width,height,THREE.RedFormat,THREE.FloatType);activityTexture.needsUpdate=true;activityTexture.minFilter=activityTexture.magFilter=THREE.NearestFilter;
      uniforms.activityTexture.value=activityTexture;uniforms.activitySize.value.set(width,height);
    }else activityError=results[1].reason.message;
    setMode(mode,{preserve:false});
  }
  function maskLine(line){
    const ids=line.userData.ids,values=new Float32Array(ids.length*2).fill(-1);
    for(let i=0;i<ids.length;i++)values[i*2]=values[i*2+1]=activityModel?.renderByBranch[ids[i]]??-1;
    line.geometry.setAttribute('activityIndex',new THREE.BufferAttribute(values,1));
    if(line.userData.section!==4){
      line.material.onBeforeCompile=shader=>{
        Object.assign(shader.uniforms,{activityTexture:uniforms.activityTexture,activitySize:uniforms.activitySize,activityEnabled:uniforms.activityEnabled});
        shader.vertexShader=maskLookup+'\n'+shader.vertexShader.replace('void main() {','void main() { activityVisible=visibleAt(activityIndex);');
        shader.fragmentShader='varying float activityVisible;\n'+shader.fragmentShader.replace('void main() {','void main() { if(activityVisible<0.5)discard;');
      };
      line.material.customProgramCacheKey=()=> 'local-activity-mask-v1';line.material.needsUpdate=true;
    }
  }
  function decorate(line){
    maskLine(line);if(line.userData.section!==4||(!oilModel&&!activityModel))return;
    const ids=line.userData.ids,indices=new Float32Array(ids.length),vertices=new Float32Array(ids.length*2);
    for(let i=0;i<ids.length;i++){const p=model?.renderByBranch[ids[i]]??-1;indices[i]=p;vertices[i*2]=vertices[i*2+1]=p}
    line.geometry.setAttribute('productionIndex',new THREE.BufferAttribute(vertices,1));
    const uturnInstances=new Float32Array(ids.length),uturnVertices=new Float32Array(ids.length*2);
    for(let i=0;i<ids.length;i++)if(line.userData.uturnMask?.[i]){uturnInstances[i]=1;uturnVertices[i*2]=uturnVertices[i*2+1]=1}
    line.geometry.setAttribute('uturnLateral',new THREE.BufferAttribute(uturnVertices,1));
    const scopeVertices=new THREE.BufferAttribute(new Float32Array(ids.length*2),1),scopeInstances=new THREE.InstancedBufferAttribute(new Float32Array(ids.length),1);line.geometry.setAttribute('groupSelected',scopeVertices);
    for(let i=0;i<ids.length;i++)if(highlightIds?.has(ids[i])){scopeVertices.setX(i*2,1);scopeVertices.setX(i*2+1,1);scopeInstances.setX(i,1)}
    let color=line.geometry.attributes.color;if(!color){const array=new Float32Array(ids.length*6),c=new THREE.Color('#a3ff12');for(let i=0;i<array.length;i+=3){array[i]=c.r;array[i+1]=c.g;array[i+2]=c.b}color=new THREE.BufferAttribute(array,3);line.geometry.setAttribute('color',color)}
    line.geometry.setAttribute('surveyColor',color);line.material.dispose();line.material=material(false);
    const g=new THREE.InstancedBufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute([0,-1,0,1,-1,0,1,1,0,0,1,0],3));g.setIndex([0,1,2,0,2,3]);
    const endpoints=new THREE.InstancedInterleavedBuffer(line.geometry.attributes.position.array,6);
    g.setAttribute('segmentStart',new THREE.InterleavedBufferAttribute(endpoints,3,0));g.setAttribute('segmentEnd',new THREE.InterleavedBufferAttribute(endpoints,3,3));g.setAttribute('productionIndex',new THREE.InstancedBufferAttribute(indices,1));g.instanceCount=ids.length;const colors=new THREE.InstancedInterleavedBuffer(color.array,6);g.setAttribute('surveyColor',new THREE.InterleavedBufferAttribute(colors,3,0));
    const activityIndices=new Float32Array(ids.length);for(let i=0;i<ids.length;i++)activityIndices[i]=activityModel?.renderByBranch[ids[i]]??-1;g.setAttribute('activityIndex',new THREE.InstancedBufferAttribute(activityIndices,1));
    g.setAttribute('uturnLateral',new THREE.InstancedBufferAttribute(uturnInstances,1));g.setAttribute('groupSelected',scopeInstances);const mesh=new THREE.Mesh(g,material(true));mesh.frustumCulled=false;mesh.visible=enabled;mesh.raycast=()=>{};line.add(mesh);
    const view={line,mesh,endpoints,colors,scopeVertices,scopeInstances,ids};views.add(view);line.userData.production=view;line.geometry.addEventListener('dispose',()=>views.delete(view));
  }
  function syncLine(line,opacity=1){const v=line.userData.production;if(!v)return;v.endpoints.needsUpdate=true;line.material.uniforms.opacity.value=opacity;v.mesh.material.uniforms.opacity.value=opacity}
  function selection(w){
    selected=w;const index=model?.indexOf(w)??-1;uniforms.selectedIndex.value=model?.renderIndexOf(w)??-1;
    const host=$('wellProduction');if(!host)return;host.replaceChildren();if(!model||!w)return;
    if(mode==='activity'){activitySelection(host,w,index);return;}
    const title=document.createElement('h4');title.textContent='Monthly oil production';const value=document.createElement('p');value.className='production-well-value';const oil=model.value(month,index);value.textContent=`${monthLabel(model.metadata.months[month])}: ${Number.isFinite(oil)?fmt(oil)+' bbl':'No reported value'}`;host.append(title,value);
    const note=document.createElement('p');note.className='caption';note.textContent=index<0?'No matching production well identifier.':'Whole-well volume across reported pools. Every survey branch shares this value.';host.append(note);if(index<0)return;
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 260 100');svg.setAttribute('role','img');svg.setAttribute('aria-label',`Monthly oil history for permit ${w.permit}; gaps indicate missing records.`);svg.classList.add('production-chart');let peak=0,reported=0;for(let i=period.start;i<=period.end;i++){const v=model.value(i,index);if(Number.isFinite(v)){peak=Math.max(peak,v);reported++}}if(!reported){const empty=document.createElement('p');empty.className='caption';empty.textContent='No reported values in this playback period.';host.append(empty);return}const max=Math.max(1,peak),chartX=i=>8+(i-period.start)/Math.max(1,period.end-period.start)*244;
    let path='',open=false;for(let i=period.start;i<=period.end;i++){const v=model.value(i,index);if(!Number.isFinite(v)){open=false;continue}const x=chartX(i),y=91-v/max*70;path+=`${open?'L':'M'}${x.toFixed(2)},${y.toFixed(2)} `;open=true;const dot=document.createElementNS(ns,'circle');dot.setAttribute('cx',x);dot.setAttribute('cy',y);dot.setAttribute('r','1.25');dot.setAttribute('fill','#a3ff12');const tip=document.createElementNS(ns,'title');tip.textContent=`${model.metadata.months[i]}: ${fmt(v)} bbl`;dot.append(tip);svg.append(dot)}
    const curve=document.createElementNS(ns,'path');curve.setAttribute('d',path);curve.setAttribute('fill','none');curve.setAttribute('stroke','#a3ff12');curve.setAttribute('stroke-width','1.5');svg.append(curve);const cursor=document.createElementNS(ns,'line');const x=chartX(month);for(const [k,v] of Object.entries({x1:x,x2:x,y1:18,y2:93,stroke:'#e5f0f6','stroke-dasharray':'3 3'}))cursor.setAttribute(k,v);svg.append(cursor);const label=document.createElementNS(ns,'text');label.setAttribute('x','8');label.setAttribute('y','12');label.setAttribute('fill','#9cb3c2');label.setAttribute('font-size','10');label.textContent=`Peak ${fmt(peak)} bbl/month · ${model.metadata.months[period.start]}–${model.metadata.months[period.end]}`;svg.append(label);host.append(svg);
  }
  function activitySelection(host,w,index){
    const row=activityModel.metadata.wells[index],date=model.metadata.months[month],water=model.value(month,index);
    const title=document.createElement('h4');title.textContent='Spud & frac activity';const spud=document.createElement('p');spud.textContent='Reported spud: '+(row?.spud_date||'unavailable');
    const value=document.createElement('p');value.className='production-well-value';value.textContent=`${monthLabel(date)}: ${model.status(month,index).water_status==='unmatched_identity'?'Activity identity unavailable':water>=0?fmt(water)+' gal reported water':water===-1?'Frac event · water unavailable / review required':'No recorded frac event'}`;
    if(date>model.metadata.provenance.latest_job_end?.slice(0,7))value.textContent=`${monthLabel(date)}: Outside supplied FracFocus history; activity unknown.`;
    const note=document.createElement('p');note.className='caption';note.textContent='Current mapped path shown from spud month. Water belongs to the whole well job; all mapped branches share its size, and totals count the well once.';host.append(title,spud,value,note);
    const events=(row?.events||[]).filter(e=>e.month&&e.month>=model.metadata.months[period.start]&&e.month<=model.metadata.months[period.end]);
    if(events.length){const label=document.createElement('p');label.className='caption';label.textContent='Jump to a recorded treatment:';host.append(label);for(const event of events.slice(-8)){const button=document.createElement('button');button.type='button';button.textContent=event.end+' · '+(event.water_gallons!==null&&!event.review_required?fmt(event.water_gallons)+' gal':'water unavailable / review');button.onclick=()=>{stop();const i=model.metadata.months.indexOf(event.month);if(i>=0){setEnabled(true);setMonth(i)}};host.append(button);}}
  }
  $('timelineMode').onchange=e=>setMode(e.target.value);
  $('activityUnknown').onchange=e=>{includeUnknown=e.target.checked;activityModel?.setIncludeUnknown(includeUnknown);setMonth(month)};
  $('productionEnabled').onchange=e=>setEnabled(e.target.checked);
  $('productionPeriod').onchange=e=>setPeriod(Number(e.target.value));
  $('productionMonth').oninput=e=>{stop();setMonth(e.target.value)};
  $('productionDate').onchange=e=>{if(!model)return;const i=model.metadata.months.indexOf(e.target.value);if(i>=0){stop();setMonth(i)}else e.target.value=model.metadata.months[month]};
  $('productionPrevious').onclick=()=>{stop();setMonth(month-1)};$('productionNext').onclick=()=>{stop();setMonth(month+1)};
  $('productionPlay').onclick=()=>{if(!model)return;if(playing){stop();return}setEnabled(true);document.dispatchEvent(new CustomEvent('viewer:production-play'));if(month===period.end){let first=period.start;while(first<period.end&&!(mode==='activity'?model.summaries[first].fracEvents:model.summaries[first].reported))first++;setMonth(first)}playing=true;lastTick=0;$('productionPlay').textContent='Pause';$('productionPlay').setAttribute('aria-pressed','true')};
  $('productionSize').oninput=e=>{uniforms.referenceWidth.value=+e.target.value;drawLegend()};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop()});
  return {activityActive,visible,load,reset,decorate,syncLine,selection,setEnabled,setWellContext,enabled:()=>enabled,pause:stop,setSurveyColoring:active=>{uniforms.surveyColorEnabled.value=active?1:0},ready:()=>!!model,
    setBranchScope(ids=null,label='operator filter'){scopeLabel=ids===null?'':label;requestedScopeIds=ids===null?null:[...ids];if(!model)return;model.setBranchScope(ids);const raw=model.metadata;$('productionStatus').textContent=`${monthLabel(raw.months[0])}–${monthLabel(raw.months.at(-1))} · ${fmt(model.scopeIndices.length)} matched well${model.scopeIndices.length===1?'':'s'}${scopeLabel?' in '+scopeLabel:''}`;setMonth(month)},
    setScopeHistory(value){scopeHistory=value;drawScopeHistory()},
    highlightBranches(ids=null){highlightIds=ids===null?null:new Set(ids);for(const v of views){for(let i=0;i<v.ids.length;i++){const value=highlightIds?.has(v.ids[i])?1:0;v.scopeVertices.setX(i*2,value);v.scopeVertices.setX(i*2+1,value);v.scopeInstances.setX(i,value)}v.scopeVertices.needsUpdate=true;v.scopeInstances.needsUpdate=true}},
    playScope(){if(!model||!model.scopeIndices.length)return;setEnabled(true);document.dispatchEvent(new CustomEvent('viewer:production-play'));let first=period.start;while(first<period.end&&!(mode==='activity'?model.summaries[first].fracEvents:model.summaries[first].reported))first++;setMonth(first);playing=true;lastTick=0;$('productionPlay').textContent='Pause';$('productionPlay').setAttribute('aria-pressed','true')},
    update(t,camera,width,height){uniforms.viewport.value.set(Math.max(1,width),Math.max(1,height));uniforms.cameraNear.value=camera.near;if(!playing)return;if(!lastTick){lastTick=t;return}if(t-lastTick>=1000/Number($('productionSpeed').value)){lastTick=t;if(month>=period.end)stop();else setMonth(month+1)}},
    pickPixels(w){if(w&&!visible(w))return -1;if(uniforms.wellContext.value>0.5||!enabled||!model)return 5;const quantity=w?model.value(month,model.indexOf(w)):mode==='activity'?model.summaries[month].maximumWater:model.summaries[month].maximumOil;return Math.max(5,(quantity>0?uniforms.referenceWidth.value*Math.sqrt(quantity/uniforms.referenceQuantity.value):0)/2+3)}
  };
}
