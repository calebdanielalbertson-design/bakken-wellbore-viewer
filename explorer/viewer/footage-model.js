// Pure calculations for mapped lateral-footage scenarios. These densities are
// illustrative comparisons, not calibrated capacity, confidence or probabilities.
export const DEFAULT_SCENARIOS=Object.freeze({low:49.5,base:66,high:82.5});
export const SCENARIO_NOTE='Illustrative capacity densities: historical 66 ft/ac and ±25%; not calibrated or confidence bounds.';
export const NO_DATA_COLOR='#6b7280';
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const nonnegative=value=>finite(value)&&value>=0?value:null;
const count=value=>Number.isInteger(value)&&value>=0;
const clamp=value=>Math.max(0,Math.min(1,value));
const source=record=>record?.properties??record??{};

function positiveRate(rate){
  if(!finite(rate)||rate<=0)throw Error('Capacity density must be a positive finite number in ft/ac.');
  return rate;
}
export function validateScenarios(values){
  if(!values||typeof values!=='object'||Array.isArray(values))throw Error('Enter low, base and high capacity densities.');
  const result={low:positiveRate(values.low),base:positiveRate(values.base),high:positiveRate(values.high)};
  if(result.low>result.base||result.base>result.high)throw Error('Capacity densities must be ordered low ≤ base ≤ high.');
  return result;
}
function fromTotals(mappedFt,acres,rate){
  if((mappedFt!==null&&!finite(mappedFt))||(acres!==null&&!finite(acres)))throw Error('Footage totals exceed the supported numeric range.');
  const capacityFt=acres===null?null:acres*rate;
  if(capacityFt!==null&&(!finite(capacityFt)||(acres>0&&capacityFt===0)))throw Error('Footage capacity exceeds the supported numeric range.');
  const balanceFt=capacityFt===null||mappedFt===null?null:capacityFt-mappedFt;
  const developmentPct=capacityFt!==null&&capacityFt>0&&mappedFt!==null?100*(mappedFt/capacityFt):null;
  if(developmentPct!==null&&!finite(developmentPct))throw Error('Development ratio exceeds the supported numeric range.');
  return {mappedFt,acres,capacityFt,
    developmentPct,
    remainingFt:balanceFt===null?null:Math.max(0,balanceFt),balanceFt,
    excessFt:balanceFt===null?null:Math.max(0,-balanceFt)};
}
export function scenarioMetrics(record,rate=DEFAULT_SCENARIOS.base){
  positiveRate(rate);
  const value=source(record),eligible=value.eligible===true;
  // A documented zero-area outside-mask record is known zero. Unknown formation
  // or eligibility is not converted to zero, even if an unrelated acreage exists.
  const outside=value.eligible===false&&value.eligibility_status==='outside_dataset_mask'&&value.eligible_acres===0&&value.mapped_lateral_ft===0;
  const mappedFt=eligible?nonnegative(value.mapped_lateral_ft):outside?0:null;
  const acres=eligible?nonnegative(value.eligible_acres):outside?0:null;
  return {...fromTotals(mappedFt,acres,rate),eligible,outside};
}

// Use only for disjoint reporting partitions, or an already unioned area. This
// arithmetic helper cannot infer spatial overlap between different record IDs.
// Never aggregate independently calculated, overlapping DSUs with this function.
export function aggregateMetrics(records,rate=DEFAULT_SCENARIOS.base){
  positiveRate(rate);
  if(!Array.isArray(records))throw Error('Expected one disjoint reporting-record array.');
  const ids=new Set(),metrics=records.map(record=>{
    const id=source(record).id;
    if(id!==undefined){if(ids.has(id))throw Error('Duplicate reporting ID would count footage twice.');ids.add(id);}
    return scenarioMetrics(record,rate);
  });
  const complete=metrics.filter(m=>m.mappedFt!==null&&m.acres!==null).length;
  const sum=key=>metrics.length&&metrics.every(m=>m[key]!==null)?metrics.reduce((total,m)=>total+m[key],0):null;
  return {...fromTotals(sum('mappedFt'),sum('acres'),rate),recordCount:metrics.length,completeCount:complete,
    unavailableCount:metrics.length-complete,disjointRecordsRequired:true};
}

