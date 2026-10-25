export const REFERENCE_OIL=10000;
export function normalizeId(value){return String(value??'').trim().replace(/\.0+$/,'').replace(/[-\s]/g,'')}
export function productionKey(w){return `${normalizeId(w.permit)}|${normalizeId(w.api)}`}
export function symbolWidth(oil,referenceWidth=10){return Number.isFinite(oil)&&oil>0?referenceWidth*Math.sqrt(oil/REFERENCE_OIL):0}
export function playbackPeriods(months){
  const periods=[];let start=0;
  const serial=s=>Number(s.slice(0,4))*12+Number(s.slice(5,7))-1;
  for(let i=1;i<=months.length;i++)if(i===months.length||serial(months[i])!==serial(months[i-1])+1){periods.push({start,end:i-1,label:`${months[start]} – ${months[i-1]}`});start=i}
  return periods;
}
export function createProductionModel(metadata,values,surveyWells){
  if(metadata.version!==1||!Array.isArray(metadata.months)||!Array.isArray(metadata.wells)||!metadata.months.length||!metadata.wells.length)throw Error('Invalid production index');
  const count=metadata.wells.length;
  if(values.length!==count*metadata.months.length)throw Error('Incomplete monthly production data');
  const index=new Map(metadata.wells.map((w,i)=>[productionKey(w),i]));
  if(index.size!==count)throw Error('Duplicate production well identifiers');
  const byBranch=new Int32Array(surveyWells.length).fill(-1),renderByBranch=new Int32Array(surveyWells.length).fill(-1),scope=new Set(),missingIndex=new Map();
  for(const w of surveyWells){const key=productionKey(w),i=index.get(key);if(i!==undefined){byBranch[w.id]=renderByBranch[w.id]=i;scope.add(i)}else{if(!missingIndex.has(key))missingIndex.set(key,-2-missingIndex.size);renderByBranch[w.id]=missingIndex.get(key)}}
  const allScopeIndices=[...scope],scopeIndices=[...scope],summaries=[];
  function summarize(){summaries.length=0;for(let m=0;m<metadata.months.length;m++){let barrels=0,reported=0,producing=0,maximumOil=0;for(const i of scopeIndices){const v=values[m*count+i];if(Number.isFinite(v)&&v>=0){barrels+=v;reported++;maximumOil=Math.max(maximumOil,v);if(v>0)producing++}}summaries.push({month:metadata.months[m],barrels,reported,producing,maximumOil})}}
  summarize();
  return {metadata,values,count,byBranch,renderByBranch,scopeIndices,summaries,
    value(month,index){return index<0?NaN:values[month*count+index]},
    indexOf(w){return w?byBranch[w.id]??-1:-1},
    renderIndexOf(w){return w?renderByBranch[w.id]??-1:-1},
    setBranchScope(ids=null){const next=ids===null?allScopeIndices:[...new Set(ids.map(id=>byBranch[id]).filter(i=>i>=0))];scopeIndices.length=0;scopeIndices.push(...next);summarize()},
    uploadMonth(month,target){target.fill(-1);for(let i=0;i<count;i++){const v=values[month*count+i];if(Number.isFinite(v)&&v>=0)target[i]=v}return target}
  };
}
