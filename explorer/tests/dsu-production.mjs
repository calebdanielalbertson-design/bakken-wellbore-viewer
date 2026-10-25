// Run from a source checkout: node tests/dsu-production.mjs
// --viewer PATH selects viewer sources; --data PATH optionally checks prepared
// full survey/production, and --membership PATH selects its association index.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';

const args=process.argv.slice(2),option=name=>{const i=args.indexOf(name);return i<0?null:args[i+1];};
const viewer=path.resolve(option('--viewer')??'viewer');
const sourceUrl=name=>pathToFileURL(path.join(viewer,name)).href;
const THREE=await import(sourceUrl('vendor/three.module.js'));
const {createDSUMembershipModel,membershipKey,createDSUWellController}=await import(sourceUrl('dsu-wells.js'));
const {createProductionModel}=await import(sourceUrl('production-model.js'));
const {renderScopeHistory}=await import(sourceUrl('production-history.js'));
const temporaryParent=await fs.realpath(os.tmpdir()),temporary=await fs.mkdtemp(path.join(temporaryParent,'bakken-dsu-production-test-'));
try{
const productionText=(await fs.readFile(path.join(viewer,'production.js'),'utf8'))
 .replace("from 'three'",`from '${sourceUrl('vendor/three.module.js')}'`)
 .replace("from './production-model.js'",`from '${sourceUrl('production-model.js')}'`)
 .replace("from './production-history.js'",`from '${sourceUrl('production-history.js')}'`);
await fs.writeFile(path.join(temporary,'production.mjs'),productionText);
const {createProductionController}=await import(pathToFileURL(path.join(temporary,'production.mjs')).href);

const manifest={version:1,sourceCRS:'NAD83',origin:[-103,48],stations:120,wells:[]};
for(const [permit,count] of [['1',3],['2',2],['3',2],['4',2]])for(let i=0;i<count;i++){
 const id=manifest.wells.length;manifest.wells.push({id,permit,api:`330010000${permit}0000`,branch:i?'LAT'+i:'VERT'});
}
const manifestBytes=new TextEncoder().encode(JSON.stringify(manifest));
const hash=createHash('sha256').update(manifestBytes).digest('hex');
const row=(permit,branchIds,intersectingBranchIds,insideFt,totalFt)=>({key:`${permit}|330010000${permit}`,permit,api10:`330010000${permit}`,branchIds,intersectingBranchIds,insideFt,totalFt,fraction:insideFt/totalFt});
const rows=[row('1',[0,1,2],[1],660,2000),row('2',[3,4],[4],10,1000),row('3',[5,6],[6],500,1000),row('4',[7,8],[8],1000,1500)];
const membership={version:1,survey:{branchCount:9,stations:120,sourceCRS:'NAD83',origin:[-103,48]},sourceHashes:{manifestSha256:hash},dsu:{featureCount:2},units:{'unit-a':rows,'unit-b':[rows[0]]}};
const model=createDSUMembershipModel(membership,manifest,hash);
assert.deepEqual(model.rows('unit-a').map(r=>r.permit),['1','4']);
assert.deepEqual(model.rows('unit-a','any').map(r=>r.permit),['1','2','3','4']);
assert.deepEqual(model.rows('unit-a','majority').map(r=>r.permit),['3','4']);
assert.equal(membershipKey({permit:' 1.0 ',api:'33-001-00001-0000'}),'1|3300100001');
assert.throws(()=>model.rows('missing'),/absent/);
assert.throws(()=>createDSUMembershipModel(membership,manifest,'incorrect'),/fingerprint/);
for(const mutate of [d=>d.version=2,d=>d.survey.stations++,d=>d.survey.branchCount++,d=>d.survey.origin[0]++,d=>d.survey.sourceCRS='WGS84',d=>d.dsu.featureCount++,d=>d.units['unit-a'].push(d.units['unit-a'][0]),d=>d.units['unit-a'][0].fraction=.99,d=>d.units['unit-a'][0].branchIds.push(999),d=>d.units['unit-a'][0].intersectingBranchIds=[4],d=>d.units['unit-a'][0].insideFt=0]){
 const bad=structuredClone(membership);mutate(bad);assert.throws(()=>createDSUMembershipModel(bad,manifest,hash));
}

const metadata={version:1,months:['2024-01','2024-02','2024-03','2024-04'],wells:manifest.wells.filter(w=>['1','2','3'].includes(w.permit)&&w.branch==='VERT').map(w=>({permit:w.permit,api:w.api})),valuesFile:'oil.bin'};
const values=new Float32Array([100,200,300, NaN,NaN,NaN, 0,0,0, 50,NaN,70]);
const productionModel=createProductionModel(metadata,values,manifest.wells);
productionModel.setBranchScope([0,1,2,7,8,0,1,2]);
assert.equal(productionModel.scopeIndices.length,1,'all branches and duplicate branch IDs count a production well once');
assert.deepEqual(productionModel.summaries.map(s=>[s.barrels,s.reported,s.producing]),[[100,1,1],[0,0,0],[0,1,0],[50,1,1]]);
assert.ok(Number.isNaN(productionModel.value(0,productionModel.indexOf(manifest.wells[7]))),'unmatched well has no value');

const elements=new Map();
class Element{
 constructor(tag='div'){this.tagName=tag;this.children=[];this.style={};this.attributes={};this.classList={add(){}};this.value='';this.checked=false;this.hidden=false;this.disabled=false;this._text='';}
 set id(value){this._id=value;elements.set(value,this);}get id(){return this._id;}
 set textContent(value){this._text=String(value);this.children=[];}get textContent(){return this._text+this.children.map(child=>child.textContent??'').join('');}
 append(...items){this.children.push(...items);}replaceChildren(...items){this._text='';this.children=items;}setAttribute(name,value){this.attributes[name]=String(value);}
}
const $=id=>{if(!elements.has(id)){const e=new Element();e.id=id;}return elements.get(id);};
globalThis.document={getElementById:$,createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),addEventListener(){}};
const texts=element=>element.textContent;
const history=new Element();
const historyProps={title:'Synthetic DSU',totalWells:2,matchedWells:1,months:metadata.months,summaries:productionModel.summaries,period:{start:0,end:3},month:1};
renderScopeHistory(history,historyProps);assert.match(texts(history),/No reported values/);assert.match(texts(history),/1 selected wells have no production match/);
renderScopeHistory(history,{...historyProps,month:2});assert.match(texts(history),/0 bbl reported/);
const svg=history.children.find(child=>child.tagName==='svg'),curve=svg.children.find(child=>child.tagName==='path');
assert.equal((curve.attributes.d.match(/M/g)||[]).length,2,'missing February opens a gap; zero March retains a point');
assert.match(texts(history),/Reported oil in this period: 150 bbl/);
assert.match(texts(history),/Overlapping DSU totals must not be added/);
renderScopeHistory(history,{...historyProps,matchedWells:0});assert.match(texts(history),/No production matches/);