// Turbo polynomial approximation: Copyright 2019 Google LLC, Apache-2.0.
// Colormap: Anton Mikhailov. GLSL approximation: Ruofei Du.
// Source: https://gist.github.com/mikhailov-work/0d177465a8151eb6ede1768d51d476c7
// https://research.google/blog/turbo-an-improved-rainbow-colormap-for-visualization/
// The returned values are normalized sRGB channels, not linear-light RGB.
export function turboRGB(value){
  if(!finite(value))return null;
  const x=clamp(value),x2=x*x,x3=x2*x,x4=x2*x2,x5=x4*x;
  return [
    0.13572138+4.61539260*x-42.66032258*x2+132.13108234*x3-152.94239396*x4+59.28637943*x5,
    0.09140261+2.19418839*x+4.84296658*x2-14.18503333*x3+4.27729857*x4+2.82956604*x5,
    0.10667330+12.64194608*x-60.58204836*x2+110.36276771*x3-89.90310912*x4+27.34824973*x5
  ].map(clamp);
}
export function turboHex(value){
  const rgb=turboRGB(value);
  return rgb?'#'+rgb.map(channel=>Math.round(channel*255).toString(16).padStart(2,'0')).join(''):NO_DATA_COLOR;
}
export function percentile98(values){
  if(!Array.isArray(values))throw Error('Expected numeric values for a layer color scale.');
  const sorted=values.filter(value=>nonnegative(value)!==null).sort((a,b)=>a-b);
  if(!sorted.length)return null;
  const position=(sorted.length-1)*.98,lo=Math.floor(position),hi=Math.ceil(position);
  return sorted[lo]+(sorted[hi]-sorted[lo])*(position-lo);
}
const COLOR_METRICS=new Set(['developmentPct','mappedFt','remainingFt']);
export function createFootageColorScale(records,rate=DEFAULT_SCENARIOS.base,{metric='developmentPct',layer}={}){
  positiveRate(rate);
  if(!Array.isArray(records)||!['dsu','township'].includes(layer))throw Error('Build a color scale from one complete DSU or township layer.');
  if(!COLOR_METRICS.has(metric))throw Error('Unsupported footage color metric.');
  // Keeping layers separate is explicit at the call boundary. Call once on the
  // entire chosen layer, then reuse the returned scale when filtering or picking.
  for(const record of records){const kind=source(record).layer;if(kind!==undefined&&kind!==layer)throw Error('DSU and township color ranges must be separate.');}
  const value=record=>{const m=scenarioMetrics(record,rate);return m.eligible?m[metric]:null;};
  const values=records.map(value).filter(v=>nonnegative(v)!==null),p98=percentile98(values);
  const upper=metric==='developmentPct'?100:Math.max(1,p98??1),range=Object.freeze([0,upper]);
  const normalize=v=>finite(v)?clamp(v/upper):null;
  return {metric,layer,range,p98,sampleCount:values.length,actualMaximum:values.length?values.reduce((maximum,v)=>Math.max(maximum,v),0):null,
    clippedCount:values.filter(v=>v>upper).length,value,normalize,
    color(record){return turboHex(normalize(value(record)));},
    colorValue(v){return turboHex(normalize(v));}};
}

