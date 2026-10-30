const fmt=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:1});
const EVENTS={spacing:'Spacing / density',pooling:'Pooling',conflict:'Conflicting same-day values',zone:'Pool zone table',termination:'Unit terminated',density:'Increased density'};

// Attach dsu-orders.json entries to prepared DSU units as unit.orders. Returns the file's metadata.
export function attachDSUOrders(units,data){
  if(data?.version!==1||!data.units||typeof data.units!=='object')throw Error('Invalid DSU order link file.');
  if(data.dsu?.featureCount!==units.length)throw Error('DSU order links were prepared for a different DSU snapshot. Rebuild dsu-orders.json.');
  const byId=new Map(units.map(u=>[u.id,u]));
  for(const id of Object.keys(data.units))if(!byId.has(id))throw Error('DSU order links reference a DSU that is not installed. Rebuild dsu-orders.json.');
  for(const unit of units)unit.orders=data.units[unit.id]??null;
  return {atlas:data.atlas,summary:data.summary,linked:Object.keys(data.units).length};
}

// Attach dsu-headroom.json entries as unit.headroom. Returns totals and rollups.
export function attachDSUHeadroom(units,data){
  if(data?.version!==1||!data.units||!data.rollups)throw Error('Invalid DSU headroom file.');
  if(data.dsu?.featureCount!==units.length)throw Error('Remaining-well file was prepared for a different DSU snapshot. Rebuild dsu-headroom.json.');
  const byId=new Map(units.map(u=>[u.id,u]));
  for(const id of Object.keys(data.units))if(!byId.has(id))throw Error('Remaining-well file references a DSU that is not installed. Rebuild dsu-headroom.json.');
  for(const unit of units)unit.headroom=data.units[unit.id]??null;
  return {totals:data.totals,rollups:data.rollups,survey:data.survey};
}

export const ROLLUP_FIELDS={county:'county',operator:'holder',pool:'pool'};

export function rollupTable(meta,by,{choose=null,active=null}={}){
  const host=el('div','dsu-rollup');const rows=meta?.rollups?.[by]||[];
  const table=el('table');const head=el('tr');
  for(const label of [by==='operator'?'Operator':by==='pool'?'Pool':'County','Units','Allowed','Drilled','Pending','Room'])head.append(el('th','',label));
  table.append(head);
  for(const r of rows.slice(0,40)){
    const tr=el('tr',r.name===active?'active':'');
    for(const v of [r.name,r.units,r.allowed,r.assignedWells,r.pending,r.remainingAfterPending])tr.append(el('td','',typeof v==='number'?fmt(v):v));
    if(choose){tr.tabIndex=0;tr.onclick=()=>choose(r.name);tr.onkeydown=e=>{if(e.key==='Enter')choose(r.name)}}
    table.append(tr);
  }
  host.append(table);
  if(rows.length>40)host.append(el('p','caption',`${fmt(rows.length-40)} smaller groups not shown.`));
  return host;
}

export function headroomTotals(meta){
  const t=meta?.totals;if(!t)return '';
  return `${fmt(t.remainingAfterPending)} wells of room after ${fmt(t.pending)} pending permits (${fmt(t.remaining)} before) across ${fmt(t.unitsWithRoom)} of ${fmt(t.units)} units with a single stated allowance. Conservative lower bound, counting shared wells in every unit: ${fmt(t.remainingConservative)}. ${fmt(t.overAllowance)} wells sit in units already over their allowance. Surveys ${meta.survey?.sourceDate||''}. Click a row to show only its units.`;
}

const REVIEW={overlapping_unit_small_allowance:'This large overlapping unit is authorized for one or two wells; the underlying units likely have orders not linked yet, so their wells count here.',
  over_allowance:'More surveyed wells than the latest linked order allows. A later or overlapping order may govern, or the extraction missed one.'};
