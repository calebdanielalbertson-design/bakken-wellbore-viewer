// Actual footage + DSU controller tests. Synthetic public geometry only.
// Run: node tests/footage-controller.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {webcrypto} from 'node:crypto';

const viewer=path.resolve('viewer'),url=name=>pathToFileURL(path.join(viewer,name)).href;
const THREE=await import(url('vendor/three.module.js'));
const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'bakken-footage-controller-'));
const moduleUrl=name=>pathToFileURL(path.join(temporary,name)).href;
try {
for(const [source,target,replacements] of [
  ['reference-plane.js','reference.mjs',[]],
  ['dsu-model.js','dsu-model.mjs',[['./reference-plane.js','reference.mjs']]],
  ['dsu.js','dsu.mjs',[['./dsu-model.js','dsu-model.mjs']]],
  ['footage-model.js','footage-model.mjs',[]],
  ['footage.js','footage.mjs',[['./dsu-model.js','dsu-model.mjs'],['./footage-model.js','footage-model.mjs']]]
]) {
  let text=(await fs.readFile(path.join(viewer,source),'utf8')).replace("from 'three'",`from '${url('vendor/three.module.js')}'`);
  for(const [from,to] of replacements)text=text.replace(`from '${from}'`,`from '${moduleUrl(to)}'`);
  await fs.writeFile(path.join(temporary,target),text);
}
const {createDSUController}=await import(moduleUrl('dsu.mjs'));
const {createFootageController}=await import(moduleUrl('footage.mjs'));
const {prepareDSUs,dsuValue}=await import(moduleUrl('dsu-model.mjs'));
const {scenarioMetrics}=await import(moduleUrl('footage-model.mjs'));
if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto,configurable:true});
globalThis.location={search:''};
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.style={};this.value='';this.checked=false;this.hidden=false;this._text='';this.attributes={};}
  get textContent(){return this._text+this.children.map(c=>typeof c==='string'?c:c.textContent).join('');}
  set textContent(value){this._text=String(value);this.children=[];}
  append(...items){this.children.push(...items);}
  prepend(...items){this.children.unshift(...items);}
  replaceChildren(...items){this.children=items;this._text='';}
  setAttribute(name,value){this.attributes[name]=String(value);}
}
const encode=value=>new TextEncoder().encode(JSON.stringify(value));
const digest=async value=>Buffer.from(await crypto.subtle.digest('SHA-256',value)).toString('hex');
const pause=()=>new Promise(resolve=>setTimeout(resolve,1));
async function settle(predicate,description){for(let i=0;i<300;i++){if(predicate())return;await pause();}assert.fail('Did not settle: '+description);}
const feature=(id,x,extra={})=>({type:'Feature',id,properties:{id,label:id,sourceRecord:1,acres:1280,spacingType:'SPC',zone:{topFt:9000,bottomFt:10000},inventory:{matched:true,eligible:true,underReview:false,remainingWells:7.3,developmentPercent:12.5,confidence:80},...extra},geometry:{type:'Polygon',coordinates:[[[x,47.99],[x+.01,47.99],[x+.01,48.01],[x,48.01],[x,47.99]]]}});
const supported=(id,acres,feet,extra={})=>({id,eligible:true,eligibility_status:'source_bakken_mask',eligible_acres:acres,mapped_lateral_ft:feet,observed_wells:feet===0?0:1,observed_lateral_branches:feet===0?0:1,...extra});
async function fixture(){
  const manifest={version:1,stations:4,sourceCRS:'NAD83',origin:[-103,48],sourceSnapshot:{date:'2026-10-17'},wells:[{id:0,permit:'100',api:'33053000010000'},{id:1,permit:'101',api:'33053000020000'}]};
  const manifestBytes=encode(manifest),hash=await digest(manifestBytes);
  const dsus={type:'FeatureCollection',metadata:{sourceCRS:'EPSG:4269',retrievedAtUTC:'2026-10-17'},features:[feature('dsu-a',-103.02),feature('dsu-b',-103.01),feature('dsu-empty',-103),feature('dsu-unknown',-102.99)]};
  const town=feature('twp-a',-103.02,{label:'T152N R96W'});
  const townData={type:'FeatureCollection',metadata:{sourceCRS:'EPSG:4269',footage_manifest_sha256:hash},features:[town]};
  const dsuBytes=encode(dsus),townBytes=encode(townData);
  const payload={version:1,survey:{manifest_sha256:hash,stations:4,branch_count:2,well_count:2,source_crs:'NAD83',origin:[-103,48],source_date:'2026-10-17'},source_hashes:{survey_manifest_sha256:hash,dsu_file_sha256:await digest(dsuBytes),townships_geojson_sha256:await digest(townBytes)},method:{area_crs:'EPSG:5070',footage_label:'Mapped classified lateral plan footage'},coverage:{usable_wells:2,unusable_wells:0},dsus:{'dsu-a':supported('dsu-a',1280,31680),'dsu-b':supported('dsu-b',1280,31680),'dsu-empty':supported('dsu-empty',1280,0),'dsu-unknown':{id:'dsu-unknown',eligible:false,eligibility_status:'formation_unavailable',eligible_acres:null,mapped_lateral_ft:null,observed_wells:null,observed_lateral_branches:null}},townships:{'twp-a':supported('twp-a',2000,40000,{full_acres:23040})}};
  return {manifest,manifestBytes,hash,dsus,dsuBytes,townData,townBytes,payload};
}
async function setup(input=null,{deferFootage=false,savedRates=null}={}){
  input??=await fixture();
  const storage=new Map(savedRates?[['bakken-footage-scenarios-v1',JSON.stringify(savedRates)]]:[]);
  globalThis.localStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)};
  const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  globalThis.document={getElementById:$,createElement:tag=>new Element(tag),addEventListener(){},dispatchEvent(){return true}};
  for(const [id,value] of Object.entries({footageLayer:'dsu',footageMetric:'developmentPct',footageScenario:'base','footageRate-low':'49.5','footageRate-base':'66','footageRate-high':'82.5',dsuColor:'acreage',dsuFilter:'all',dsuSearch:'',dsuTopOffset:'0',dsuBottomOffset:'0',townshipSearch:''}))$(id).value=value;
  $('townshipInspect').checked=true;
  let release;const wait=deferFootage?new Promise(resolve=>release=resolve):null;
  const fetched=[];
  globalThis.fetch=async request=>{
    const requestPath=new URL(String(request)).pathname;fetched.push(requestPath);
    if(requestPath.endsWith('/footage.json')&&wait)await wait;
    const bytes=requestPath.endsWith('/footage.json')?encode(input.payload):requestPath.endsWith('/townships.geojson')?input.townBytes:requestPath.endsWith('/drilling-spacing-units.geojson')?input.dsuBytes:null;
    assert.ok(bytes,'Unexpected fetch '+requestPath);
    return {ok:true,arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),json:async()=>JSON.parse(new TextDecoder().decode(bytes))};
  };
  const scene=new THREE.Scene(),root=new THREE.Group();scene.add(root);let footage,lastAnalysis=null;
  const dsu=createDSUController(root,{focus:()=>{},say:()=>{},footageRequested:key=>footage.activateDSU(key)});
  const original=dsu.setFootageAnalysis.bind(dsu);dsu.setFootageAnalysis=analysis=>{lastAnalysis=analysis;original(analysis);};
  footage=createFootageController(scene,{dsu,focus:()=>{},say:()=>{}});
  dsu.setDataset(input.manifest);footage.setDataset(input.manifest,input.manifestBytes);
  const enable=()=>{$('footageEnabled').checked=true;$('footageEnabled').onchange();};
  const loaded=()=>lastAnalysis!==null;
  return {input,$,scene,root,dsu,footage,enable,loaded,get analysis(){return lastAnalysis;},release,fetched,storage};
}
let passed=0;async function test(name,callback){await callback();passed++;console.log('PASS '+name);}
await test('matching full snapshot loads actual DSU controller; zero differs from unknown; legacy stays unchanged',async()=>{
  const s=await setup(),before=JSON.stringify(s.input.dsus);s.enable();await settle(s.loaded,'initial load');
  const units=prepareDSUs(s.input.dsus,s.input.manifest),a=units[0];
  assert.notEqual(s.analysis.color(units[2],'mappedFt'),'#6b7280');
  assert.equal(s.analysis.color(units[3],'mappedFt'),'#6b7280');
  assert.equal(dsuValue(a,'remaining'),7.3);assert.equal(JSON.stringify(s.input.dsus),before);
  await s.dsu.openUnit('dsu-a',false);
  assert.match(s.$('dsuSelection').textContent,/84,480/);assert.match(s.$('dsuSelection').textContent,/Saved remaining wells: 7.3/);
});
await test('scenario changes preserve shared Turbo endpoints for all three metrics and independent data scopes',async()=>{
  const s=await setup();s.enable();await settle(s.loaded,'scenario load');const unit=prepareDSUs(s.input.dsus,s.input.manifest)[0];
  for(const key of ['developmentPct','mappedFt','remainingFt']){
    const ranges=[],colors=[];
    for(const scenario of ['low','base','high']){s.$('footageScenario').value=scenario;s.$('footageScenario').onchange({target:{value:scenario}});ranges.push(s.analysis.legend(key).match(/Turbo (.+?)(?:%| ft)/)?.[1]);colors.push(s.analysis.color(unit,key));}
    assert.ok(ranges[0]);assert.equal(new Set(ranges).size,1,key+' shared Turbo range');if(key==='mappedFt')assert.equal(new Set(colors).size,1,'fixed mapped footage color');
  }
});
await test('blank, invalid and unordered edits keep previous rates and rendered metrics',async()=>{
  const s=await setup();s.enable();await settle(s.loaded,'input load');const oldLegend=s.analysis.legend('remainingFt');
  for(const values of [{low:'',base:'66',high:'82.5'},{low:'70',base:'66',high:'82.5'},{low:'49.5',base:'66',high:'0'},{low:'49.5',base:'NaN',high:'82.5'}]){
    for(const [key,value]of Object.entries(values))s.$('footageRate-'+key).value=value;s.$('footageApply').onclick();
    assert.ok(s.$('footageError').textContent);assert.equal(s.analysis.legend('remainingFt'),oldLegend);
  }
  for(const [key,value]of Object.entries({low:'40',base:'60',high:'80'}))s.$('footageRate-'+key).value=value;s.$('footageApply').onclick();
  assert.equal(s.$('footageError').textContent,'');assert.match(s.analysis.legend('remainingFt'),/60 ft\/ac/);
});
await test('township card reads independent union ledger rather than sum of overlapping DSUs',async()=>{
  const s=await setup();s.enable();await settle(s.loaded,'township load');
  s.$('footageLayer').onchange({target:{value:'township'}});s.$('townshipSearch').value='T152N R96W';s.$('townshipSearch').oninput();
  const button=s.$('townshipResults').children.find(e=>e.tagName==='BUTTON');assert.ok(button);button.onclick();
  const card=s.$('footageSelection').textContent;
  assert.match(card,/40,000 ft/);assert.match(card,/132,000/);assert.doesNotMatch(card,/63,360 ft/);
  assert.equal(scenarioMetrics(s.input.payload.townships['twp-a'],66).mappedFt,40000);
  const group=s.scene.children.find(g=>g.name==='Township footage inventory');assert.equal(group.visible,true);assert.equal(group.parent,s.scene);assert.equal(group.position.y,40);
  s.root.scale.y=8;
  group.updateWorldMatrix(true,true);
  const bounds=new THREE.Box3().setFromObject(group.children.find(o=>o.isMesh));
  assert.equal(bounds.min.y,39);assert.equal(bounds.max.y,40,'township plane does not inherit survey depth exaggeration');
  const center=bounds.getCenter(new THREE.Vector3()),camera=new THREE.OrthographicCamera(-20000,20000,20000,-20000,.1,100000);
  camera.position.set(center.x,50000,center.z);camera.up.set(0,0,-1);camera.lookAt(center.x,0,center.z);camera.updateProjectionMatrix();
  s.$('footageSelection').replaceChildren();
  s.$('townshipInspect').checked=true; // user chooses Townships in "Select on map"
  assert.equal(s.footage.pick({clientX:500,clientY:500},camera,{left:0,top:0,width:1000,height:1000}),true);
  assert.match(s.$('footageSelection').textContent,/T152N R96W/,'actual ray triangle owner selects the township ledger');
});
await test('manifest or DSU fingerprint mismatch rejects footage without changing saved DSU values',async()=>{
  for(const kind of ['survey','dsu']){
    const input=await fixture();if(kind==='survey')input.payload.survey.manifest_sha256='f'.repeat(64);else input.payload.source_hashes.dsu_file_sha256='f'.repeat(64);
    const s=await setup(input);s.enable();await settle(()=>s.$('footageStatus').textContent.includes('requires its matching'),'mismatch');
    assert.equal(s.analysis,null);assert.match(s.$('dsuLegend').textContent,/gray = unavailable/);
    assert.equal(dsuValue(prepareDSUs(input.dsus,input.manifest)[0],'remaining'),7.3);
    assert.equal(s.scene.children.find(g=>g.name==='Township footage inventory').visible,false);
  }
});
await test('dataset reset prevents delayed old snapshot from reviving stale colors or townships',async()=>{
  const s=await setup(await fixture(),{deferFootage:true});s.enable();await settle(()=>s.fetched.some(f=>f.endsWith('/footage.json')),'deferred request');
  s.footage.setDataset(null);s.dsu.setDataset(null);s.release();
  for(let i=0;i<50;i++)await pause();
  assert.equal(s.analysis,null);assert.equal(s.scene.children.find(g=>g.name==='Township footage inventory').children.length,0);assert.equal(s.$('footageSelection').children.length,0);
});
await test('finite density inputs whose acreage product overflows keep the previous valid scenario',async()=>{
  const s=await setup();s.enable();await settle(s.loaded,'overflow input load');const oldLegend=s.analysis.legend('remainingFt');
  for(const key of ['low','base','high'])s.$('footageRate-'+key).value='1e308';
  s.$('footageApply').onclick();assert.ok(s.$('footageError').textContent);
  assert.equal(s.analysis.legend('remainingFt'),oldLegend,'invalid capacity edit preserves known-good rates');
  assert.notEqual(s.storage.get('bakken-footage-scenarios-v1'),JSON.stringify({low:1e308,base:1e308,high:1e308}),'invalid capacity rates are never persisted');
});
await test('restored overflow density settings cannot prevent a valid snapshot from loading',async()=>{
  const s=await setup(null,{savedRates:{low:1e308,base:1e308,high:1e308}});s.enable();
  await settle(s.loaded,'restored rates recover');
  assert.match(s.analysis.legend('remainingFt'),/66 ft\/ac/,'restored unsupported numeric range falls back to defaults');
});
await test('editing scenarios and changing geography leaves source snapshots unchanged',async()=>{
  const input=await fixture(),before=JSON.stringify(input);
  const s=await setup(input);s.enable();await settle(s.loaded,'source preservation load');
  for(const [name,value] of Object.entries({low:'40',base:'60',high:'80'}))s.$('footageRate-'+name).value=value;
  s.$('footageApply').onclick();
  s.$('footageLayer').value='township';s.$('footageLayer').onchange({target:{value:'township'}});
  s.footage.setDataset(null);s.dsu.setDataset(null);
  assert.equal(JSON.stringify(input),before,'scenario exploration cannot rewrite measurements or saved legacy inventory');
});
console.log(`${passed} actual footage controller tests passed.`);
} finally {await fs.rm(temporary,{recursive:true,force:true});}
