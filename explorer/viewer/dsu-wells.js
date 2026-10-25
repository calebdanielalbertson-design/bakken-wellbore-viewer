const $=id=>document.getElementById(id),fmt=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:0});
export const membershipKey=w=>`${String(w.permit).trim().replace(/\.0+$/,'')}|${String(w.api10??w.api).replace(/[-\s]/g,'').slice(0,10)}`;
export function createDSUMembershipModel(data,manifest,expectedHash=null){
  const s=data?.survey;
  if(data?.version!==1||!s||s.branchCount!==manifest.wells.length||s.stations!==manifest.stations||s.sourceCRS!==manifest.sourceCRS||JSON.stringify(s.origin)!==JSON.stringify(manifest.origin))throw Error('Well membership is prepared for a different survey snapshot. Use the current full dataset or rebuild the membership file.');
  if(expectedHash&&data.sourceHashes?.manifestSha256!==expectedHash)throw Error('DSU membership does not match this survey manifest fingerprint. Rebuild the membership file.');
  if(!data.units||Object.keys(data.units).length!==data.dsu?.featureCount)throw Error('Incomplete DSU membership index.');
  const wells=new Map(manifest.wells.map(w=>[w.id,w]));
  for(const rows of Object.values(data.units)){
    const seen=new Set();if(!Array.isArray(rows))throw Error('Invalid DSU membership rows.');
    for(const r of rows){
      if(seen.has(r.key)||r.key!==membershipKey(r)||!Array.isArray(r.branchIds)||!r.branchIds.length||!Array.isArray(r.intersectingBranchIds)||!r.intersectingBranchIds.length||![r.insideFt,r.totalFt,r.fraction].every(Number.isFinite)||r.insideFt<=0||r.totalFt<=0||r.insideFt>r.totalFt+.1||Math.abs(r.fraction-r.insideFt/r.totalFt)>1e-5)throw Error('Invalid or duplicate DSU well association.');
      if(r.branchIds.some(id=>!wells.has(id)||membershipKey(wells.get(id))!==r.key)||r.intersectingBranchIds.some(id=>!r.branchIds.includes(id)))throw Error('DSU association does not match survey branch identities.');
      seen.add(r.key);
    }
  }
  return {data,rows(id,rule='660'){if(!Object.hasOwn(data.units,id))throw Error('This DSU is absent from the membership snapshot.');return data.units[id].filter(r=>rule==='any'||(rule==='majority'?r.fraction>=.5:r.insideFt>=660))}};
}

export function createDSUWellController({changed,visible=()=>true,selectWell,play,clear}){
  let manifest=null,model=null,pending=null,generation=0,request=0,unit=null,rule='660',fingerprint=Promise.resolve(null);
  function notify(rows=null){
    const all=rows??(unit&&model?model.rows(unit.id,rule):[]),shown=all.filter(r=>r.branchIds.some(visible));
    const ids=shown.flatMap(r=>r.branchIds.filter(visible));
    changed(unit&&model?{unit,rows:shown,allRows:all,branchIds:ids,label:`DSU #${unit.properties.sourceRecord}`,rule}:null);
  }
  function render(){
    const host=$('dsuWellDetails');host.replaceChildren();if(!unit||!model){notify(null);return}
    const rows=model.rows(unit.id,rule),shown=rows.filter(r=>r.branchIds.some(visible));
    const title=document.createElement('h3');title.textContent='Wells in this footprint';
    const count=document.createElement('p');count.className='dsu-well-count';count.textContent=`${fmt(shown.length)} unique wells highlighted${shown.length!==rows.length?' · '+fmt(rows.length)+' before operator filter':''}`;
    const label=document.createElement('label');label.className='field';label.htmlFor='dsuMembershipRule';label.textContent='Lateral overlap rule';
    const select=document.createElement('select');select.id='dsuMembershipRule';select.setAttribute('aria-label','Lateral overlap rule');
    for(const [value,text] of [['660','At least 660 ft inside'],['any','Any positive lateral length inside'],['majority','At least half the surveyed lateral inside']]){const o=document.createElement('option');o.value=value;o.textContent=text;select.append(o)}select.value=rule;select.onchange=e=>{rule=e.target.value;render()};
    const note=document.createElement('p');note.className='caption';note.textContent='Plan-view intersection with the original footprint, using classified lateral segments. Display insets and depth separation do not affect this group. This is a geometric association, not a legal DSU assignment or a formation/bench match.';
    const actions=document.createElement('div');actions.className='dsu-actions';const playButton=document.createElement('button');playButton.className='primary';playButton.textContent='Play group production';playButton.disabled=!shown.length;playButton.onclick=play;const reset=document.createElement('button');reset.textContent='Clear DSU selection';reset.onclick=clear;actions.append(playButton,reset);
    const chart=document.createElement('div');chart.id='dsuProduction';chart.setAttribute('aria-live','polite');
    const list=document.createElement('details'),summary=document.createElement('summary');summary.textContent=`Associated wells (${fmt(shown.length)})`;list.append(summary);const rowsHost=document.createElement('div');rowsHost.className='results dsu-member-list';
    for(const row of shown){const b=document.createElement('button');b.textContent=`Permit ${row.permit} · ${fmt(row.insideFt)} ft inside · ${Math.round(row.fraction*100)}% of mapped lateral`;b.onclick=()=>{const id=row.intersectingBranchIds.find(visible)??row.branchIds.find(visible);selectWell(manifest.wells.find(w=>w.id===id))};rowsHost.append(b)}list.append(rowsHost);
    host.append(title,count,label,select,note,actions,chart,list);notify(rows);
  }
  async function ensure(){
    if(model)return model;if(pending)return pending;const version=generation,m=manifest;
    const next=(async()=>{const hash=await fingerprint;if(hash==='unavailable')throw Error('Open the viewer on localhost to verify the DSU membership snapshot.');const response=await fetch(new URL('./data/dsu/dsu-well-membership.json',import.meta.url));if(!response.ok)throw Error('DSU well membership is not installed for this viewer.');const data=await response.json();if(version!==generation)return null;model=createDSUMembershipModel(data,m,hash);return model})();pending=next;
    try{return await next}finally{if(pending===next)pending=null}
  }
  return {
    setDataset(m,bytes=null){generation++;request++;manifest=m;model=null;pending=null;unit=null;fingerprint=bytes?(globalThis.crypto?.subtle?crypto.subtle.digest('SHA-256',bytes).then(buffer=>Array.from(new Uint8Array(buffer),v=>v.toString(16).padStart(2,'0')).join('')):Promise.resolve('unavailable')):Promise.resolve(null);$('dsuWellDetails').replaceChildren();changed(null)},
    async select(next){if(next&&unit?.id===next.id&&model){unit=next;this.refresh();return}unit=next;const version=++request;$('dsuWellDetails').replaceChildren();changed(null);if(!next||!manifest)return;const message=document.createElement('p');message.className='caption';message.textContent='Finding surveyed laterals in this spacing unit…';$('dsuWellDetails').append(message);try{await ensure();if(version===request&&unit===next)render()}catch(e){if(version===request){message.textContent=e.message;changed(null)}}},
    refresh(){if(unit&&model)try{render()}catch(e){$('dsuWellDetails').textContent=e.message;changed(null)}},
    selection(){return unit&&model?{unit,rows:model.rows(unit.id,rule)}:null}
  };
}
