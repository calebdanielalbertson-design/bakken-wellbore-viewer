import * as THREE from 'three';
import {createOperatorModel} from './operator-model.js';

export const METRICS={
  section:{label:'Well section'},
  operator:{label:'Operator',categorical:true},
  dls:{label:'Dogleg severity (DLS)',field:3,unit:'°/100 ft',min:0,max:15,note:'Change in survey direction per 100 ft of measured depth. Overview colors retain the largest interval DLS within each displayed segment.'},
  curvature:{label:'Curvature',field:3,factor:Math.PI/18,unit:'rad/1,000 ft',min:0,max:Math.PI*5/6,note:'Survey-course curvature. This is DLS expressed in radians per 1,000 ft, so the two modes describe the same directional change.'},
  tortuosity:{label:'Local tortuosity',field:6,unit:'path/chord ratio',min:1,max:1.15,note:'3D path length ÷ straight-line distance in a centered 1,000 ft MD window. Straight = 1. Planned curves also increase this ratio. End windows shorten; at least 500 ft and three distinct points are required. Overview retains the highest ratio.'},
  inclination:{label:'Inclination',field:1,unit:'° from vertical',min:0,max:90,note:'Measured survey inclination: 0° is downward vertical, 90° is horizontal. Values above the scale maximum use its highest color.'},
  azimuth:{label:'Azimuth',field:2,unit:'°',min:0,max:360,cyclic:true,note:'Survey azimuth with a cyclic scale: 0° and 360° share a color. Hidden below 5° inclination. The source azimuth reference is retained; no magnetic/grid correction is applied.'},
  build:{label:'Build / drop rate',field:4,unit:'°/100 ft',min:-10,max:10,signed:true,note:'Inclination change per 100 ft MD. Positive builds toward horizontal; negative drops toward vertical. Overview retains the signed rate with the largest absolute value.'},
  turn:{label:'Turn rate',field:5,unit:'°/100 ft',min:-10,max:10,signed:true,note:'Shortest signed azimuth change per 100 ft MD. Positive is increasing azimuth. Missing when either station is below 5° inclination. Overview retains the signed rate with the largest absolute value.'},
  tvd:{label:'True vertical depth',unit:'ft',min:0,max:15000,geometry:true,note:'Relative TVD below each well’s reference, before display exaggeration. It is not subsea elevation or a shared elevation datum.'},
  md:{label:'Measured depth',field:0,unit:'ft',min:0,max:25000,note:'Source measured depth along the survey. Overview uses the ending station’s value.'},
  departure:{label:'Horizontal departure',field:7,unit:'ft',min:0,max:12000,note:'Horizontal distance from this branch’s first available station. That station may be below the surface; this is not necessarily surface-hole departure.'}
};
const SECTION=['#65b9ff','#b79cff','#ffd84d','#ff665e','#a3ff12','#9fadb8'];
const palettes={viridis:['#440154','#3b528b','#21918c','#5ec962','#fde725'],thermal:['#6588ff','#45c4dc','#fff3a1','#ffad52','#ff5269'],signed:['#3478df','#f3f1e6','#e56b36']};
const linear=v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4;
const srgb=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255);
export function scaleRGB(t,palette='viridis'){
  t=Math.max(0,Math.min(1,t));
  if(palette==='cyclic'){
    const h=((t*6)%6+6)%6,c=.8,x=c*(1-Math.abs(h%2-1)),m=.12;
    return (h<1?[c,x,0]:h<2?[x,c,0]:h<3?[0,c,x]:h<4?[0,x,c]:h<5?[x,0,c]:[c,0,x]).map(v=>Math.min(1,v+m));}
  const colors=palettes[palette]||palettes.viridis,x=t*(colors.length-1),i=Math.min(colors.length-2,Math.floor(x)),f=x-i,a=srgb(colors[i]),b=srgb(colors[i+1]);return a.map((v,k)=>v+(b[k]-v)*f);
}
export function metricValue(mode,data,index,geometry){
  const spec=METRICS[mode];if(!spec||mode==='section'||spec.categorical)return NaN;
  if(mode==='tvd')return geometry?Math.abs(geometry[index*4+1]):NaN;
  const v=data?.[index*8+spec.field];return Number.isFinite(v)?v*(spec.factor||1):NaN;
}
const fmt=(n,d=2)=>Number(n).toLocaleString('en-US',{maximumFractionDigits:d});
const $=id=>document.getElementById(id);
const SECTION_NAMES=['Vertical','Directional','Curve','Drillback','Lateral','Unknown'];
export function automaticSectionBounds(mode,stats){
  const s=METRICS[mode],factor=s.factor||1;
  if(s.categorical||!stats?.count)return null;
  if(s.cyclic)return [0,360];
  if(s.signed){const limit=Math.max(stats.absP98*factor,0.001);return [-limit,limit]}
  let low=stats.p02*factor,high=stats.p98*factor;
  if(!Number.isFinite(low)||!Number.isFinite(high))return null;
  if(high-low<Math.max(1e-6,Math.abs(low)*1e-6)){const pad=Math.max(Math.abs(low)*0.01,mode==='tortuosity'?.001:.01);low=Math.max(s.min??0,low-pad);high+=pad}
  return [low,high];
}