// Wire the same group-scope interaction as the app using controlled operator visibility.
$('productionSpeed').value='3';
const production=createProductionController();
const reader=async(name,json)=>json?structuredClone(metadata):values.buffer.slice(0);
await production.load(reader,manifest);assert.equal(production.ready(),true);
let latest=null,visible=new Set(manifest.wells.map(w=>w.id)),fetches=0;
globalThis.fetch=async()=>{fetches++;return{ok:true,json:async()=>structuredClone(membership)};};
const apply=state=>{latest=state;production.setScopeHistory(state?{title:state.label,totalWells:state.rows.length}:null);production.setBranchScope(state?state.branchIds:null,state?.label??'all');production.highlightBranches(state?.branchIds??null);};
const selectedWells=[];
const controller=createDSUWellController({changed:apply,visible:id=>visible.has(id),selectWell:well=>selectedWells.push(well),play:()=>production.playScope(),clear(){}});
controller.setDataset(manifest,manifestBytes);
const unit={id:'unit-a',properties:{sourceRecord:1,display:{insetFt:100},zone:{topFt:9000,bottomFt:10000}}};
await controller.select(unit);
assert.deepEqual(latest.branchIds,[0,1,2,7,8],'all source branches highlight, including nonintersecting vertical/sibling paths');
assert.equal(latest.rows.length,2);assert.equal(fetches,1);
assert.match(texts($('dsuProduction')),/1 selected wells have no production match/);
const makeLine=ids=>{const line=new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(ids.flatMap((_,i)=>[i,0,0,i+1,0,0]),3)),new THREE.LineBasicMaterial());line.userData.ids=ids;production.decorate(line);return line;};
const line=makeLine(manifest.wells.map(w=>w.id));
assert.deepEqual(Array.from(line.userData.production.scopeInstances.array),[1,1,1,0,0,0,0,1,1]);
assert.deepEqual(Array.from(line.geometry.attributes.groupSelected.array),[1,1,1,0,0,0,0,1,1].flatMap(v=>[v,v]));
visible=new Set([0,1,2]);controller.refresh();assert.equal(latest.rows.length,1);assert.equal(latest.allRows.length,2);assert.deepEqual(latest.branchIds,[0,1,2]);
assert.deepEqual(Array.from(line.userData.production.scopeInstances.array),[1,1,1,0,0,0,0,0,0]);
assert.match(texts($('productionCoverage')),/1 of 1 matched well/);
visible=new Set(manifest.wells.map(w=>w.id));controller.refresh();
$('dsuMembershipRule').onchange({target:{value:'any'}});assert.equal(latest.rows.length,4);assert.equal(latest.branchIds.length,9);
$('dsuMembershipRule').onchange({target:{value:'majority'}});assert.deepEqual(latest.rows.map(r=>r.permit),['3','4']);
$('dsuMembershipRule').onchange({target:{value:'660'}});
const priorIds=latest.branchIds.slice();unit.properties.display.insetFt=99999;unit.properties.display.depthStep=10000;
await controller.select(unit);assert.deepEqual(latest.branchIds,priorIds,'source display offsets do not change associations');assert.equal(fetches,1);
$('productionMonth').oninput({target:{value:1}});assert.match(texts($('dsuProduction')),/No reported values/);
$('productionMonth').oninput({target:{value:2}});assert.match(texts($('dsuProduction')),/0 bbl reported/);
production.playScope();assert.equal($('productionPlay').textContent,'Pause');assert.equal($('productionDate').value,'2024-01');
controller.setDataset(null);assert.equal(latest,null);assert.equal($('dsuProduction').children.length,0);
assert.ok(line.userData.production.scopeInstances.array.every(value=>value===0));
production.reset();await production.load(reader,manifest);assert.equal(production.ready(),true);
assert.match(texts($('productionCoverage')),/2 of 3 matched wells/);

