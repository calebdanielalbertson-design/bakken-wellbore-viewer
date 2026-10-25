// Well names are display/search data. Consumers must render returned strings
// with textContent; this module never interprets names as HTML or instructions.
const hashPattern=/^[a-f\d]{64}$/i;
const own=(value,key)=>Object.prototype.hasOwnProperty.call(value,key);
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&(Object.getPrototypeOf(value)===Object.prototype||Object.getPrototypeOf(value)===null);
const identity=well=>`${well.permit}|${well.api}`;
const compare=new Intl.Collator('en',{numeric:true,sensitivity:'base'}).compare;
const lateral=well=>/^LAT(?:ERAL)?(?:$|[\s_\-\d])/i.test(String(well.branch??''));
const depth=well=>Number.isFinite(well.maxMD)?well.maxMD:Number.isFinite(well.endMD)?well.endMD:-Infinity;
const representative=(a,b)=>Number(lateral(b))-Number(lateral(a))||depth(b)-depth(a)||a.id-b.id;

function surveyWells(survey){
  if(!Array.isArray(survey?.wells)||!survey.wells.length)throw Error('Well search requires a survey with identified branches.');
  const seen=new Set();
  for(const well of survey.wells){
    if(!well||!Number.isSafeInteger(well.id)||well.id<0||seen.has(well.id)||typeof well.permit!=='string'||!well.permit.trim()||typeof well.api!=='string'||!well.api.trim())throw Error('Invalid or duplicate survey branch identity.');
    seen.add(well.id);
  }
  return seen;
}

/** Strict optional-sidecar validation. Returns Map<number, string>, preserving
 * each supplied name verbatim. Missing metadata throws; callers may continue
 * using createWellSearch(survey) for identifier/operator search. */
export function validateWellNames(data,survey,manifestSHA256){
  const ids=surveyWells(survey),meta=data?.survey;
  if(data?.version!==1||!object(meta)||!hashPattern.test(manifestSHA256??'')||!hashPattern.test(meta.manifestSHA256??'')||meta.manifestSHA256.toLowerCase()!==manifestSHA256.toLowerCase())throw Error('Well names do not match the survey manifest fingerprint.');
  const origin=meta.origin,expectedDate=survey.sourceSnapshot?.date??null;
  if(meta.branchCount!==survey.wells.length||!Number.isSafeInteger(meta.stations)||meta.stations<=0||meta.stations!==survey.stations||typeof meta.sourceCRS!=='string'||!meta.sourceCRS||meta.sourceCRS!==survey.sourceCRS||!Array.isArray(origin)||origin.length!==2||!origin.every(Number.isFinite)||Math.abs(origin[0])>180||Math.abs(origin[1])>90||JSON.stringify(origin)!==JSON.stringify(survey.origin)||!own(meta,'sourceDate')||meta.sourceDate!==expectedDate||(meta.sourceDate!==null&&(typeof meta.sourceDate!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(meta.sourceDate))))throw Error('Well-name metadata describes a different survey snapshot.');
  if(!object(data.names)||!object(data.source)||!object(data.coverage))throw Error('Well-name metadata, source and coverage objects are required.');
  const names=new Map();
  for(const [key,name]of Object.entries(data.names)){
    if(!/^(0|[1-9]\d*)$/.test(key)||!Number.isSafeInteger(Number(key))||!ids.has(Number(key))||typeof name!=='string'||!name.trim()||/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(name))throw Error('Invalid well-name branch identity or name.');
    names.set(Number(key),name);
  }
  return names;
}

