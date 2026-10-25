import * as THREE from 'three';
import {prepareDSUs,buildDSUPrisms} from './dsu-model.js';
import {DEFAULT_SCENARIOS,validateScenarios,scenarioMetrics,turboHex,createFootageColorScale,validateFootageSnapshot} from './footage-model.js';

const $=id=>document.getElementById(id),fmt=(v,d=0)=>Number.isFinite(v)?v.toLocaleString('en-US',{maximumFractionDigits:d}):'Unavailable';
const LABELS={mappedFt:'Surveyed lateral feet · drilled proxy',developmentPct:'Mapped lateral development',remainingFt:'Scenario feet remaining'};
const GRADIENT='linear-gradient(90deg,'+Array.from({length:17},(_,i)=>turboHex(i/16)).join(',')+')';
const digest=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');

export function createFootageController(scene,{dsu,focus,say}){
  const group=new THREE.Group();group.name='Township footage inventory';group.visible=false;group.position.y=40;scene.add(group);
  const raycaster=new THREE.Raycaster();let manifest=null,expectedHash=null,data=null,maps=null,towns=[],selectedTown=null,batch=null,mesh=null,edges=null,highlight=null,pending=null,generation=0;
  let rates={...DEFAULT_SCENARIOS},scenario='base',layer='dsu',metric='developmentPct';
  // Layers have identical, independent visibility on every viewport.
  let townshipRequested=false,loadFailed=false;
  try{const saved=localStorage.getItem('bakken-footage-scenarios-v1');if(saved)rates=validateScenarios(JSON.parse(saved))}catch{}
  for(const name of ['low','base','high'])$('footageRate-'+name).value=rates[name];
  const scaleCache=new Map();
  const enabled=()=>$('footageEnabled').checked;
  const townshipVisible=()=>!loadFailed&&townshipRequested;
  const layersChanged=()=>document.dispatchEvent(new CustomEvent('viewer:layers-changed',{detail:{townshipRequested:townshipVisible(),townshipVisible:group.visible,loading:!!pending,independentLayers:true}}));
  const selectionChanged=(interactive=false)=>document.dispatchEvent(new CustomEvent('viewer:selection-changed',{detail:{kind:'township',selected:selectedTown,selection:townSelection(),interactive}}));
  // Showing a layer does not silently change which object a click selects.
  $('townshipInspect').checked=false;
  function townSelection(){return selectedTown?{kind:'township',id:selectedTown.id,label:selectedTown.properties.label,bounds:townBounds(selectedTown),unit:selectedTown}:null}
  function clearSelection(){
    const changed=!!selectedTown;selectedTown=null;
    if(highlight){highlight.geometry.dispose();highlight.material.dispose();group.remove(highlight);highlight=null}
    $('footageSelection').replaceChildren();if(changed)selectionChanged();
  }
  const records=kind=>Object.values(data?.[kind==='dsu'?'dsus':'townships']||{});
  const currentRate=()=>rates[scenario];
  const getScale=(kind,key=metric)=>{const id=`${kind}|${key}|${rates.low}|${rates.base}|${rates.high}|${scenario}`;if(!scaleCache.has(id))scaleCache.set(id,createFootageColorScale(records(kind),key==='remainingFt'?rates.high:currentRate(),{metric:key,layer:kind}));return scaleCache.get(id)};
  const metrics=record=>scenarioMetrics(record,currentRate());
  function assertRatesFit(candidate,payload=data){if(payload)for(const record of [...Object.values(payload.dsus),...Object.values(payload.townships)])for(const name of ['low','base','high'])scenarioMetrics(record,candidate[name]);return candidate}
  function color(record,kind=layer,key=metric){
    const scale=getScale(kind,key);
    const value=scenarioMetrics(record,currentRate())?.[key];return Number.isFinite(value)?turboHex(scale.normalize(value)):'#6b7280';
  }
  function describe(kind=layer,key=metric){
    const scale=getScale(kind,key),r=scale.range;
    return `${LABELS[key]} · ${kind==='township'?'DSU-covered township portion':'DSU footprint'} · ${scenario} capacity · ${fmt(currentRate(),2)} ft/ac · Turbo ${fmt(r[0])}–${fmt(r[1])}${key==='developmentPct'?'%':' ft'}${key==='developmentPct'?' (values above 100% retained)':' (color capped at P98; same range across scenarios)'} · gray = unavailable`;
  }
  function panel(record,title,legacy=null){
    const box=document.createElement('section');box.className='footage-card';
    const heading=document.createElement('h4');heading.textContent=title;box.append(heading);
    if(!record||!record.eligible){const p=document.createElement('p');p.textContent='Footage scenario unavailable: unsupported formation or no eligible DSU-covered acreage.';box.append(p);return box}
    const list=document.createElement('dl');
    const measurements=[['Surveyed lateral ft',fmt(record.mapped_lateral_ft)+' ft'],['Measured eligible acres',fmt(record.eligible_acres,1)+' ac'],['Observed intersecting wells',fmt(record.observed_wells)]];
    if(Number.isFinite(record.full_acres)&&record.full_acres>0)measurements.push(['Full township acres',fmt(record.full_acres,1)+' ac'],['DSU-covered share',fmt(100*record.eligible_acres/record.full_acres,1)+'%']);
    for(const [name,value] of measurements){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;list.append(dt,dd)}box.append(list);
    const table=document.createElement('table');table.className='footage-table';const caption=document.createElement('caption');caption.textContent='Illustrative capacity scenarios · all surveyed operators';table.append(caption);
    const head=document.createElement('thead'),tr=document.createElement('tr');for(const text of ['Case','Capacity ft','Developed','Feet left']){const th=document.createElement('th');th.scope='col';th.textContent=text;tr.append(th)}head.append(tr);table.append(head);
    const body=document.createElement('tbody');for(const name of ['low','base','high']){const m=scenarioMetrics(record,rates[name]),row=document.createElement('tr');if(name===scenario)row.className='active-scenario';for(const text of [name,fmt(m.capacityFt),fmt(m.developmentPct,1)+(Number.isFinite(m.developmentPct)?'%':''),fmt(m.remainingFt)]){const td=document.createElement('td');td.textContent=text;row.append(td)}body.append(row)}table.append(body);box.append(table);
    const active=metrics(record),note=document.createElement('p');note.className='caption';note.textContent=`Mapped classified lateral footage is a drilling proxy, not verified completed footage. Target and branch status are unverified. ${active.excessFt>0?fmt(active.excessFt)+' ft above the selected benchmark; review density/geometry. ':''}Footage headroom does not establish feasible well locations.`;box.append(note);
    if(legacy){const details=document.createElement('details'),summary=document.createElement('summary');details.open=true;summary.textContent='Compare September 12 results';details.append(summary);const p=document.createElement('p');p.className='caption';p.textContent=legacy.matched&&!legacy.underReview&&legacy.eligible?`Saved remaining wells: ${fmt(legacy.remainingWells,1)} · development: ${fmt(legacy.developmentPercent,1)}%. Count-based historical model; units differ from the new footage scenarios.`:'Saved September estimate unavailable, unmatched, or under review. This is not zero remaining inventory.';details.append(p);box.append(details)}
    return box;
  }
  function refreshDSU(){
    dsu.setFootageAnalysis(data?{gradient:GRADIENT,color:(unit,key)=>color(data.dsus[unit.id],'dsu',key),legend:key=>describe('dsu',key),panel:unit=>panel(data.dsus[unit.id],'Lateral footage scenarios',unit.properties.inventory)}:null);
  }
  function legend(){
    $('footageColorbar').style.background=GRADIENT;$('footageLegend').textContent=data?describe():'Waiting for a matching full survey dataset.';
  }
  function clearTownMeshes(){for(const o of [...group.children]){o.geometry?.dispose();o.material?.dispose();group.remove(o)}batch=mesh=edges=highlight=null}
  function drawTowns(){
    clearTownMeshes();if(!data||!towns.length)return;
    batch=buildDSUPrisms(towns,{layout:'source',colorForUnit:u=>new THREE.Color(color(data.townships[u.id],'township'))});
    mesh=new THREE.Mesh(batch.geometry,new THREE.MeshBasicMaterial({vertexColors:true,side:THREE.DoubleSide,transparent:true,opacity:.2,depthWrite:false}));mesh.renderOrder=-4;group.add(mesh);
    edges=new THREE.LineSegments(batch.edgeGeometry,new THREE.LineBasicMaterial({vertexColors:true,transparent:true,opacity:.9,depthWrite:false}));edges.renderOrder=-3;group.add(edges);
    if(selectedTown)selectTown(selectedTown,{interactive:false});
  }
  function selectTown(unit,{interactive=true}={}){
    if(!group.visible||!unit)return;
    const i=towns.indexOf(unit),r=batch?.ranges[i];if(!r)return;
    selectedTown=unit;if(highlight){highlight.geometry.dispose();highlight.material.dispose();group.remove(highlight)}
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(edges.geometry.attributes.position.array.slice(r.edgeStart*3,r.edgeEnd*3),3));
    highlight=new THREE.LineSegments(g,new THREE.LineBasicMaterial({color:'#fff',depthTest:false}));highlight.renderOrder=4;group.add(highlight);
    const host=$('footageSelection');host.replaceChildren(panel(data.townships[unit.id],unit.properties.label));const button=document.createElement('button');button.className='primary';button.textContent='Zoom to township';button.onclick=()=>zoomTown(unit);host.prepend(button);selectionChanged(interactive);
  }
  function townBounds(unit){const b=unit.bounds.slice();b[1]=-11000;b[4]=100;return b}
  function zoomTown(unit){if(unit)focus(townBounds(unit))}
  function search(){
    const host=$('townshipResults');host.replaceChildren();const query=$('townshipSearch').value.trim().toLowerCase().replace(/\s+/g,'');if(!query||!data)return;
    const matches=towns.filter(u=>(u.properties.label+' '+u.id).toLowerCase().replace(/\s+/g,'').includes(query));const count=document.createElement('p');count.className='caption';count.textContent=`${fmt(matches.length)} township matches${matches.length>15?' · first 15 shown':''}`;host.append(count);
    for(const unit of matches.slice(0,15)){const b=document.createElement('button');b.textContent=unit.properties.label;b.onclick=()=>{setTownshipVisible(true);selectTown(unit);zoomTown(unit)};host.append(b)}
  }
  async function ensure(){
    if(data||!manifest)return;if(pending)return pending;const version=generation,m=manifest;
    loadFailed=false;
    $('footageStatus').textContent='Checking survey snapshot and loading projected footage…';
    const task=(async()=>{try{
      const get=async path=>{const r=await fetch(new URL(path,import.meta.url));if(!r.ok)throw Error('Footage data is not installed.');return r.arrayBuffer()};
      const [bytes,townBytes,dsuBytes]=await Promise.all([get('./data/inventory/footage.json'),get('./data/inventory/townships.geojson'),get('./data/dsu/drilling-spacing-units.geojson')]);
      const payload=JSON.parse(new TextDecoder().decode(bytes)),townData=JSON.parse(new TextDecoder().decode(townBytes));const hash=await expectedHash;
      const dsuSource=JSON.parse(new TextDecoder().decode(dsuBytes));
      const checked=validateFootageSnapshot(payload,m,hash,{dsuIds:dsuSource.features.map(f=>f.id),townshipIds:townData.features.map(f=>f.id)});
      if(await digest(dsuBytes)!==payload.source_hashes.dsu_file_sha256)throw Error('Footage data does not match the installed DSU boundaries.');
      if(payload.source_hashes.townships_geojson_sha256&&await digest(townBytes)!==payload.source_hashes.townships_geojson_sha256)throw Error('Township geometry does not match the footage ledger.');
      if(townData.metadata?.footage_manifest_sha256!==hash)throw Error('Townships belong to another survey snapshot.');
      if(version!==generation)return;
      const seen=new Set();for(const f of townData.features){if(!payload.townships[f.id]||seen.has(f.id))throw Error('Township ledger identifiers do not match the map.');seen.add(f.id)}if(seen.size!==Object.keys(payload.townships).length)throw Error('Incomplete township map.');
      try{assertRatesFit(rates,payload)}catch{rates={...DEFAULT_SCENARIOS};for(const name of ['low','base','high'])$('footageRate-'+name).value=rates[name];try{localStorage.removeItem('bakken-footage-scenarios-v1')}catch{}$('footageError').textContent='Saved densities exceed the supported numeric range. Comparison defaults restored.'}
      data=payload;maps=checked;scaleCache.clear();
      const features=townData.features.filter(f=>payload.townships[f.id].eligible&&payload.townships[f.id].eligible_acres>1/4046.8564224).map(f=>({...f,properties:{...f.properties,id:f.id,acres:payload.townships[f.id].full_acres,zone:{topFt:0,bottomFt:1}}}));
      towns=prepareDSUs({...townData,features},m);
      $('footageStatus').textContent=`Survey ${payload.survey.source_date||'snapshot'} · EPSG:5070 · ${fmt(towns.length)} townships with eligible DSU coverage. ${fmt(payload.coverage.unusable_wells)} wells lack usable lateral geometry; zero mapped footage does not prove no development.`;
      refreshDSU();drawTowns();legend();search();applyVisibility();
    }catch(e){if(version===generation){data=null;maps=null;loadFailed=true;townshipRequested=false;clearSelection();scaleCache.clear();clearTownMeshes();group.visible=false;refreshDSU();$('footageStatus').textContent=e.message+' Footage analysis requires its matching full survey snapshot.';$('footageLegend').textContent='Unavailable · existing well and historical DSU views remain available.';layersChanged()}}
    finally{if(pending===task){pending=null;layersChanged()}}})();pending=task;layersChanged();return task;
  }
  function applyVisibility(){
    const show=enabled(),showTown=townshipVisible();$('footageDetails').hidden=!show&&!showTown;$('townshipControls').hidden=layer!=='township'&&!showTown;$('footageSelection').hidden=layer!=='township'&&!showTown;group.visible=showTown&&!!data;
    if(!showTown){$('townshipInspect').checked=false;clearSelection()}
    if(show&&layer==='dsu')dsu.useFootageMetric(metric);
    layersChanged();
  }
  function refresh(){scaleCache.clear();refreshDSU();drawTowns();legend();applyVisibility()}
  function setTownshipVisible(value){townshipRequested=!!value;if(value){loadFailed=false;$('footageEnabled').checked=true;layer='township';$('footageLayer').value=layer}applyVisibility();legend();if(value)return ensure()}
  $('footageEnabled').onchange=()=>{if(!enabled())townshipRequested=false;else{loadFailed=false;if(layer==='township')townshipRequested=true;else dsu.setVisible(true)}applyVisibility();if(enabled())ensure();else dsu.useFootageMetric(null)};
  $('footageLayer').onchange=e=>{layer=e.target.value;if(enabled()){if(layer==='township')townshipRequested=true;else dsu.setVisible(true)}loadFailed=false;refresh();if(enabled())ensure()};
  $('footageMetric').onchange=e=>{metric=e.target.value;refresh()};
  $('footageScenario').onchange=e=>{scenario=e.target.value;refresh()};
  $('footageApply').onclick=()=>{try{const candidate=assertRatesFit(validateScenarios(Object.fromEntries(['low','base','high'].map(name=>{const v=$('footageRate-'+name).value;if(!v.trim())throw Error('Enter every capacity density. Blank is not zero.');return [name,Number(v)]}))));rates=candidate;try{localStorage.setItem('bakken-footage-scenarios-v1',JSON.stringify(rates))}catch{}$('footageError').textContent='';refresh()}catch(e){$('footageError').textContent=e.message}};
  $('footageReset').onclick=()=>{rates={...DEFAULT_SCENARIOS};try{localStorage.removeItem('bakken-footage-scenarios-v1')}catch{}for(const name of ['low','base','high'])$('footageRate-'+name).value=rates[name];$('footageError').textContent='';refresh()};
  $('townshipSearch').oninput=search;
  const params=new URLSearchParams(location.search);if(['dsu','township'].includes(params.get('inventory'))){layer=params.get('inventory');$('footageEnabled').checked=true;$('footageLayer').value=layer;if(layer==='township')townshipRequested=true;else dsu.setVisible(true);if(['low','base','high'].includes(params.get('scenario'))){scenario=params.get('scenario');$('footageScenario').value=scenario}applyVisibility()}
  layersChanged();
  return {
    // Compatibility only: responsive layout never changes layer state.
    setMobileLayers(){},
    setTownshipVisible,selection:townSelection,clearSelection,zoomSelection(){if(selectedTown&&group.visible)zoomTown(selectedTown)},
    townshipVisible,
    visibleBounds(){if(!group.visible||!towns.length)return null;const bounds=[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];for(const unit of towns){const next=townBounds(unit);for(let axis=0;axis<3;axis++){bounds[axis]=Math.min(bounds[axis],next[axis]);bounds[axis+3]=Math.max(bounds[axis+3],next[axis+3])}}return bounds},
    setDataset(m,bytes=null){generation++;manifest=m;data=maps=null;pending=null;loadFailed=false;towns=[];clearSelection();scaleCache.clear();clearTownMeshes();group.visible=false;$('footageSelection').replaceChildren();$('townshipResults').replaceChildren();refreshDSU();expectedHash=bytes&&crypto.subtle?digest(bytes):Promise.resolve(null);if((enabled()||townshipRequested)&&m)ensure();layersChanged()},
    activateDSU(key){if(!key){if(layer==='dsu'){if(townshipRequested){layer='township';$('footageLayer').value=layer}else $('footageEnabled').checked=false;applyVisibility()}return}$('footageEnabled').checked=true;layer='dsu';metric=key;$('footageLayer').value=layer;$('footageMetric').value=metric;applyVisibility();ensure();legend()},
    pick(event,camera,rect){if(!group.visible||!mesh||!$('townshipInspect').checked||dsu.inspecting())return false;group.updateWorldMatrix(true,true);camera.updateMatrixWorld();raycaster.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);const hit=raycaster.intersectObject(mesh,false)[0];if(!hit)return false;selectTown(towns[batch.owners[hit.faceIndex]]);say('Township selected. Metrics include only eligible DSU-covered land and all surveyed operators.');return true}
  };
}