// A group can be chosen while an oil file is loading. Reapply after completion,
// as the app must do, and verify the resulting scope rather than stale global totals.
const delayedProduction=createProductionController();let releaseProduction;
const delayedLoad=delayedProduction.load(async(name,json)=>json?await new Promise(resolve=>releaseProduction=resolve):values.buffer.slice(0),manifest);
delayedProduction.setScopeHistory({title:'Deferred DSU',totalWells:2});delayedProduction.setBranchScope([0,1,2,7,8],'Deferred DSU');
releaseProduction(structuredClone(metadata));await delayedLoad;
const beforeRefresh=texts($('dsuProduction'));
assert.match(beforeRefresh,/1 selected wells have no production match/,'a scope chosen during loading applies to the first ready chart');
assert.doesNotMatch(beforeRefresh,/-\d+ selected wells/);
delayedProduction.setBranchScope([0,1,2,7,8],'Deferred DSU');
assert.match(texts($('dsuProduction')),/1 selected wells have no production match/);
assert.doesNotMatch(texts($('dsuProduction')),/-\d+ selected wells/);

// A DSU fetch that resolves after dataset replacement must not reinstate the old group.
let releaseOld;globalThis.fetch=async()=>{await new Promise(resolve=>releaseOld=resolve);return{ok:true,json:async()=>structuredClone(membership)};};
controller.setDataset(manifest);const oldSelect=controller.select(unit);while(!releaseOld)await new Promise(resolve=>setTimeout(resolve,0));
controller.setDataset(null);releaseOld();await oldSelect;assert.equal(latest,null);