function normalized(value){
  const folded=String(value??'').normalize('NFKD').toLowerCase().replace(/\p{M}/gu,'')
    .replace(/[øłđðþæœß]/g,letter=>({ø:'o',ł:'l',đ:'d',ð:'d',þ:'th',æ:'ae',œ:'oe',ß:'ss'})[letter]);
  const text=folded.replace(/[^\p{L}\p{N}]+/gu,' ').trim().replace(/\s+/g,' ');
  return {text,compact:text.replace(/ /g,'')};
}
function field(value,kind){return {...normalized(value),kind};}
function score(branch,query,tokens){
  if(branch.fields.some(f=>f.kind==='identifier'&&f.compact===query.compact))return 0;
  if(branch.fields.some(f=>f.kind==='name'&&f.compact===query.compact))return 1;
  if(branch.fields.some(f=>f.text.startsWith(query.text)||f.compact.startsWith(query.compact)))return 2;
  if(branch.fields.some(f=>f.text.includes(query.text)||f.compact.includes(query.compact)))return 3;
  return tokens.every(token=>branch.text.includes(token))?4:Infinity;
}

/** Cached text, dynamic visibility. namedCount/totalCount describe all exact
 * permit+full-API groups. Returned branchCount counts visible sibling branches.
 * Operator callbacks are evaluated once; rebuild after their metadata changes. */
export function createWellSearch(survey,{names,operatorNameForBranch=()=>'',operatorGroupForBranch=()=>'',visible=()=>true}={}){
  surveyWells(survey);
  const cachedNames=new Map(),nameMap=names instanceof Map,nameObject=object(names);
  for(const well of survey.wells){const value=nameMap?names.get(well.id):nameObject?names[well.id]:null;if(typeof value==='string'&&value.trim())cachedNames.set(well.id,value);}
  const getName=id=>cachedNames.get(id)||'';
  const byIdentity=new Map(),byBranch=new Map();
  for(const well of survey.wells){
    const key=identity(well);if(!byIdentity.has(key))byIdentity.set(key,{branches:[],names:new Set()});
    const group=byIdentity.get(key),name=getName(well.id);group.branches.push({well,name});if(name)group.names.add(name);byBranch.set(well.id,group);
  }
  for(const group of byIdentity.values()){
    group.branches.sort((a,b)=>representative(a.well,b.well));
    group.name=group.branches.find(branch=>branch.name)?.name??'';
    const nameFields=[...group.names].map(name=>field(name,'name'));
    for(const branch of group.branches){
      branch.fields=[field(branch.well.permit,'identifier'),field(branch.well.api,'identifier'),field(branch.well.branch,'identifier'),...nameFields,field(operatorNameForBranch(branch.well.id),'operator'),field(operatorGroupForBranch(branch.well.id),'operator')].filter(value=>value.text);
      branch.text=branch.fields.map(value=>value.text).join(' ');
      branch.sort=normalized(branch.name||group.name||branch.well.permit).text;
    }
  }
  const groups=[...byIdentity.values()],namedCount=groups.filter(group=>group.names.size>0).length;
  return {
    namedCount,totalCount:groups.length,
    nameForBranch(id){return getName(id)||byBranch.get(id)?.name||'';},
    search(query,limit=30){
      if(typeof query!=='string')return {rows:[],total:0};
      const q=normalized(query);if(!q.compact)return {rows:[],total:0};
      const tokens=q.text.split(' '),matched=[];
      for(const group of groups){
        const shown=group.branches.filter(branch=>visible(branch.well.id));if(!shown.length)continue;
        // Branch-specific identifiers/operators must select the branch that
        // actually matched. Existing LAT/depth order breaks equal-score ties.
        let rank=Infinity,chosen=null;
        for(const branch of shown){const value=score(branch,q,tokens);if(value<rank){rank=value;chosen=branch;}}
        if(!chosen)continue;
        const name=chosen.name||group.name;
        matched.push({well:chosen.well,name,branchCount:shown.length,rank,sort:chosen.sort});
      }
      matched.sort((a,b)=>a.rank-b.rank||compare(a.sort,b.sort)||compare(a.well.permit,b.well.permit)||compare(a.well.api,b.well.api)||a.well.id-b.well.id);
      const cap=Number.isFinite(limit)?Math.min(30,Math.max(0,Math.floor(limit))):30;
      return {rows:matched.slice(0,cap).map(({well,name,branchCount})=>({well,name,branchCount})),total:matched.length};
    }
  };
}