function headroomBlock(h){
  const box=el('div','dsu-headroom-card');
  box.append(el('h4','',h.assignedBalance>=0?`Room for ${fmt(h.assignedBalance)} more well${h.assignedBalance===1?'':'s'}`:`${fmt(-h.assignedBalance)} well${h.assignedBalance===-1?'':'s'} over the allowance`));
  const dl=document.createElement('dl');
  for(const [label,value] of [['Bakken wells ≥ 660 ft inside',fmt(h.wellsInside)],['Counted here for rollups',fmt(h.assignedWells)],['Pending permits (surface location)',fmt(h.pending)],['Operator',h.holder?`${h.holder}${h.holderSource==='order applicant'?' · order applicant':''}`:'Unknown'],['County',h.county||'Unknown']])dl.append(el('dt','',label),el('dd','',value));
  box.append(dl);
  if(h.wellsInside!==h.assignedWells)box.append(el('p','caption','Some wells here also cross an overlapping unit; each well counts in only one unit for statewide totals.'));
  if(h.review)box.append(el('p','caption dsu-review',REVIEW[h.review]));
  return box;
}

export function orderSearchText(unit){
  return unit.orders?unit.orders.footprints.flatMap(f=>f.history.map(h=>`${h.order} ${h.case}`)).join(' '):'';
}

function el(tag,className,text){const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node}
function orderRef(row,documentUrl){
  const label=`Order ${row.order}`;
  if(!documentUrl||!row.documentId)return el('span','',label);
  const a=el('a','',label);a.href=documentUrl(row.documentId);a.target='_blank';a.rel='noopener';return a;
}

export function ordersPanel(unit,{documentUrl=null,meta=null}={}){
  const host=el('section','dsu-orders');host.append(el('div','eyebrow','NDIC ORDERS'));
  const entry=unit.orders;
  if(!entry){host.append(el('p','caption',meta?'No processed order footprint matches this DSU. It may be governed by an order not yet processed or without an explicit land description.':'Order links are not installed. Build dsu-orders.json with prepare_dsu_orders.py.'));return host}
  const a=entry.allowance,p=unit.properties,inv=p.inventory;
  const headline=el('h3','',a?.wells!=null?`Latest order allows ${fmt(a.wells)} well${a.wells===1?'':'s'}`:'Latest order states no single allowance');
  const source=el('p','dsu-order-source');
  if(a){source.append(orderRef({order:a.order,documentId:entry.footprints.flatMap(f=>f.history).find(h=>h.order===a.order)?.documentId},documentUrl),` · Case ${a.case||'—'} · ${a.date||'undated'}${a.qualifier==='maximum'?' · stated as a maximum':''}`)}
  host.append(headline,source);
  if(a?.mixed)host.append(el('p','caption','Linked footprints state different allowances (for example, separate pools). The most recent order is shown.'));
  if(unit.headroom)host.append(headroomBlock(unit.headroom));
  const dl=document.createElement('dl');
  const rows=[['Model capacity · Sep 12',inv?.matched&&inv.estimatedCapacity!=null?fmt(inv.estimatedCapacity)+' wells':'Unavailable'],
              ['Model assigned wells',inv?.matched&&inv.assignedWells!=null?fmt(inv.assignedWells):'Unavailable']];
  if(!unit.headroom&&a?.wells!=null&&inv?.matched&&inv.assignedWells!=null)rows.push(['Order allowance − assigned',fmt(Math.max(0,a.wells-inv.assignedWells))+' wells']);
  for(const [label,value] of rows){dl.append(el('dt','',label),el('dd','',value))}
  host.append(dl);
  for(const fp of entry.footprints){
    const details=document.createElement('details'),summary=el('summary','',`${fp.pool||'Pool unknown'} · ${fp.zone||'no zone'} · ${fmt(fp.acres)} ac · ${fp.match} match (${Math.round(fp.iou*100)}% overlap)`);
    details.append(summary);const list=el('ol','dsu-order-history');
    for(const h of [...fp.history].reverse()){
      const li=el('li');li.append(el('span','',h.date||'undated'),' · ',orderRef(h,documentUrl),` · ${EVENTS[h.event]||h.event||'event'}`,h.wells!=null?` · ${fmt(h.wells)} wells${h.viaOrder?' (carried from order '+h.viaOrder+')':''}`:'');list.append(li);
    }
    details.append(list);host.append(details);
  }
  host.append(el('p','caption',`Machine-extracted from order text${meta?.atlas?.built?' · atlas '+meta.atlas.built.slice(0,10):''}; not human-reviewed. A stated allowance is not proof the order governs today or that locations are drillable.`));
  return host;
}