export function createSurveyColors({changed,sectionColor=()=>null}={}){
  let mode='section',metadata=null,manifest=null,reader=null,overview=null,generation=0,selected=null,selectedData=null,overviewPromise=null;
  const tiles=new Map(),pending=new Map(),limits=new Map(),views=new Set();let ramp=[],palette='thermal';
  let operators=null,operatorRGB=[];
  let sectionStats=null,scope='shared',editSection=4,modeRequest=0,activeRanges=[];const sectionLimits=new Map();
  const sectionRGB=SECTION.map(h=>srgb(h).map(linear)),unknown=srgb('#80909d').map(linear);
  const spec=()=>METRICS[mode];
  const bySection=()=>scope==='section'&&!!sectionStats&&!spec().cyclic;
  function statsFor(section){return sectionStats?.sections.find(s=>s.id===section)?.metrics[mode==='curvature'?'dls':mode]}
  function bounds(section=editSection){
    if(bySection())return sectionLimits.get(mode+':'+section)||automaticSectionBounds(mode,statsFor(section));
    const s=spec(),max=limits.get(mode)??s.max;return[s.signed?-max:s.min,max];
  }
  function makeRamp(){const s=spec();if(s.categorical){ramp=[];activeRanges=[];return}const key=s.cyclic?'cyclic':s.signed?'signed':palette;ramp=Array.from({length:1025},(_,i)=>scaleRGB(i/1024,key).map(linear));activeRanges=SECTION_NAMES.map((_,i)=>bounds(i));}
  function rgb(value,section,branchId=null,row=null,tile=null){if(mode==='section')return sectionColor(section,branchId,row,tile)||sectionRGB[section]||unknown;if(mode==='operator')return operatorRGB[operators?.forBranch(branchId)?.id]||unknown;if(!Number.isFinite(value))return unknown;const range=activeRanges[section];if(!range)return unknown;const [lo,hi]=range,t=spec().cyclic?((value%360)+360)%360/360:Math.max(0,Math.min(1,(value-lo)/(hi-lo)));return ramp[Math.round(t*1024)]}
  function legend(){
    const s=spec();$('surveyColorMode').value=mode;$('surveyColorDetails').hidden=mode==='section'||!!s.categorical;$('surveyColorNote').textContent=s.note||'';
    $('operatorControls').hidden=!operators;
    const operatorKey=$('operatorLegend').closest('details');if(operatorKey)operatorKey.hidden=mode!=='operator';
    if(mode==='section'||s.categorical)return;
    const range=bounds(),[lo,hi]=range||[NaN,NaN],key=s.cyclic?'cyclic':s.signed?'signed':palette;
    $('surveyColorPalette').value=palette;
    $('surveyScaleScope').value=scope;$('surveyScaleScope').disabled=!sectionStats||!!s.cyclic;
    $('surveyScaleSectionField').hidden=!bySection();$('surveyScaleSection').value=String(editSection);
    $('surveyColorFloorField').hidden=!bySection()||!!s.signed;$('surveyColorFloor').value=Number.isFinite(lo)?Number(lo.toPrecision(7)):'';
    $('surveyColorFloor').disabled=!range;$('surveyColorCeiling').disabled=!!s.cyclic||!range;
    $('surveyScaleScopeNote').textContent=s.cyclic?'Azimuth keeps its fixed compass scale so north has the same color everywhere.':bySection()?'Each section has its own range, shared across every well. Automatic limits use the 2nd–98th percentiles (signed rates use ±98th percentile magnitude). Endpoint colors include values beyond the limits. Colors compare variation within a section; equal colors across sections can mean different values.':sectionStats?'One scale across all wells and sections.':'Section statistics unavailable; using one shared scale.';
    $('surveySectionLegends').hidden=!bySection();$('surveySectionLegends').replaceChildren();
    if(bySection())for(let i=0;i<SECTION_NAMES.length;i++){
      const r=bounds(i),row=document.createElement('div');row.className='survey-section-scale';
      const name=document.createElement('strong');name.textContent=SECTION_NAMES[i];
      const value=document.createElement('span');value.textContent=r?`${fmt(r[0],4)} – ${fmt(r[1],4)} ${s.unit}`:'No valid measurements';
      const note=document.createElement('small');note.textContent=r?(sectionLimits.has(mode+':'+i)?'Custom':'Automatic'):'Unavailable';row.append(name,value,note);$('surveySectionLegends').append(row);
    }
    $('surveyColorBar').style.background='linear-gradient(to right,'+Array.from({length:25},(_,i)=>`rgb(${scaleRGB(i/24,key).map(v=>Math.round(v*255)).join(',')}) ${i/24*100}%`).join(',')+')';
    $('surveyColorMin').textContent=bySection()?'Low':s.cyclic?'0° N':`${fmt(lo,mode==='tortuosity'?3:2)}`;
    $('surveyColorMax').textContent=bySection()?'High':s.cyclic?'360° N':`${fmt(hi,mode==='tortuosity'?3:2)}+`;
    $('surveyColorUnit').textContent=bySection()?'Range for each section below':s.cyclic?'90° E · 180° S · 270° W':s.unit;
    $('surveyColorCeiling').value=Number.isFinite(hi)?Number(hi.toPrecision(7)):'';$('surveyColorCeiling').min=bySection()?'':s.signed?'.0001':String((s.min||0)+.0001);
    $('surveyColorPalette').disabled=!!s.signed||!!s.cyclic;
    $('surveyColorScaleLabel').textContent=s.signed?'Symmetric scale limit (±)':bySection()?'Section maximum':'Scale maximum';
    $('surveyColorReset').textContent=bySection()?'Reset this section to automatic':'Reset scale';
    $('surveyColorApply').disabled=!!s.cyclic||!range;
  }
  function sourceFor(line){return line.userData.surveyColor?.overview?overview:tiles.get(line.userData.surveyColor?.tile)}
  function apply(line){
    const binding=line.userData.surveyColor;if(!binding)return;
    const attr=line.geometry.attributes.color,data=sourceFor(line),p=line.geometry.attributes.position.array;
    for(let i=0;i<binding.rows.length;i++){
      const value=mode==='tvd'?Math.abs(p[i*6+4]):metricValue(mode,data,binding.rows[i]);
      // Overview positions may have been collapsed by detail loading; retain original TVD.
      const actual=mode==='tvd'&&line.userData.original?Math.abs(line.userData.original[i*6+4]):value;
      const c=rgb(actual,line.userData.section,line.userData.ids?.[i],binding.rows[i],binding.overview?null:binding.tile);for(let k=0;k<6;k++)attr.array[i*6+k]=c[k%3];
    }
    attr.needsUpdate=true;line.userData.production?.colors&&(line.userData.production.colors.needsUpdate=true);
  }
  function refresh(){makeRamp();for(const line of views)apply(line);legend();selection(selected,selectedData);changed?.(mode)}
  function reset(){generation++;metadata=null;manifest=null;reader=null;overview=null;overviewPromise=null;operators=null;operatorRGB=[];$('operatorFilter').value='all';tiles.clear();pending.clear();selected=null;selectedData=null;mode='section';limits.clear();sectionLimits.clear();sectionStats=null;scope='shared';$('surveyColorMode').disabled=true;$('surveyColorStatus').textContent='Reading survey measurements…';legend()}
  async function load(read,survey){
    reset();manifest=survey;reader=read;const version=generation;
    try{const m=await read('metrics.json',true);if(version!==generation)return;if(m.version!==1||m.stride!==8||m.stations!==survey.stations||m.overviewSegments!==survey.overviewSegments||m.branchCount!==survey.wells.length||m.source?.sourceCRS!==survey.sourceCRS||JSON.stringify(m.source?.origin)!==JSON.stringify(survey.origin))throw Error('Measurement index does not match the survey.');metadata=m;$('surveyColorStatus').textContent='Survey measurements available · shared scales across wells';}
    catch(e){if(version===generation)$('surveyColorStatus').textContent='Survey measurements unavailable. Section and TVD colors remain available.'}
    if(version!==generation)return;
    try{const stats=await read('section-metric-scales.json',true);if(version!==generation)return;if(stats.version===1&&stats.stations===survey.stations&&stats.branchCount===survey.wells.length&&stats.overviewSegments===survey.overviewSegments&&stats.sourceCRS===survey.sourceCRS&&JSON.stringify(stats.origin)===JSON.stringify(survey.origin)&&Array.isArray(stats.sections)){sectionStats=stats;scope='section'}}catch(e){if(version!==generation)return;}
    try{const raw=await read('operators.json',true);if(version!==generation)return;operators=createOperatorModel(raw,survey);operatorRGB=operators.groups.map(g=>srgb(g.color).map(linear));$('operatorStatus').textContent=`DMR wells snapshot ${operators.provenance.sourceDate||''} · operator joined by permit and API`;}catch(e){if(version!==generation)return;$('operatorStatus').textContent='Operator metadata unavailable for this dataset.';}
    for(const option of $('surveyColorMode').options)option.disabled=option.value==='operator'?!operators:!metadata&&!['section','tvd'].includes(option.value);
    if(version===generation)$('surveyColorMode').disabled=false;
  }
  async function ensureOverview(){
    if(!metadata||overview)return overview;if(overviewPromise)return overviewPromise;
    const version=generation,get=reader;
    overviewPromise=(async()=>{const data=new Float32Array(await get('overview.metrics.bin'));if(version!==generation)return null;if(data.length!==manifest.overviewSegments*8)throw Error('Incomplete overview measurements.');overview=data;return data})();
    try{return await overviewPromise}finally{if(version===generation)overviewPromise=null}
  }
  async function ensureTile(tile){
    if(!metadata||tiles.has(tile))return tiles.get(tile);if(pending.has(tile))return pending.get(tile);
    const version=generation,get=reader,count=manifest.tiles.find(t=>t.id===tile)?.stations;
    const task=(async()=>{const data=new Float32Array(await get(tile+'.metrics.bin'));if(version!==generation)return null;if(data.length!==count*8)throw Error('Incomplete tile measurements: '+tile);tiles.set(tile,data);return data})();pending.set(tile,task);
    try{return await task}finally{if(version===generation)pending.delete(tile)}
  }
  async function setMode(next){
    if(!METRICS[next]||(next==='operator'?!operators:!metadata&&!['section','tvd'].includes(next)))return;mode=next;const version=generation,request=++modeRequest;refresh();
    if(mode==='operator'){$('surveyColorStatus').textContent=`Operator colors · DMR snapshot ${operators.provenance.sourceDate||''}`;return}
    if(mode==='section'||mode==='tvd'){$('surveyColorStatus').textContent=metadata?'Survey measurements available · shared scales across wells':'Survey measurements unavailable. Section and TVD colors remain available.';return}
    $('surveyColorStatus').textContent='Loading full-resolution measurements…';
    const needed=[...new Set([...views].map(l=>l.userData.surveyColor.tile).filter(Boolean))],results=await Promise.allSettled([ensureOverview(),...needed.map(ensureTile)]);
    if(version!==generation||request!==modeRequest)return;refresh();const failed=results.filter(r=>r.status==='rejected');$('surveyColorStatus').textContent=failed.length?'Some measurements unavailable; loaded measurements are shown.':'Full-resolution metrics · overview preserves rate peaks';
  }
  function decorate(line,rows,tile=null){
    line.userData.surveyColor={rows:Uint32Array.from(rows),tile,overview:tile===null};
    line.geometry.setAttribute('color',new THREE.BufferAttribute(new Float32Array(rows.length*6),3));line.material.vertexColors=true;line.material.color.set(0xffffff);line.material.needsUpdate=true;
    views.add(line);line.geometry.addEventListener('dispose',()=>views.delete(line));apply(line);
  }
  function stationRGB(section,tile,row,data,branchId=null){return rgb(metricValue(mode,tiles.get(tile),row,data),section,branchId,row,tile)}
  function selection(w,data){
    selected=w;selectedData=data;const host=$('wellSurveyMetric');if(!host)return;host.replaceChildren();host.hidden=!w||mode==='section';if(host.hidden)return;
    const h=document.createElement('h4');h.textContent=spec().label+' · selected branch';const p=document.createElement('p');p.className='caption';
    if(mode==='operator'){const group=operators?.forBranch(w.id);p.textContent=operators?.nameForBranch(w.id)||'Operator unavailable';host.append(h,p);const note=document.createElement('p');note.className='caption';note.textContent='Display group: '+(group?.label||'Unknown');host.append(note);return}
    let min=Infinity,max=-Infinity,n=0;
    for(let i=w.offset;i<w.offset+w.count;i++){const v=metricValue(mode,tiles.get(w.tile),i,data);if(Number.isFinite(v)){min=Math.min(min,v);max=Math.max(max,v);n++}}
    p.textContent=n?`${fmt(min,3)}–${fmt(max,3)} ${spec().unit} · ${fmt(n)} valid stations`:'No valid measurements available for this branch.';host.append(h,p);
    if(bySection()){const note=document.createElement('p');note.className='caption';note.textContent='Colors use the separate section ranges shown above; this range covers the whole selected branch.';host.append(note)}
    if(mode==='azimuth'){const note=document.createElement('p');note.className='caption';note.textContent='Numeric range may cross the 0°/360° wrap.';host.append(note)}
  }
  $('surveyColorMode').onchange=e=>setMode(e.target.value);
  $('surveyColorPalette').onchange=e=>{palette=e.target.value;refresh()};
  $('surveyScaleScope').onchange=e=>{scope=e.target.value==='section'&&sectionStats?'section':'shared';refresh()};
  $('surveyScaleSection').onchange=e=>{editSection=Number(e.target.value);legend()};
  function customSectionRange(){const hi=Number($('surveyColorCeiling').value),lo=spec().signed?-hi:Number($('surveyColorFloor').value);if($('surveyColorFloor').value!==''&&$('surveyColorCeiling').value!==''&&Number.isFinite(lo)&&Number.isFinite(hi)&&hi>lo){sectionLimits.set(mode+':'+editSection,[lo,hi]);$('surveyScaleError').textContent='';refresh()}else{$('surveyScaleError').textContent=spec().signed?'Enter a positive finite scale limit.':'Enter finite limits with maximum greater than minimum.'}}
  $('surveyColorFloor').onchange=customSectionRange;
  $('surveyColorCeiling').onchange=e=>{if(bySection()){customSectionRange();return}const v=Number(e.target.value),s=spec();if(Number.isFinite(v)&&v>(s.signed?0:s.min)){limits.set(mode,v);refresh()}else legend()};
  $('surveyColorApply').onclick=()=>$('surveyColorCeiling').onchange({target:$('surveyColorCeiling')});
  $('surveyColorReset').onclick=()=>{if(bySection())sectionLimits.delete(mode+':'+editSection);else limits.delete(mode);$('surveyScaleError').textContent='';refresh()};
  makeRamp();legend();
  return {load,reset,decorate,ensureTile,selection,stationRGB,refresh,setMode,operatorModel:()=>operators,mode:()=>mode,active:()=>mode!=='section',ready:()=>!!metadata,
    releaseTiles(keep){for(const key of tiles.keys())if(!keep.has(key))tiles.delete(key)},
    async tileReady(tile){if(mode==='section'||mode==='tvd'||mode==='operator')return;await ensureTile(tile);for(const l of views)if(l.userData.surveyColor.tile===tile)apply(l);selection(selected,selectedData)}
  };
}
