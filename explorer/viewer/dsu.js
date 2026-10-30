import * as THREE from 'three';
import {prepareDSUs,buildDSUPrisms,dsuScale,dsuColor,dsuValue,zoneInterval,dsuDisplayInterval,DSU_PALETTES,DSU_ACREAGE_COLORS} from './dsu-model.js';
import {attachDSUOrders,attachDSUHeadroom,ordersPanel,orderSearchText,rollupTable,headroomTotals,ROLLUP_FIELDS} from './dsu-orders.js';

const $=id=>document.getElementById(id),fmt=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:0});
const MODE_LABELS={acres:'Published spacing acres',orderWells:'Wells allowed · NDIC orders',headroom:'Remaining permitted wells',remaining:'Remaining wells · saved model',development:'Development · saved model',confidence:'Confidence · saved model',type:'Spacing-unit type'};
const METHODS={local_paired_tops:'Nearby paired Lodgepole and Birdbear tops',local_separate_tops:'Separate nearby Lodgepole and Birdbear controls',lodgepole_plus_800ft:'Nearby Lodgepole top + assumed 800 ft thickness',lateral_minus800_plus200:'Nearest lateral depths −800 / +200 ft',regional_9000_10000:'Regional 9,000–10,000 ft display fallback'};
const metricFmt=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:1});
export function createDSUController(root,{focus,say,selectionChanged=()=>{},footageRequested=()=>{}}){
  const group=new THREE.Group();group.name='Approximate DSU zones';group.visible=false;root.add(group);
  const raycaster=new THREE.Raycaster();let manifest=null,units=[],displayed=[],metadata=null,mesh=null,pickMesh=null,edges=null,batch=null,highlight=null,selected=null,generation=0,openRequest=0,loading=null,loaded=false;
  let topOffset=0,bottomOffset=0,mode='acreage',opacity=.09,filter='all',layout='nested',depthStep=0;
  let footageAnalysis=null,colorRange=[0,100],ordersMeta=null,orderDocuments=null,headroomMeta=null;
  const footageMode=()=>mode.startsWith('footage-');
  const colorForUnit=unit=>footageMode()?new THREE.Color(footageAnalysis?.color(unit,mode.slice(8))||'#6b7280'):dsuColor(unit,mode,colorRange);
  const dispose=o=>{o.geometry?.dispose();o.material?.dispose();o.removeFromParent()};
  function clear(notify=true){for(const o of [...group.children])dispose(o);mesh=pickMesh=edges=highlight=null;batch=null;selected=null;displayed=[];$('dsuSelection').replaceChildren();$('dsuOverlaps').replaceChildren();if(notify)selectionChanged(null)}
  function clearSelection(){if(highlight){dispose(highlight);highlight=null}selected=null;$('dsuSelection').replaceChildren();$('dsuOverlaps').replaceChildren();selectionChanged(null)}
  function filtered(){return units.filter(u=>filter==='all'||filter===u.properties.spacingType||(filter==='modeled'&&dsuValue(u,'remaining')!==null)||(filter==='ordered'&&dsuValue(u,'orderWells')!==null)||(filter==='room'&&dsuValue(u,'headroom')>0)||(filter.startsWith('group:')&&inGroup(u))||(filter==='selected'&&u===selected)||(filter.startsWith('acres-')&&u.properties.acres===+filter.slice(6)))}
  // filter 'group:<by>:<name>' keeps units whose headroom record falls in that rollup row.
  function inGroup(u){const [,by,...name]=filter.split(':');return u.headroom!=null&&(u.headroom[ROLLUP_FIELDS[by]]||'Unknown')===name.join(':')}
  function rollups(){
    $('dsuHeadroomTotals').textContent=headroomMeta?headroomTotals(headroomMeta):'Build dsu-headroom.json with prepare_dsu_headroom.py to see statewide totals.';
    const by=$('dsuRollupBy').value||'county',[,activeBy,...name]=filter.startsWith('group:')?filter.split(':'):[];
    $('dsuRollupTable').replaceChildren(headroomMeta?rollupTable(headroomMeta,by,{active:activeBy===by?name.join(':'):null,choose:value=>{
      const next=`group:${by}:${value}`;filter=filter===next?'all':next;$('dsuFilter').value=filter.startsWith('group:')?'all':filter;render();results();rollups();
      say(filter==='all'?'Showing all DSUs.':`Showing units in ${value}. Click the row again to show all.`)}}):'');
  }
  function bounds(unit){const b=unit.bounds.slice(),{top,bottom}=dsuDisplayInterval(unit,{topOffset,bottomOffset,layout,depthStep});b[1]=-bottom;b[4]=-top;return b}
  const faceOpacity=()=>Math.min(.65,opacity*(layout==='nested'?1.7:1));
  const edgeOpacity=()=>Math.min(.9,.35+opacity*2);
  function legend(){
    if(footageMode()){
      $('dsuAcreageLegend').hidden=true;$('dsuColorbar').hidden=false;
      $('dsuColorbar').style.background=footageAnalysis?.gradient||'linear-gradient(90deg,#30123b,#4685fa,#1ae4b6,#a4fc3b,#f9ba38,#e3440a,#7a0403)';
      $('dsuLegend').textContent=footageAnalysis?.legend(mode.slice(8))||'Footage analysis is loading or unavailable · gray = unavailable';
      $('dsuModelNote').hidden=false;$('dsuModelNote').textContent='Footage scenarios use all surveyed operators and original footprints. Mapped lateral feet are a drilling proxy; completion and target assignments are unverified. September results remain in the saved-model color options.';return;
    }
    const range=dsuScale(units,mode),bar=$('dsuColorbar');bar.hidden=mode==='acreage';bar.style.background=mode==='type'?'linear-gradient(90deg,#70c5e8 50%,#cda3ff 50%)':`linear-gradient(90deg,${(DSU_PALETTES[mode]||DSU_PALETTES.acres).join(',')})`;
    $('dsuAcreageLegend').hidden=mode!=='acreage';$('dsuAcreageLegend').replaceChildren();
    if(mode==='acreage')for(const [acres,color] of Object.entries(DSU_ACREAGE_COLORS)){const item=document.createElement('span'),swatch=document.createElement('i');swatch.style.background=color;const label=document.createElement('b');label.textContent=fmt(acres)+' ac';item.append(swatch,label);$('dsuAcreageLegend').append(item)}
    $('dsuLegend').textContent=mode==='acreage'?'Fixed published acreage classes · gray = other sizes':mode==='type'?'Blue: spacing (SPC) · Purple: drilling (DRL)':`${fmt(range[0])} — ${fmt(range[1])}${mode==='acres'?' acres · upper colors capped at 98th percentile':mode==='remaining'?' modeled wells':mode==='confidence'?' score / 100':' %'}`;
    $('dsuModelNote').hidden=['acres','acreage','type'].includes(mode);
    if(mode==='headroom'){$('dsuLegend').textContent='Red: more wells than allowed · gray: at allowance · green: room for 1–10+ more wells · neutral gray = no single linked allowance';$('dsuModelNote').textContent=headroomMeta?headroomTotals(headroomMeta).replace(/ Click a row.*$/,'')+' Allowances are machine-extracted and not human-reviewed.':'Remaining-well file is not installed. Build dsu-headroom.json with prepare_dsu_headroom.py.';return}
    if(mode==='orderWells'){$('dsuLegend').textContent=`${fmt(range[0])} — ${fmt(range[1])}+ wells allowed by the latest linked order · gray = no linked allowance`;$('dsuModelNote').textContent=ordersMeta?`${fmt(ordersMeta.summary?.dsusWithAllowance??0)} DSUs have a stated allowance from ${fmt(ordersMeta.summary?.footprints??0)} processed order footprints${ordersMeta.atlas?.built?' · atlas '+ordersMeta.atlas.built.slice(0,10):''}. Machine-extracted and not human-reviewed; gray units may be governed by orders not yet processed.`:'Order links are not installed. Build dsu-orders.json with prepare_dsu_orders.py.';return}
    if(metadata?.inventoryScenario){const inv=metadata.inventoryScenario;$('dsuModelNote').textContent=`Legacy model · methodology under review. Scenario ${inv.asOf||'2026-09-12'} · GIS ${inv.sourceGISDate||'2026-09-07'}. ${fmt(inv.counts?.available??0)} matched records have estimates. Gray = unmatched, under review, or unavailable. These are not current validated drillable-location counts.`}
    else $('dsuModelNote').textContent='No saved inventory model is included with this DSU file. Gray means unavailable.';
  }
  function status(){if(loaded){$('dsuStatus').textContent=`${fmt(displayed.length)} of ${fmt(units.length)} DSU records · DMR ${metadata?.retrievedAtUTC?.slice(0,10)||''}. Overlapping units remain separate.${ordersMeta?` ${fmt(ordersMeta.linked)} linked to NDIC orders.`:''}`;$('dsuOverlapNote').textContent=layout==='source'?'Source footprints · no inward or depth separation offsets.':`Nested display: 1,280 ac → 100 ft inset; 1,920 → 220 ft; 2,560 → 340 ft; 3,840 → 460 ft. Bands are 50 ft wide. ${depthStep?'Exploded view: larger acreage classes are lifted '+fmt(depthStep)+' ft per level. ':'Depth separation is off. '}Display offsets are not setbacks or legal boundaries and do not change acreage or inventory.${units.some(u=>!u.nested)?' Units without prepared bands use source outlines.':''}${units.some(u=>u.nested?.fallback)?' Narrow footprints use their original unfilled outline.':''}`;$('dsuDepthSeparation').disabled=layout==='source'}}
  function render(){
    if(!loaded)return;
    const previous=selected,next=filtered();clear(false);displayed=next;colorRange=dsuScale(units,mode);
    batch=buildDSUPrisms(displayed,{topOffset,bottomOffset,mode,range:dsuScale(units,mode),layout,depthStep,colorForUnit});
    mesh=new THREE.Mesh(batch.geometry,new THREE.MeshBasicMaterial({vertexColors:true,transparent:true,opacity:faceOpacity(),side:THREE.DoubleSide,depthWrite:false}));mesh.renderOrder=-8;group.add(mesh);
    pickMesh=mesh;if(batch.pickGeometry!==batch.geometry){pickMesh=new THREE.Mesh(batch.pickGeometry,new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));pickMesh.visible=false;group.add(pickMesh)}
    edges=new THREE.LineSegments(batch.edgeGeometry,new THREE.LineBasicMaterial({vertexColors:true,transparent:true,opacity:edgeOpacity(),depthWrite:false}));edges.renderOrder=-7;group.add(edges);
    if(previous&&displayed.includes(previous))select(previous,false);else selectionChanged(null);legend();status();
  }
  function recolor(){
    if(!batch)return;
    const range=dsuScale(units,mode),colors=mesh.geometry.attributes.color,edgeColors=edges.geometry.attributes.color;colorRange=range;
    displayed.forEach((unit,i)=>{const c=colorForUnit(unit),r=batch.ranges[i];for(let v=r.start;v<r.end;v++)colors.setXYZ(v,c.r,c.g,c.b);for(let v=r.edgeStart;v<r.edgeEnd;v++)edgeColors.setXYZ(v,c.r,c.g,c.b)});
    colors.needsUpdate=true;edgeColors.needsUpdate=true;legend();
  }
  function select(unit,interactive=true){
    selected=unit;if(highlight){dispose(highlight);highlight=null}
    const index=displayed.indexOf(unit);if(index<0)return;
    const r=batch.ranges[index],vertices=edges.geometry.attributes.position.array.slice(r.edgeStart*3,r.edgeEnd*3),g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(vertices,3));
    highlight=new THREE.LineSegments(g,new THREE.LineBasicMaterial({color:'#ffffff',transparent:true,opacity:.95,depthTest:false}));highlight.renderOrder=4;group.add(highlight);
    const host=$('dsuSelection');host.replaceChildren();const tag=document.createElement('div');tag.className='eyebrow';tag.textContent='SELECTED DSU';const title=document.createElement('h3');title.textContent=unit.properties.label;
    const zoom=document.createElement('button');zoom.className='primary';zoom.textContent='Zoom to DSU';zoom.onclick=()=>focus(bounds(unit));
    const isolate=document.createElement('button');isolate.textContent=filter==='selected'?'Show all DSUs':'Show only this DSU';isolate.onclick=()=>{filter=filter==='selected'?'all':'selected';$('dsuFilter').value=filter;render();results()};
    const p=unit.properties,[top,bottom]=zoneInterval(p.zone,topOffset,bottomOffset),dl=document.createElement('dl');
    for(const [label,value] of [['Published acres',fmt(p.acres)],['Type',p.spacingType||'Unavailable'],['Case',p.caseNo??'Not supplied'],['Order',p.orderNo??'Not supplied'],['Display upper TVD',fmt(top)+' ft'],['Display lower TVD',fmt(bottom)+' ft']]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;dl.append(dt,dd)}
    const displayNote=document.createElement('p');displayNote.className='caption';const lift=dsuDisplayInterval(unit,{topOffset,bottomOffset,layout,depthStep}).lift;displayNote.textContent=layout==='nested'?`Display inset: ${fmt(p.display?.insetFt||0)} ft${p.display?.fallback?' · original outline fallback':''}. ${lift?'Exploded view lift: '+fmt(lift)+' ft above the interval listed; source depths unchanged.':'No depth separation.'}`:'Source footprint; no inset or depth separation.';
    const zone=p.zone,note=document.createElement('p');note.className='caption';note.textContent=`Approximate zone. ${METHODS[zone?.method]||zone?.method||'Regional display fallback'}. Birdbear top is a proxy for the Three Forks base. ${zone?.sourceDate?'Controls: '+zone.sourceDate+'. ':''}${Number.isFinite(zone?.nearestKm)?`${zone.nSamples} control${zone.nSamples===1?'':'s'} · ${metricFmt(zone.nearestKm)}–${metricFmt(zone.furthestKm)} km away. `:''}Depths are provisional TVD below each well’s reference; elevations are not applied. Published orders control the legal interval.`;
    host.append(tag,title,zoom,isolate,dl,ordersPanel(unit,{documentUrl:orderDocuments,meta:ordersMeta}),displayNote,note);
    if(!footageMode()&&!['acres','acreage','type','orderWells','headroom'].includes(mode)){const metric=document.createElement('p');metric.className='caption';const v=dsuValue(unit,mode);metric.textContent=`${MODE_LABELS[mode]}: ${v===null?'unavailable / review':metricFmt(v)+(mode==='remaining'?'':mode==='confidence'?' / 100':'%')}. Scenario: 2026-09-12.`;host.append(metric)}
    if(footageAnalysis)host.append(footageAnalysis.panel(unit));
    const id=document.createElement('small');id.className='caption';id.textContent='Record '+p.sourceRecord+' · '+unit.id;host.append(id);
    selectionChanged(unit,{interactive});
  }
  function results(){
    const host=$('dsuResults');host.replaceChildren();const query=$('dsuSearch').value.trim().toLowerCase();if(!query||!loaded)return;
    const matches=displayed.filter(u=>{const p=u.properties;return `${p.caseNo??''} ${p.orderNo??''} ${p.referenceCode??''} ${p.label} ${p.id} ${orderSearchText(u)}`.toLowerCase().includes(query)});
    const count=document.createElement('p');count.className='caption';count.textContent=`${fmt(matches.length)} matches${matches.length>20?' · first 20 shown':''}`;host.append(count);
    for(const unit of matches.slice(0,20)){const b=document.createElement('button');b.textContent=`${unit.properties.label} · Case ${unit.properties.caseNo??'—'} · Order ${unit.properties.orderNo??'—'} · #${unit.properties.sourceRecord}`;b.onclick=()=>{select(unit);focus(bounds(unit))};host.append(b)}
  }
  async function ensureLoaded(){
    if(loaded||!manifest)return;
    if(loading)return loading;
    const version=generation,m=manifest;$('dsuStatus').textContent='Loading published DSU footprints and approximate depth intervals…';
    const pending=(async()=>{try{
      const r=await fetch(new URL('./data/dsu/drilling-spacing-units.geojson',import.meta.url));if(!r.ok)throw Error('DSU file not installed. Prepare the public DMR DSU ZIP with the included importer.');const data=await r.json();if(version!==generation)return;
      const prepared=prepareDSUs(data,m);if(version!==generation)return;
      // Order links are optional; a missing or stale file must not block the DSU layer.
      let orders=null,documents=null,headroom=null;
      try{const o=await fetch(new URL('./data/dsu/dsu-orders.json',import.meta.url));if(o.ok)orders=attachDSUOrders(prepared,await o.json())}catch(e){say(e.message)}
      if(orders)try{const h=await fetch(new URL('./data/dsu/dsu-headroom.json',import.meta.url));if(h.ok)headroom=attachDSUHeadroom(prepared,await h.json())}catch(e){say(e.message)}
      try{const s=await fetch('/api/orders/status');if(s.ok&&(await s.json()).available)documents=id=>'/api/orders/document?id='+encodeURIComponent(id)}catch{}
      if(version!==generation)return;units=prepared;metadata=data.metadata;ordersMeta=orders;orderDocuments=documents;headroomMeta=headroom;loaded=true;render();rollups();
    }catch(e){if(version===generation){$('dsuStatus').textContent=e.message;$('dsuEnabled').checked=false;group.visible=false;$('dsuDetails').hidden=true;document.dispatchEvent(new CustomEvent('viewer:layers-changed'))}}
    finally{if(loading===pending)loading=null}})();loading=pending;return pending;
  }
  async function setVisible(value){if(!value)openRequest++;$('dsuEnabled').checked=value;group.visible=value;$('dsuDetails').hidden=!value;document.dispatchEvent(new CustomEvent('viewer:layers-changed'));if(!value){$('dsuInspect').checked=false;clearSelection();return}await ensureLoaded()}
  $('dsuEnabled').onchange=e=>setVisible(e.target.checked);
  $('dsuColor').onchange=e=>{mode=e.target.value;footageRequested(footageMode()?mode.slice(8):null);recolor();if(selected)select(selected,false)};
  $('dsuFilter').onchange=e=>{filter=e.target.value;render();results();rollups()};
  $('dsuRollupBy').onchange=()=>rollups();
  $('dsuOpacity').oninput=e=>{opacity=+e.target.value/100;$('dsuOpacityValue').textContent=e.target.value+'%';if(mesh)mesh.material.opacity=faceOpacity();if(edges)edges.material.opacity=edgeOpacity()};
  $('dsuLayout').onchange=e=>{layout=e.target.value;$('dsuDepthSeparationValue').textContent=layout==='source'?'Off (source view)':depthStep?depthStep+' ft / level':'Off';render()};
  $('dsuDepthSeparation').onchange=e=>{depthStep=+e.target.value;$('dsuDepthSeparationValue').textContent=depthStep?depthStep+' ft / level':'Off';render()};
  $('dsuApplyDepth').onclick=()=>{
    const top=Number($('dsuTopOffset').value),bottom=Number($('dsuBottomOffset').value);try{if(!$('dsuTopOffset').value.trim()||!$('dsuBottomOffset').value.trim()||!Number.isFinite(top)||!Number.isFinite(bottom))throw Error('Enter both offsets in feet.');for(const unit of units)zoneInterval(unit.properties.zone,top,bottom);topOffset=top;bottomOffset=bottom;$('dsuDepthError').textContent='';render()}catch(e){$('dsuDepthError').textContent=e.message}
  };
  $('dsuResetDepth').onclick=()=>{$('dsuTopOffset').value=$('dsuBottomOffset').value='0';topOffset=bottomOffset=0;$('dsuDepthError').textContent='';render()};
  $('dsuSearch').oninput=results;
  return {
    setVisible,
    setFootageAnalysis(value){footageAnalysis=value;recolor();if(selected)select(selected,false)},
    useFootageMetric(metric){if(!metric&&!footageMode())return;mode=metric?'footage-'+metric:'acreage';$('dsuColor').value=mode;recolor();if(selected)select(selected,false)},
    selection(){return selected},
    zoomSelection(){if(selected)focus(bounds(selected))},
    visibleBounds(){if(!group.visible||!displayed.length)return null;const result=[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];for(const unit of displayed){const b=bounds(unit);for(let i=0;i<3;i++){result[i]=Math.min(result[i],b[i]);result[i+3]=Math.max(result[i+3],b[i+3])}}return result},
    clearSelection,
    async openUnit(id,zoom=true){const version=generation,request=++openRequest;await setVisible(true);if(version!==generation||request!==openRequest||!group.visible)return false;const unit=units.find(u=>u.id===id);if(!unit){say('This spacing unit is not in the installed DSU snapshot.');return false}select(unit);if(zoom)focus(bounds(unit));return true},
    setDataset(m){generation++;manifest=m;loading=null;loaded=false;units=[];metadata=null;clear();if(filter==='selected'){filter='all';$('dsuFilter').value='all'}$('dsuResults').replaceChildren();$('dsuSearch').value='';$('dsuStatus').textContent='Published footprints with approximate formation-depth boxes.';if(group.visible)ensureLoaded()},
    inspecting(){return group.visible&&loaded&&$('dsuInspect').checked},
    pick(event,camera,rect){
      if(!this.inspecting()||!pickMesh)return false;
      group.updateWorldMatrix(true,true);camera.updateMatrixWorld();raycaster.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);
      const seen=new Set(),hits=[];for(const hit of raycaster.intersectObject(pickMesh,false)){const unit=displayed[batch.pickOwners[hit.faceIndex]];if(unit&&!seen.has(unit.id)){seen.add(unit.id);hits.push(unit)}}
      $('dsuOverlaps').replaceChildren();if(!hits.length){say('No spacing unit at this point. Choose Wells in Select on map to select well paths.');return true}
      select(hits[0]);if(hits.length>1){const label=document.createElement('label');label.className='field';label.textContent=`${hits.length} overlapping DSUs · choose record`;const chooser=document.createElement('select');chooser.setAttribute('aria-label','Overlapping DSU records');hits.forEach((u,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`#${u.properties.sourceRecord} · ${u.properties.acres} ac · Case ${u.properties.caseNo??'—'} · Order ${u.properties.orderNo??'—'}`;chooser.append(o)});chooser.onchange=()=>select(hits[+chooser.value]);$('dsuOverlaps').append(label,chooser)}
      say('Spacing unit selected. Use Zoom to selection or open its details in the panel.');return true;
    }
  };
}
