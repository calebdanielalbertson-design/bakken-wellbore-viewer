import assert from 'node:assert/strict';
import {DEFAULT_SCENARIOS,validateScenarios,scenarioMetrics,aggregateMetrics,turboRGB,turboHex,NO_DATA_COLOR,percentile98,createFootageColorScale,validateFootageSnapshot} from '../viewer/footage-model.js';

let passed=0;
function test(name,callback){callback();passed++;console.log(`PASS ${name}`);}
const near=(actual,expected,tolerance=1e-9)=>assert.ok(Math.abs(actual-expected)<=tolerance,`${actual} != ${expected}`);
const record=(id,acres,feet,extra={})=>({id,eligible:true,eligibility_status:'source_bakken_mask',eligible_acres:acres,mapped_lateral_ft:feet,observed_wells:feet===0?0:1,observed_lateral_branches:feet===0?0:1,...extra});
const hash='a'.repeat(64),clone=value=>JSON.parse(JSON.stringify(value));
function fixture(){
  const manifest={stations:4,sourceCRS:'NAD83',origin:[-103,48],sourceSnapshot:{date:'2026-10-17'},wells:[
    {id:0,permit:'100',api:'33053000010000'},{id:1,permit:'100',api:'33053000010000'}]};
  const data={version:1,survey:{manifest_sha256:hash,stations:4,branch_count:2,well_count:1,origin:[-103,48],source_crs:'NAD83',source_date:'2026-10-17'},
    source_hashes:{survey_manifest_sha256:hash,dsu_file_sha256:'b'.repeat(64),townships_geojson_sha256:'c'.repeat(64)},method:{area_crs:'EPSG:5070',footage_label:'Mapped classified lateral plan footage'},
    coverage:{usable_wells:1,unusable_wells:0},dsus:{'dsu-a':record('dsu-a',1280,31680)},townships:{'twp-a':record('twp-a',2560,31680)}};
  return {manifest,data};
}

