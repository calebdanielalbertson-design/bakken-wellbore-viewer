const fmt=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:0});
export function renderScopeHistory(host,{title,totalWells,matchedWells,months,summaries,period,month}){
  host.replaceChildren();const heading=document.createElement('h4');heading.textContent=title+' · combined oil';host.append(heading);
  if(!matchedWells){const empty=document.createElement('p');empty.className='caption';empty.textContent=`No production matches for the ${fmt(totalWells)} selected wells.`;host.append(empty);return}
  const current=summaries[month],value=document.createElement('p');value.className='production-well-value';value.textContent=`${months[month]}: ${current.reported?fmt(current.barrels)+' bbl reported':'No reported values'}`;host.append(value);
  const coverage=document.createElement('p');coverage.className='caption';coverage.textContent=`${fmt(current.reported)} of ${fmt(matchedWells)} matched wells reported this month · ${fmt(totalWells-matchedWells)} selected wells have no production match.`;host.append(coverage);
  let peak=0,reportedMonths=0,cumulative=0,partial=0;
  for(let i=period.start;i<=period.end;i++){const s=summaries[i];if(s.reported){peak=Math.max(peak,s.barrels);cumulative+=s.barrels;reportedMonths++;if(s.reported<matchedWells)partial++}}
  if(reportedMonths){
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),x=i=>8+(i-period.start)/Math.max(1,period.end-period.start)*244,y=v=>99-v/Math.max(1,peak)*70;
    svg.setAttribute('viewBox','0 0 260 128');svg.setAttribute('role','img');svg.setAttribute('aria-label',title+' combined monthly oil; gaps mean no reports, partial months sum reported wells only.');svg.classList.add('production-chart');
    let path='',open=false;for(let i=period.start;i<=period.end;i++){const s=summaries[i];if(!s.reported){open=false;continue}path+=`${open?'L':'M'}${x(i).toFixed(2)},${y(s.barrels).toFixed(2)} `;open=true;const dot=document.createElementNS(ns,'circle');for(const [k,v] of Object.entries({cx:x(i),cy:y(s.barrels),r:1.5,fill:s.reported<matchedWells?'#ffc475':'#86ece5'}))dot.setAttribute(k,v);const tip=document.createElementNS(ns,'title');tip.textContent=`${months[i]}: ${fmt(s.barrels)} bbl · ${s.reported}/${matchedWells} wells reported`;dot.append(tip);svg.append(dot)}
    const curve=document.createElementNS(ns,'path');for(const [k,v] of Object.entries({d:path,fill:'none',stroke:'#86ece5','stroke-width':1.5}))curve.setAttribute(k,v);svg.append(curve);
    const cursor=document.createElementNS(ns,'line');for(const [k,v] of Object.entries({x1:x(month),x2:x(month),y1:20,y2:102,stroke:'#e5f0f6','stroke-dasharray':'3 3'}))cursor.setAttribute(k,v);svg.append(cursor);
    for(const [text,px,py,anchor] of [[`Peak ${fmt(peak)} bbl/month`,8,13,'start'],[months[period.start],8,119,'start'],[months[period.end],252,119,'end']]){const t=document.createElementNS(ns,'text');for(const [k,v] of Object.entries({x:px,y:py,fill:'#a2bfce','font-size':10,'text-anchor':anchor}))t.setAttribute(k,v);t.textContent=text;svg.append(t)}host.append(svg);
  }
  const total=document.createElement('p');total.className='caption';total.textContent=reportedMonths?`Reported oil in this period: ${fmt(cumulative)} bbl. ${partial?'Amber dots mark months with incomplete well reporting. ':''}`:'No reported values in this playback period.';host.append(total);
  const note=document.createElement('p');note.className='caption';note.textContent='Whole-well oil across reported pools, counted once per well. Volumes are not prorated to the part of the lateral inside the DSU. Overlapping DSU totals must not be added together. Gaps are missing data, not zero production. Use the monthly timeline to scrub or play.';host.append(note);
}
