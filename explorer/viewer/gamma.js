import * as THREE from 'three';
import {buildGammaTubeBuffers,turboSRGB,srgbToLinear} from './gamma-geometry.js';

const $=id=>document.getElementById(id),fmt=(n,d=0)=>Number(n).toLocaleString('en-US',{maximumFractionDigits:d});
const SPECTRAL=['#5e4fa2','#3288bd','#66c2a5','#abdda4','#e6f598','#ffffbf','#fee08b','#fdae61','#f46d43','#d53e4f','#9e0142'].map(h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255));
export function gammaColor(t,palette='turbo'){
  t=Math.max(0,Math.min(1,t));if(palette==='turbo')return turboSRGB(t);
  const x=t*(SPECTRAL.length-1),i=Math.min(SPECTRAL.length-2,Math.floor(x)),f=x-i;
  return SPECTRAL[i].map((v,k)=>v+(SPECTRAL[i+1][k]-v)*f);
}
const POPULATIONS={averaged:{initial:500,maximum:1000,batch:100},detailed:{initial:50,maximum:100,batch:25}};
const PROFILES={
  gamma:{label:'Gamma ray',short:'GR',unit:'API',ceiling:300,unitPattern:/^(g?api|aapi)$/i},
  cbl:{label:'CBL amplitude',short:'CBL',unit:'mV',ceiling:100,unitPattern:/^mv$/i}
};
function dispose(o){o.traverse(v=>{v.geometry?.dispose();v.material?.dispose()});o.removeFromParent()}
function quantile(values,q){const a=values.filter(Number.isFinite).sort((a,b)=>a-b);if(!a.length)return 1;const x=(a.length-1)*q,i=Math.floor(x);return a[i]+(a[Math.ceil(x)]-a[i])*(x-i)}