const hashPattern=/^[a-f\d]{64}$/i;
function validHash(value){return typeof value==='string'&&hashPattern.test(value);}
function sameIds(map,expected,label){
  if(expected===undefined)return;
  const ids=Array.from(expected);
  if(ids.some(id=>typeof id!=='string')||new Set(ids).size!==ids.length||ids.length!==map.size||ids.some(id=>!map.has(id)))throw Error(`${label} footage IDs do not match the displayed source boundaries.`);
}
function validateGroup(value,label,survey){
  if(!value||typeof value!=='object'||Array.isArray(value)||!Object.keys(value).length)throw Error(`Missing ${label} footage records.`);
  const result=new Map();
  for(const [id,record]of Object.entries(value)){
    if(!id||id.trim()!==id||!record||typeof record!=='object'||record.id!==id||typeof record.eligible!=='boolean')throw Error(`Invalid ${label} footage group identity.`);
    for(const field of ['eligible_acres','mapped_lateral_ft'])if(record[field]!==null&&nonnegative(record[field])===null)throw Error(`Invalid ${label} ${field}; unavailable values must be null.`);
    for(const field of ['observed_wells','observed_lateral_branches'])if(record[field]!==null&&!count(record[field]))throw Error(`Invalid ${label} ${field}.`);
    if(record.observed_wells>survey.well_count||record.observed_lateral_branches>survey.branch_count)throw Error(`Out-of-range ${label} observation count.`);
    if(record.eligible){
      if(record.eligibility_status!=='source_bakken_mask')throw Error(`Unsupported ${label} eligibility basis.`);
      if(!(record.eligible_acres>0)||record.mapped_lateral_ft===null||record.observed_wells===null||record.observed_lateral_branches===null)throw Error(`Supported ${label} records need measured acreage and observed footage/counts.`);
    }else{
      const outside=record.eligibility_status==='outside_dataset_mask';
      const expected=outside?0:null;
      for(const field of ['eligible_acres','mapped_lateral_ft','observed_wells','observed_lateral_branches'])if(record[field]!==expected)throw Error(`Unsupported ${label} must distinguish outside-mask zero from unavailable observations.`);
    }
    result.set(id,record);
  }
  return result;
}
export function validateFootageSnapshot(data,manifest,expectedHash,{dsuIds,townshipIds}={}){
  if(data?.version!==1||!manifest||!Array.isArray(manifest.wells)||!manifest.wells.length)throw Error('Invalid mapped-footage snapshot or survey manifest.');
  const survey=data.survey;
  if(!validHash(expectedHash)||!validHash(survey?.manifest_sha256)||survey.manifest_sha256.toLowerCase()!==expectedHash.toLowerCase())throw Error('Footage data does not match the loaded survey manifest hash.');
  if(!Array.isArray(survey.origin)||survey.origin.length!==2||!survey.origin.every(finite)||Math.abs(survey.origin[0])>180||Math.abs(survey.origin[1])>90||typeof survey.source_crs!=='string'||!survey.source_crs||typeof survey.source_date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(survey.source_date))throw Error('Footage geometry reference or source date is missing.');
  if(!count(survey.stations)||survey.stations===0||survey.stations!==manifest.stations||survey.branch_count!==manifest.wells.length||survey.source_crs!==manifest.sourceCRS||JSON.stringify(survey.origin)!==JSON.stringify(manifest.origin)||survey.source_date!==manifest.sourceSnapshot?.date)throw Error('Footage data does not match the loaded survey geometry and source date.');
  const wells=new Set();
  for(const [index,well]of manifest.wells.entries()){
    if(well.id!==index||typeof well.permit!=='string'||typeof well.api!=='string'||well.api.length<10)throw Error('Survey well identifiers are invalid.');
    wells.add(`${well.permit}|${well.api.slice(0,10)}`);
  }
  if(survey.well_count!==wells.size)throw Error('Footage well population does not match the loaded survey.');
  if(!data.source_hashes||typeof data.source_hashes!=='object'||Array.isArray(data.source_hashes)||!Object.keys(data.source_hashes).length||Object.values(data.source_hashes).some(value=>!validHash(value)))throw Error('Footage source fingerprints are incomplete.');
  if(!validHash(data.source_hashes.dsu_file_sha256)||!validHash(data.source_hashes.townships_geojson_sha256)||data.source_hashes.survey_manifest_sha256?.toLowerCase()!==expectedHash.toLowerCase())throw Error('Footage source fingerprints do not identify the survey and displayed boundaries.');
  if(data.method?.area_crs!=='EPSG:5070'||typeof data.method?.footage_label!=='string'||!data.method.footage_label.trim())throw Error('Footage measurement basis is missing or unsupported.');
  const coverage=data.coverage;
  if(!count(coverage?.usable_wells)||!count(coverage?.unusable_wells)||coverage.usable_wells+coverage.unusable_wells!==survey.well_count)throw Error('Footage coverage does not reconcile to the survey well population.');
  const dsus=validateGroup(data.dsus,'DSU',survey),townships=validateGroup(data.townships,'township',survey);
  sameIds(dsus,dsuIds,'DSU');sameIds(townships,townshipIds,'Township');
  return {data,dsus,townships,survey,coverage};
}
