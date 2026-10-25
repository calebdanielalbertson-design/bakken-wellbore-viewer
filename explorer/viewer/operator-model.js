// Categorical operator metadata is independent of station metrics and geometry.
// Exact DMR names are retained; display groups are palette choices, not ownership
// history or a statement about the operator in a past production month.
export function createOperatorModel(data,survey){
  const s=data?.survey;
  if(data?.version!==1||!s||s.branchCount!==survey.wells.length||s.stations!==survey.stations||s.overviewSegments!==survey.overviewSegments||s.sourceCRS!==survey.sourceCRS||JSON.stringify(s.origin)!==JSON.stringify(survey.origin))throw Error('Operator index does not match this survey.');
  if(!Array.isArray(data.groups)||!data.groups.length||!Array.isArray(data.names)||!Array.isArray(data.branchGroups)||!Array.isArray(data.branchNames)||data.branchGroups.length!==survey.wells.length||data.branchNames.length!==survey.wells.length)throw Error('Incomplete operator index.');
  const keys=new Set();
  for(const [i,g]of data.groups.entries()){
    if(g.id!==i||typeof g.key!=='string'||keys.has(g.key)||typeof g.label!=='string'||!/^#[\da-f]{6}$/i.test(g.color))throw Error('Invalid operator group.');
    keys.add(g.key);
  }
  for(let i=0;i<survey.wells.length;i++){
    if(survey.wells[i].id!==i||!Number.isInteger(data.branchGroups[i])||!data.groups[data.branchGroups[i]]||!Number.isInteger(data.branchNames[i])||typeof data.names[data.branchNames[i]]!=='string')throw Error('Invalid branch operator identity.');
  }
  const groups=data.groups,branchGroups=Uint32Array.from(data.branchGroups),branchNames=Uint32Array.from(data.branchNames);
  return {groups,provenance:data.provenance||{},joinStats:data.joinStats||{},
    forBranch(id){return Number.isInteger(id)&&id>=0&&id<branchGroups.length?groups[branchGroups[id]]:null},
    nameForBranch(id){return Number.isInteger(id)&&id>=0&&id<branchNames.length?data.names[branchNames[id]]:''},
    matches(id,key){return key==='all'||this.forBranch(id)?.key===key}
  };
}