export function createGammaController(root,{changed,focus,selectWell}){
  const group=new THREE.Group();group.name='Well log vertical tubes';root.add(group);
  const ray=new THREE.Raycaster(),entries=new Map(),pending=new Map(),requestVersions=new Map(),errors=new Map(),skippedNearby=new Map();
  let manifest=null,catalog=null,epoch=0,selectedPermit=null,active=false,lastHover=0,nearbyRun=null;const sourceRequests=new Map(),catalogPromises=new Map();
  const query=new URLSearchParams(location.search),wanted=query.get('gamma')==='1';
  let metric=query.get('log')==='cbl'?'cbl':'gamma',requestedActive=wanted,averageFt=query.get('average')==='0'?0:100;
  let permitFilter=null;const permitVisible=permit=>!permitFilter||permitFilter.has(String(permit));
  const population=()=>averageFt?POPULATIONS.averaged:POPULATIONS.detailed;
  const profile=()=>PROFILES[metric],validUnit=u=>profile().unitPattern.test((u||'').trim());
  function configureMetric(){
    const p=profile();$('logType').value=metric;$('logEnabledLabel').textContent=`${p.short} radius and color`;
    $('logRawOption').textContent=`Shared ${p.unit} scale`;$('logCeilingLabel').textContent=`${p.unit} scale maximum`;
    $('gammaCeiling').value=String(p.ceiling);$('gammaMode').value='raw';
    $('gammaColorbar').setAttribute('aria-label',`${p.label} color scale`);
    $('logMeaning').textContent=metric==='cbl'?'Lower amplitude can indicate stronger casing-to-cement bonding. Tool, casing and well conditions affect the response; this view does not assign a bond-quality grade.':'';
    $('logMeaning').hidden=metric!=='cbl';
    $('logRadiusDescription').textContent=`Radius increases linearly with ${p.short==='CBL'?'measured CBL amplitude':'GR'} up to the scale maximum. Display radius is exaggerated, not ${metric==='cbl'?'cement thickness or bore diameter':'bore diameter'}. Source gaps remain open.${metric==='cbl'?' A thin gray centerline keeps zero-amplitude intervals visible.':''}`;
  }
  function configureSampling(){
    $('logSampling').value=String(averageFt);
    const p=population();$('logPopulation').textContent=`Starts with ${fmt(p.initial)} nearby wells. Add up to ${fmt(p.maximum)} in one view; remove wells with × to make room.`;
    $('logSamplingNote').textContent=averageFt?'Values are averaged within 100 ft of measured depth. Short changes are smoothed; switch to Detailed to inspect them. Missing intervals stay open.':`Detailed ${metric==='cbl'?'5':'10'} ft display spacing. The smaller well group keeps the finer view manageable.`;
    $('logRadiusDescription').textContent=`Radius and color follow ${averageFt?'100 ft interval means':'measured log values'} up to the scale maximum. Radius is exaggerated for display. Missing intervals stay open.${metric==='cbl'?' A thin gray centerline keeps zero-amplitude intervals visible.':''}`;
  }
  configureMetric();configureSampling();
  function status(s){$('gammaStatus').textContent=s}
  function enabled(){return active&&!!catalog}
  function contextVisible(){return !enabled()||$('gammaContext').checked}
  function controlValues(){return {radius:+$('gammaRadius').value,maximum:Math.max(1,+$('gammaCeiling').value||profile().ceiling),mode:$('gammaMode').value,palette:$('gammaPalette').value}}
  function legend(){const c=controlValues(),stops=Array.from({length:25},(_,i)=>{const rgb=gammaColor(i/24,c.palette).map(v=>Math.round(v*255));return `rgb(${rgb.join(',')}) ${i/24*100}%`});$('gammaColorbar').style.background=`linear-gradient(to right,${stops.join(',')})`;$('gammaLegend').replaceChildren();for(const label of c.mode==='raw'?[`0 ${profile().unit}`,`${fmt(c.maximum)}+ ${profile().unit}`]:['0','95th percentile+']){const span=document.createElement('span');span.textContent=label;$('gammaLegend').append(span)}$('gammaRadiusValue').textContent=`${c.radius} ft`;$('gammaCeiling').disabled=c.mode!=='raw'}
  function occupied(){return entries.size+[...pending.keys()].filter(p=>!entries.has(p)).length}
  function report(){
    const count=[...entries.values()].filter(e=>permitVisible(e.permit)&&e.meshes.length).length;
    const loading=nearbyRun?` · adding ${nearbyRun.completed}/${nearbyRun.total}…`:pending.size?' · loading…':'';
    status(`${count} ${profile().short} well${count===1?'':'s'} displayed · ${fmt(population().maximum)} maximum · ${averageFt?'100 ft means':'detailed'}${loading}${skippedNearby.size?' · '+skippedNearby.size+' sources skipped':''}${errors.size?' · '+[...errors.values()].at(-1):''}`);
    const remaining=Math.max(0,population().maximum-occupied());
    $('gammaNearby').disabled=!!nearbyRun||!remaining;
    $('gammaNearby').textContent=nearbyRun?'Adding wells…':remaining?`Add ${Math.min(population().batch,remaining)} nearby`:`${fmt(population().maximum)} wells loaded`;
  }
  function limits(permit=null){const es=permit?[entries.get(permit)].filter(Boolean):[...entries.values()];const box=new THREE.Box3();for(const e of es.filter(e=>permitVisible(e.permit)))for(const mesh of e.meshes){mesh.geometry.computeBoundingBox();box.union(mesh.geometry.boundingBox)}if(box.isEmpty())return null;return [...box.min.toArray(),...box.max.toArray()]}
  function focusGamma(permit=null){const b=limits(permit);if(b)focus(b)}
  function note(e){const unit=e.data.unit||e.data.source?.unit||'unknown';const source=e.data.source||{};const flags=(e.data.flags||[]).map(v=>typeof v==='string'?v:JSON.stringify(v));return `${source.file||'LAS'} · ${source.mnemonic||profile().label} (${unit}). ${e.data.sampling||e.data.samplingMethod||'10 ft measured-depth samples; linear survey interpolation'}. ${e.incompatible?`This source needs the relative scale because its units are not ${profile().unit}. `:''}${flags.slice(0,3).join(' ')}`}
  function sourcePicker(){const entry=entries.get(selectedPermit),well=catalog?.wells?.[selectedPermit];$('gammaSource').hidden=!well;$('gammaSourceLabel').hidden=!well;if(!well){$('gammaSourceNote').textContent='Select a survey well to add its log.';return}if(!well.sources&&!sourceRequests.has(selectedPermit)){const permit=selectedPermit,version=epoch;sourceRequests.set(permit,fetch(`/api/${metric}/sources?permit=${encodeURIComponent(permit)}`).then(r=>{if(!r.ok)throw Error('Source list unavailable');return r.json()}).then(data=>{if(version!==epoch)return;Object.assign(well,data);if(selectedPermit===permit)sourcePicker()}).catch(()=>{if(version===epoch&&selectedPermit===permit)$('gammaSourceNote').textContent='Source list unavailable.'}))}const sources=well.sources||[entry?.data.source].filter(Boolean),picker=$('gammaSource');picker.replaceChildren();for(const source of sources){const option=document.createElement('option');option.value=source.id;option.textContent=`${source.file} · ${source.mnemonic} (${source.unit||'unknown units'})`;option.disabled=!!source.errors?.length;picker.append(option)}picker.value=entry?.sourceId||well.defaultSourceId||sources[0]?.id;$('gammaSourceNote').textContent=entry?note(entry):'Loading selected log…'}
  function list(){const host=$('gammaWells');host.replaceChildren();for(const [permit,e]of entries){if(!permitVisible(permit))continue;const row=document.createElement('div');row.className='gamma-well';const b=document.createElement('button');b.type='button';b.textContent=`${permit} · ${e.data.unit||e.data.source?.unit||'?'}${e.meshes.length?'':' · no tube'}`;b.setAttribute('aria-pressed',String(permit===selectedPermit));b.onclick=()=>{selectedPermit=permit;sourcePicker();list();focusGamma(permit);selectWell(permit)};const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Remove ${profile().short} well ${permit}`);remove.onclick=()=>{requestVersions.set(permit,(requestVersions.get(permit)||0)+1);pending.delete(permit);errors.delete(permit);entries.get(permit)?.meshes.forEach(dispose);entries.delete(permit);if(selectedPermit===permit)selectedPermit=null;list();sourcePicker();report();changed()};row.append(b,remove);host.append(row)}sourcePicker()}
  function renderEntry(e){e.meshes.forEach(dispose);e.meshes=[];const c=controlValues(),unit=e.data.unit||e.data.source?.unit;e.incompatible=c.mode==='raw'&&!validUnit(unit);if(e.incompatible)return;
    const all=(e.data.paths||[]).flatMap(p=>p.points.map(v=>v[4]));e.q95=Math.max(1e-6,e.data.aggregation&&Number.isFinite(e.data.stats?.percentiles?.['95'])?e.data.stats.percentiles['95']:quantile(all,.95));const ceiling=c.mode==='raw'?c.maximum:e.q95;
    for(const path of e.data.paths||[]){const samples=path.points.map(v=>({x:v[0],y:v[1],z:v[2],md:v[3],gr:v[4]}));const buffers=buildGammaTubeBuffers(samples,{sides:10,maxGapMD:2.5*(e.data.stats?.displayStepFt||10),maxVertices:200000,radiusAt:s=>c.radius*Math.min(1,Math.max(0,s.gr)/ceiling),colorAt:s=>gammaColor(s.gr/ceiling,c.palette).map(srgbToLinear)});if(!buffers.indices.length)continue;
      const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(buffers.positions,3));geometry.setAttribute('color',new THREE.BufferAttribute(buffers.colors,3));geometry.setIndex(new THREE.BufferAttribute(buffers.indices,1));geometry.computeBoundingSphere();
      const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({vertexColors:true,toneMapped:false,side:THREE.DoubleSide}));mesh.userData.gamma={entry:e,path,samples,faceSources:buffers.faceSources,ceiling};if(metric==='cbl'){
        const centerPositions=[],centerSources=[];
        for(let i=0;i<buffers.faceSources.length;i+=40){const a=buffers.faceSources[i],b=buffers.faceSources[i+1];centerPositions.push(samples[a].x,samples[a].y,samples[a].z,samples[b].x,samples[b].y,samples[b].z);centerSources.push(a,b)}
        const centerGeometry=new THREE.BufferGeometry();centerGeometry.setAttribute('position',new THREE.Float32BufferAttribute(centerPositions,3));
        const centerLine=new THREE.LineSegments(centerGeometry,new THREE.LineBasicMaterial({color:'#8496aa',transparent:true,opacity:.6,toneMapped:false}));
        centerLine.userData.gamma={...mesh.userData.gamma,centerSources};mesh.add(centerLine);
      }
      mesh.visible=permitVisible(e.permit);group.add(mesh);e.meshes.push(mesh);
    }
  }
  function rebuild(){legend();for(const e of entries.values())renderEntry(e);list();report();changed()}
  async function add(permit,sourceId=null,automatic=false){
    permit=String(permit);if(!permitVisible(permit))return null;const explicit=sourceId!==null,candidate=catalog?.wells?.[permit];
    if(!candidate){status(`No matched ${profile().short} catalog entry for ${permit}.`);return null}
    sourceId=sourceId||entries.get(permit)?.sourceId||candidate.defaultSourceId||candidate.sources?.[0]?.id;
    if(!sourceId){status(`${permit}: no eligible ${profile().short} source; inspect its headers.`);return null}
    const old=entries.get(permit);
    if(old?.sourceId===sourceId){if(explicit){requestVersions.set(permit,(requestVersions.get(permit)||0)+1);pending.delete(permit);report()}return old}
    const inflight=pending.get(permit);if(inflight?.sourceId===sourceId)return inflight.task;
    if(!old&&!inflight&&occupied()>=population().maximum){status(`The ${population().maximum}-well view is full. Remove a displayed well to add another.`);return null}
    const version=epoch,requestVersion=(requestVersions.get(permit)||0)+1;
    requestVersions.set(permit,requestVersion);errors.delete(permit);
    const task=(async()=>{try{
      const response=await fetch(`/api/${metric}/well?permit=${encodeURIComponent(permit)}&source=${encodeURIComponent(sourceId)}&average=${averageFt}`);
      const data=await response.json();if(!response.ok||data.error)throw Error(data.error||'Log read failed');
      if(version!==epoch||requestVersions.get(permit)!==requestVersion)return null;
      entries.get(permit)?.meshes.forEach(dispose);const e={permit,sourceId,data,meshes:[]};entries.set(permit,e);
      renderEntry(e);if(automatic&&!e.meshes.length){entries.delete(permit);skippedNearby.set(permit,'No drawable log interval for the current scale');return null}if(!automatic)list();changed();return e;
    }catch(error){if(version===epoch&&requestVersions.get(permit)===requestVersion){if(automatic){skippedNearby.set(permit,error.message);if(entries.get(permit)?.sourceId===sourceId){entries.get(permit).meshes.forEach(dispose);entries.delete(permit)}}else errors.set(permit,`${permit}: ${error.message}`)}return null}
    finally{if(pending.get(permit)?.task===task)pending.delete(permit);if(version===epoch){report();sourcePicker()}}})();
    pending.set(permit,{sourceId,task});report();return task;
  }
  async function nearby(centerPermit=selectedPermit||'21994',count=population().batch){
    if(!catalog||!manifest||nearbyRun)return;
    const available=Math.max(0,population().maximum-occupied());if(!available){report();return}
    const raw=controlValues().mode==='raw';
    const verticals=manifest.wells.filter(w=>permitVisible(w.permit)&&w.branch==='VERT'&&catalog.wells[w.permit]?.defaultSourceId&&(!raw||validUnit(catalog.wells[w.permit].defaultUnit)));
    const center=verticals.find(w=>w.permit===String(centerPermit))||verticals[0];if(!center){status('No nearby sources compatible with the current scale.');return}
    const cx=(center.bounds[0]+center.bounds[3])/2,cz=(center.bounds[2]+center.bounds[5])/2;
    const candidates=verticals.map(w=>({w,d:Math.hypot((w.bounds[0]+w.bounds[3])/2-cx,(w.bounds[2]+w.bounds[5])/2-cz)})).sort((a,b)=>a.d-b.d);
    const permits=[...new Set(candidates.map(v=>String(v.w.permit)))].filter(p=>!entries.has(p)&&!pending.has(p)&&!skippedNearby.has(p));
    if(!permits.length){status('No additional nearby sources are available.');return}
    const version=epoch,run={completed:0,total:Math.min(count,available),attempted:0};nearbyRun=run;report();
    try{
      let cursor=0,framed=false;
      while(cursor<permits.length&&run.completed<run.total){
        if(version!==epoch||!active)return;
        const room=population().maximum-occupied();if(room<=0)break;
        const batch=permits.slice(cursor,cursor+Math.min(3,run.total-run.completed,room));cursor+=batch.length;
        await Promise.all(batch.map(async p=>{const e=await add(p,null,true);if(version===epoch){run.attempted++;if(e?.meshes.length)run.completed++;report()}}));
        if(version!==epoch||!active)return;
        list();
        if(!framed&&run.completed){selectedPermit=String(center.permit);focusGamma();framed=true}
        await new Promise(resolve=>setTimeout(resolve,0));
      }
      if(version!==epoch||!active)return;selectedPermit=String(center.permit);list();focusGamma();
    }finally{if(nearbyRun===run){nearbyRun=null;report()}}
  }
  function setActive(value){requestedActive=!!value;active=requestedActive&&!!catalog;$('gammaEnabled').checked=active;group.visible=active;$('gammaDetails').hidden=!active;if(!active)$('gammaHover').hidden=true;changed();if(active&&!entries.size)nearby(selectedPermit||'21994',population().initial);}
  function reset(){++epoch;nearbyRun=null;for(const e of entries.values())e.meshes.forEach(dispose);entries.clear();pending.clear();requestVersions.clear();errors.clear();skippedNearby.clear();sourceRequests.clear();selectedPermit=null;catalog=null;manifest=null;active=false;group.visible=false;$('gammaEnabled').checked=false;$('gammaEnabled').disabled=true;$('gammaDetails').hidden=true;$('gammaHover').hidden=true;changed()}
  async function load(m,{activate=wanted,centerPermit='21994'}={}){requestedActive=activate;reset();const version=epoch,loadingMetric=metric;manifest=m;selectedPermit=centerPermit;status(`Reading ${profile().short} catalog…`);
    try{if(!catalogPromises.has(loadingMetric))catalogPromises.set(loadingMetric,fetch(`/api/${loadingMetric}/catalog`).then(async r=>{if(!r.ok)throw Error('Start the log-enabled local viewer to load LAS data.');return r.json()}).catch(e=>{catalogPromises.delete(loadingMetric);throw e}));const c=await catalogPromises.get(loadingMetric);if(version!==epoch)return;if(m.sourceCRS!=='NAD83'||!m.origin||Math.abs(m.origin[0]+102.99897097700921)>1e-6||Math.abs(m.origin[1]-47.91137672734358)>1e-6)throw Error('Well log overlay uses the prepared full survey dataset.');catalog={...c,wells:Array.isArray(c.wells)?Object.fromEntries(c.wells.map(w=>[String(w.permit),{...w}])):c.wells};sourceRequests.clear();$('gammaEnabled').disabled=false;legend();report();if(activate){setActive(true)}}catch(e){if(version===epoch)status(e.message)}
  }
  function selected(w){if(!active||!w||!permitVisible(w.permit))return;selectedPermit=String(w.permit);sourcePicker();add(selectedPermit).then(()=>{list();sourcePicker()})}
  function intersection(event,camera,rect){if(!active)return null;ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);const meshes=[...entries.values()].filter(e=>permitVisible(e.permit)).flatMap(e=>e.meshes);ray.params.Line.threshold=12;const hit=ray.intersectObjects([...meshes,...(metric==='cbl'?meshes.flatMap(m=>m.children):[])],false)[0];if(!hit)return null;const u=hit.object.userData.gamma,sourceIndices=hit.object.isLineSegments?u.centerSources:u.faceSources,sourceOffset=hit.object.isLineSegments?hit.index:hit.faceIndex*2,a=u.samples[sourceIndices[sourceOffset]],b=u.samples[sourceIndices[sourceOffset+1]],local=hit.object.worldToLocal(hit.point.clone());const va=new THREE.Vector3(a.x,a.y,a.z),vb=new THREE.Vector3(b.x,b.y,b.z),v=vb.clone().sub(va);const t=Math.max(0,Math.min(1,local.clone().sub(va).dot(v)/Math.max(1e-9,v.lengthSq())));const md=a.md+(b.md-a.md)*t;
    const binA=u.path.bins?.[u.path.pointBinIndices?.[sourceIndices[sourceOffset]]],binB=u.path.bins?.[u.path.pointBinIndices?.[sourceIndices[sourceOffset+1]]];
    const bin=binA&&md>=binA.startMD&&md<=binA.endMD?binA:binB||binA;
    return {entry:u.entry,branch:u.path.branch,point:hit.point,md,gr:bin?.mean??(a.gr+(b.gr-a.gr)*t),maximum:u.ceiling,bin} }
  function hover(event,camera,rect){if(performance.now()-lastHover<45)return;lastHover=performance.now();const hit=intersection(event,camera,rect),host=$('gammaHover');host.hidden=!hit;if(!hit)return;host.replaceChildren();const title=document.createElement('strong');title.textContent=`${hit.entry.permit} · ${hit.branch}`;const values=document.createElement('span');values.textContent=`${hit.bin?'Mean ':''}${profile().short} ${fmt(hit.gr,1)} ${hit.entry.data.unit||hit.entry.data.source?.unit||''} · MD ${fmt(hit.md,0)} ft`;
    if(hit.bin){const interval=document.createElement('span');interval.textContent=`${fmt(hit.bin.startMD)}–${fmt(hit.bin.endMD)} ft MD · ${fmt(hit.bin.coverageFraction*100)}% covered`;host.append(interval);const range=document.createElement('span');range.textContent=`Source range ${fmt(hit.bin.min,1)}–${fmt(hit.bin.max,1)} · ${fmt(hit.bin.sampleCount)} samples`;host.append(range)}const src=document.createElement('span');src.textContent=hit.entry.data.source?.file||'';host.prepend(title,values);host.append(src);host.style.left=Math.min(rect.width-host.offsetWidth-10,Math.max(10,event.clientX-rect.left+14))+'px';host.style.top=Math.min(rect.height-host.offsetHeight-10,Math.max(10,event.clientY-rect.top+14))+'px'}
  $('logType').onchange=e=>{const next=e.target.value;if(!PROFILES[next]||next===metric)return;const m=manifest,activate=requestedActive,centerPermit=selectedPermit||'21994';metric=next;configureMetric();configureSampling();if(m)load(m,{activate,centerPermit});};
  $('logSampling').onchange=e=>{const next=Number(e.target.value);if(![0,100].includes(next)||next===averageFt)return;const m=manifest,activate=requestedActive,centerPermit=selectedPermit||'21994';averageFt=next;configureSampling();if(m)load(m,{activate,centerPermit});};
  $('gammaEnabled').onchange=e=>setActive(e.target.checked);$('gammaPalette').onchange=rebuild;$('gammaRadius').oninput=rebuild;$('gammaMode').onchange=rebuild;$('gammaCeiling').onchange=()=>{if($('gammaCeiling').checkValidity())rebuild()};$('gammaContext').onchange=changed;$('gammaFocus').onclick=()=>focusGamma();$('gammaNearby').onclick=()=>nearby(selectedPermit||'21994',population().batch);$('gammaSource').onchange=e=>{if(selectedPermit)add(selectedPermit,e.target.value)};
  function setPermitFilter(permits=null){permitFilter=permits===null?null:new Set(permits.map(String));for(const e of entries.values())for(const mesh of e.meshes)mesh.visible=permitVisible(e.permit);if(selectedPermit&&!permitVisible(selectedPermit))selectedPermit=null;list();report();$('gammaHover').hidden=true;}
  return {setPermitFilter,load,reset,enabled,contextVisible,selected,intersection,hover,focus:focusGamma,limits,group};
}