test('defaults explicitly remain illustrative density comparisons',()=>{
  assert.deepEqual(DEFAULT_SCENARIOS,{low:49.5,base:66,high:82.5});
  assert.ok(Object.isFrozen(DEFAULT_SCENARIOS));
  assert.deepEqual(validateScenarios(DEFAULT_SCENARIOS),DEFAULT_SCENARIOS);
  assert.deepEqual(validateScenarios({low:66,base:66,high:66}),{low:66,base:66,high:66});
});
test('invalid, blank, coerced and unordered density inputs are rejected',()=>{
  for(const value of [null,undefined,'','66',' ',false,0,-1,NaN,Infinity])assert.throws(()=>validateScenarios({low:value,base:66,high:82.5}));
  assert.throws(()=>validateScenarios({low:70,base:66,high:82.5}));
  assert.throws(()=>validateScenarios({low:49.5,base:66,high:65}));
  for(const rate of [null,'',false,'66',0,-1,NaN,Infinity])assert.throws(()=>scenarioMetrics(record('x',1280,0),rate));
});
test('same-footprint acreage and mapped feet produce dimensional metrics',()=>{
  const m=scenarioMetrics(record('a',1280,31680),66);
  assert.equal(m.capacityFt,84480);assert.equal(m.developmentPct,37.5);
  assert.equal(m.remainingFt,52800);assert.equal(m.balanceFt,52800);assert.equal(m.excessFt,0);
});
test('mixed lengths deplete footage rather than raw well count',()=>{
  const m=scenarioMetrics(record('a',1280,10560+15840+21120,{observed_wells:3}),66);
  assert.equal(m.mappedFt/10560,4.5);assert.equal(m.developmentPct,56.25);
  assert.equal(m.remainingFt,36960);assert.equal(m.remainingFt/10560,3.5);
});
test('missing acreage, footage or eligibility never becomes zero',()=>{
  const noArea=scenarioMetrics(record('a',null,100),66);
  assert.equal(noArea.mappedFt,100);assert.equal(noArea.acres,null);assert.equal(noArea.capacityFt,null);assert.equal(noArea.remainingFt,null);
  const noFootage=scenarioMetrics(record('a',1280,null),66);
  assert.equal(noFootage.mappedFt,null);assert.equal(noFootage.capacityFt,84480);assert.equal(noFootage.developmentPct,null);assert.equal(noFootage.remainingFt,null);
  const unknown=scenarioMetrics({id:'u',eligible:false,eligible_acres:null,mapped_lateral_ft:null},66);
  assert.equal(unknown.capacityFt,null);assert.equal(unknown.mappedFt,null);assert.equal(unknown.balanceFt,null);
  assert.equal(scenarioMetrics({eligible_acres:1280,mapped_lateral_ft:100},66).capacityFt,null);
  assert.equal(scenarioMetrics(record('a','1280','100'),66).capacityFt,null);
});
test('known empty supported area differs from explicit outside-mask zero',()=>{
  const empty=scenarioMetrics(record('a',1280,0),66);
  assert.equal(empty.developmentPct,0);assert.equal(empty.remainingFt,84480);
  const outside=scenarioMetrics({eligible:false,eligibility_status:'outside_dataset_mask',eligible_acres:0,mapped_lateral_ft:0},66);
  assert.equal(outside.mappedFt,0);assert.equal(outside.capacityFt,0);assert.equal(outside.developmentPct,null);assert.equal(outside.remainingFt,0);
});
test('over-benchmark observations retain raw percent and negative balance',()=>{
  const m=scenarioMetrics(record('a',1280,100000),66);
  assert.ok(m.developmentPct>100);assert.equal(m.balanceFt,-15520);
  assert.equal(m.remainingFt,0);assert.equal(m.excessFt,15520);
});
test('unsupported numeric overflow and underflow cannot create infinite metrics',()=>{
  assert.throws(()=>scenarioMetrics(record('a',Number.MAX_VALUE,1),66));
  assert.throws(()=>scenarioMetrics(record('a',1,Number.MAX_VALUE),Number.MIN_VALUE));
  assert.throws(()=>scenarioMetrics(record('a',Number.MIN_VALUE,1),Number.MIN_VALUE));
  assert.throws(()=>aggregateMetrics([record('a',1,Number.MAX_VALUE),record('b',1,Number.MAX_VALUE)],1));
});
test('lower/higher capacity scenarios change denominator monotonically',()=>{
  const r=record('a',1280,31680),low=scenarioMetrics(r,49.5),base=scenarioMetrics(r,66),high=scenarioMetrics(r,82.5);
  assert.ok(low.capacityFt<base.capacityFt&&base.capacityFt<high.capacityFt);
  assert.ok(low.remainingFt<base.remainingFt&&base.remainingFt<high.remainingFt);
  assert.ok(low.developmentPct>base.developmentPct&&base.developmentPct>high.developmentPct);
  assert.equal(low.mappedFt,high.mappedFt);
});
test('disjoint-area aggregation is capacity weighted, not mean percent',()=>{
  const a=record('a',1280,84480),b=record('b',2560,0),m=aggregateMetrics([a,b],66);
  assert.equal(m.acres,3840);assert.equal(m.mappedFt,84480);assert.equal(m.capacityFt,253440);
  near(m.developmentPct,100/3);assert.notEqual(m.developmentPct,50);
  assert.equal(m.remainingFt,168960);assert.equal(m.unavailableCount,0);
  assert.throws(()=>aggregateMetrics([a,a],66));
});
test('regional net and summed local positive headroom remain distinct',()=>{
  const records=[record('a',1000,1500),record('b',1000,0)],net=aggregateMetrics(records,1);
  assert.equal(net.remainingFt,500);
  assert.equal(records.reduce((sum,r)=>sum+scenarioMetrics(r,1).remainingFt,0),1000);
});
test('aggregation preserves incomplete observations instead of silently dropping them',()=>{
  const m=aggregateMetrics([record('a',1280,100),record('b',1280,null)],66);
  assert.equal(m.acres,2560);assert.equal(m.mappedFt,null);assert.equal(m.capacityFt,168960);
  assert.equal(m.remainingFt,null);assert.equal(m.unavailableCount,1);assert.equal(m.completeCount,1);
  assert.equal(aggregateMetrics([],66).capacityFt,null);
});
test('official Turbo approximation has stable coefficients, saturation and no-data handling',()=>{
  const dark=turboRGB(0);near(dark[0],.13572138);near(dark[1],.09140261);near(dark[2],.10667330);
  assert.equal(turboHex(0),'#23171b');assert.equal(turboHex(1),'#900d00');
  assert.deepEqual(turboRGB(-2),turboRGB(0));assert.deepEqual(turboRGB(5),turboRGB(1));
  assert.equal(turboHex(null),NO_DATA_COLOR);assert.equal(turboHex(NaN),NO_DATA_COLOR);
  for(let i=0;i<=100;i++)assert.ok(turboRGB(i/100).every(v=>v>=0&&v<=1));
});
test('percent color domain is fixed 0–100 while data retains values above 100',()=>{
  const r=record('a',1280,100000),scale=createFootageColorScale([r],66,{metric:'developmentPct',layer:'dsu'});
  assert.deepEqual(scale.range,[0,100]);assert.ok(scale.value(r)>100);
  assert.equal(scale.color(r),scale.colorValue(100));assert.equal(scale.clippedCount,1);
  assert.ok(scenarioMetrics(r,66).developmentPct>100);
});
test('footage colors use one whole-layer P98 domain and preserve outliers',()=>{
  const rows=Array.from({length:101},(_,i)=>record('d'+i,1280,i===100?10000:i));
  const scale=createFootageColorScale(rows,66,{metric:'mappedFt',layer:'dsu'});
  assert.equal(percentile98(rows.map(r=>r.mapped_lateral_ft)),98);assert.deepEqual(scale.range,[0,98]);
  assert.equal(scale.actualMaximum,10000);assert.equal(scale.clippedCount,2);
  assert.equal(scale.value(rows[100]),10000);assert.equal(scale.color(rows[100]),scale.colorValue(98));
  const before=scale.color(rows[20]);rows.filter(r=>r.id==='d20');assert.equal(scale.color(rows[20]),before);
});
test('DSU/township ranges are separate and unsupported observations are gray',()=>{
  const d=record('d',1280,100,{layer:'dsu'}),t=record('t',23040,2000,{layer:'township'});
  const ds=createFootageColorScale([d],66,{metric:'mappedFt',layer:'dsu'}),ts=createFootageColorScale([t],66,{metric:'mappedFt',layer:'township'});
  assert.equal(ds.range[1],100);assert.equal(ts.range[1],2000);
  assert.throws(()=>createFootageColorScale([d,t],66,{metric:'mappedFt',layer:'dsu'}));
  assert.throws(()=>createFootageColorScale([d],66,{metric:'mappedFt'}));
  const unsupported={id:'u',eligible:false,eligible_acres:null,mapped_lateral_ft:null};
  assert.equal(ds.color(unsupported),NO_DATA_COLOR);
});
test('large-layer color domains do not depend on argument-count limits',()=>{
  const rows=Array.from({length:150000},(_,i)=>record('d'+i,1280,i));
  const scale=createFootageColorScale(rows,66,{metric:'mappedFt',layer:'dsu'});
  assert.equal(scale.sampleCount,150000);assert.equal(scale.actualMaximum,149999);
  near(scale.p98,146999.02);
});
test('snapshot verifies source hash, exact survey population and optional boundary ID sets',()=>{
  const {data,manifest}=fixture(),checked=validateFootageSnapshot(data,manifest,hash,{dsuIds:['dsu-a'],townshipIds:['twp-a']});
  assert.equal(checked.dsus.get('dsu-a').mapped_lateral_ft,31680);assert.equal(checked.townships.size,1);
  assert.throws(()=>validateFootageSnapshot(data,manifest,'b'.repeat(64)));
  assert.throws(()=>validateFootageSnapshot(data,manifest,''));
  assert.throws(()=>validateFootageSnapshot(data,manifest,hash,{dsuIds:['other']}));
  for(const [key,value]of [['stations',5],['branch_count',1],['well_count',2],['origin',[-102,48]],['source_crs','WGS84'],['source_date','2026-09-07']]){
    const changed=clone(data);changed.survey[key]=value;assert.throws(()=>validateFootageSnapshot(changed,manifest,hash),key);
  }
});
test('snapshot rejects changed group IDs, invalid metrics, counts and measurement basis',()=>{
  const {data,manifest}=fixture();
  for(const mutate of [d=>d.dsus['dsu-a'].id='wrong',d=>d.dsus['dsu-a'].mapped_lateral_ft=-1,d=>d.dsus['dsu-a'].eligible_acres='1280',d=>d.dsus['dsu-a'].observed_wells=1.5,d=>d.dsus['dsu-a'].observed_wells=2,d=>d.dsus['dsu-a'].eligibility_status='unverified',d=>d.method.area_crs='EPSG:4326',d=>d.source_hashes.survey_manifest_sha256='not a hash',d=>d.source_hashes.survey_manifest_sha256='f'.repeat(64),d=>delete d.source_hashes.townships_geojson_sha256,d=>d.survey.origin=[undefined,undefined],d=>d.coverage.unusable_wells=1]){
    const changed=clone(data);mutate(changed);assert.throws(()=>validateFootageSnapshot(changed,manifest,hash));
  }
});
test('snapshot keeps unknown-formation nulls distinct from outside-mask zeros',()=>{
  const {data,manifest}=fixture();
  data.dsus['dsu-u']={id:'dsu-u',eligible:false,eligibility_status:'unknown_source_formation',eligible_acres:null,mapped_lateral_ft:null,observed_wells:null,observed_lateral_branches:null};
  data.townships['twp-out']={id:'twp-out',eligible:false,eligibility_status:'outside_dataset_mask',eligible_acres:0,mapped_lateral_ft:0,observed_wells:0,observed_lateral_branches:0};
  assert.equal(validateFootageSnapshot(data,manifest,hash).dsus.size,2);
  const wrong=clone(data);wrong.dsus['dsu-u'].mapped_lateral_ft=0;assert.throws(()=>validateFootageSnapshot(wrong,manifest,hash));
});

console.log(`\n${passed} footage-model tests passed.`);