// Optional real-data checks independently join API14 production identifiers through API10 membership keys.
const dataDir=path.resolve(option('--data')??'full-dataset');
const membershipPath=path.resolve(option('--membership')??path.join(viewer,'data/dsu/dsu-well-membership.json'));
let realSummary='synthetic fixtures only';
let haveReal=false;try{await fs.access(path.join(dataDir,'manifest.json'));await fs.access(membershipPath);haveReal=true;}catch(error){if(option('--data')||option('--membership'))throw error;}
if(haveReal){
 const manifestBuffer=await fs.readFile(path.join(dataDir,'manifest.json')),survey=JSON.parse(manifestBuffer),associations=JSON.parse(await fs.readFile(membershipPath,'utf8'));
 const realMembership=createDSUMembershipModel(associations,survey,createHash('sha256').update(manifestBuffer).digest('hex'));
 const raw=JSON.parse(await fs.readFile(path.join(dataDir,'production.json'),'utf8')),oilBuffer=await fs.readFile(path.join(dataDir,raw.valuesFile||raw.file||'oil.bin'));
 const oil=new Float32Array(oilBuffer.buffer,oilBuffer.byteOffset,oilBuffer.byteLength/4),realProduction=createProductionModel(raw,oil,survey.wells);
 const clean=value=>String(value??'').trim().replace(/\.0+$/,'').replace(/[-\s]/g,''),fullKey=w=>clean(w.permit)+'|'+clean(w.api);
 const branches=new Map(survey.wells.map(w=>[w.id,w])),productionIndices=new Map(raw.wells.map((well,index)=>[fullKey(well),index]));
 let scopes=0;
 for(const id of ['dsu-0e6eb4434fe910558aed','dsu-5e86a06ae71c8929aae6'])for(const rule of ['660','any','majority']){
  const members=realMembership.rows(id,rule),branchIds=members.flatMap(row=>row.branchIds),candidateIndices=new Set();
  for(const row of members){for(const branchId of row.branchIds){const well=branches.get(branchId);assert.equal(membershipKey(well),row.key);const index=productionIndices.get(fullKey(well));if(index!==undefined)candidateIndices.add(index);}}
  const expectedIndices=[...candidateIndices];realProduction.setBranchScope(branchIds);
  assert.deepEqual(realProduction.scopeIndices.toSorted((a,b)=>a-b),expectedIndices.toSorted((a,b)=>a-b),id+' '+rule+' production match set');
  const reference=realProduction.summaries.map(summary=>({...summary}));
  for(let month=0;month<raw.months.length;month++){
   let barrels=0,reported=0,producing=0,maximumOil=0;
   for(const index of expectedIndices){const value=oil[month*raw.wells.length+index];if(Number.isFinite(value)&&value>=0){barrels+=value;reported++;producing+=value>0;maximumOil=Math.max(maximumOil,value);}}
   assert.deepEqual(realProduction.summaries[month],{month:raw.months[month],barrels,reported,producing,maximumOil},id+' '+rule+' '+raw.months[month]);
  }
  realProduction.setBranchScope([...branchIds,...branchIds]);assert.deepEqual(realProduction.summaries,reference,'duplicate survey branches do not duplicate whole-well barrels');scopes++;
 }
 realSummary=`${scopes} real DSU/rule scopes × ${raw.months.length} months independently verified`;
}
line.geometry.dispose();line.material.dispose();line.userData.production.mesh.geometry.dispose();line.userData.production.mesh.material.dispose();
console.log('PASS: membership validation/rules, all-branch/operator scope, zero vs missing production/history, group masks, clear/replacement, source-display independence; '+realSummary+'.');
}finally{
 const resolved=await fs.realpath(temporary);assert.equal(path.dirname(resolved),temporaryParent);assert.ok(path.basename(resolved).startsWith('bakken-dsu-production-test-'));await fs.rm(resolved,{recursive:true,force:true});
}
