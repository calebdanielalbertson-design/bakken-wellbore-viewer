const $=id=>document.getElementById(id),apiBase='';
let meta=null,kind='notices',offset=0,total=0,selectedKey='',request=0,selectionRequest=0,controller=null;
const limit=6,number=v=>Number(v).toLocaleString('en-US');
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node};
const readable=value=>String(value??'').replace(/[_-]+/g,' ').trim();
const date=value=>{if(!value)return 'Date unavailable';const d=new Date(String(value).slice(0,10)+'T12:00:00Z');return Number.isNaN(d.valueOf())?String(value):d.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'})};
function publicURL(value){try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null}catch{return null}}
async function get(path,signal){const res=await fetch(apiBase+path,{signal,cache:'no-store'});const body=await res.json();if(!res.ok)throw Error(body.error?.message||'The saved research data could not be loaded.');return body}
function recordTitle(row){return row.title||row.wellName||(row.orderNo?'Order '+row.orderNo:null)||row.noticeType||'Source record'}
function landLabel(row,limit=3){const lands=row.lands||[];return lands.slice(0,limit).map(land=>[land.township&&land.range_number?`T${land.township}${land.tdir||''} R${land.range_number}${land.rdir||''}`:null,land.section?'Sec '+land.section:null,land.extent&&land.extent!=='whole_section'?readable(land.extent):null].filter(Boolean).join(' · ')).filter(Boolean).join('; ')+(lands.length>limit?` (+${lands.length-limit} more land entries)`:'')}
function recordType(row){return kind==='orders'?row.reviewStatus||'Review status unavailable':row.noticeType||'Notice type unavailable'}
function candidate(row){return /candidate|unreviewed|automatic/i.test(row.reviewStatus||'')}
function optionList(id,values,first){const host=$(id);host.replaceChildren();const all=el('option',first);all.value='';host.append(all);for(const value of values||[]){const option=el('option',readable(value));option.value=value;host.append(option)}}
function resetInspector(){selectionRequest++;selectedKey='';$('inspector').replaceChildren(el('p','Record inspector','eyebrow'),el('h3','Keep the evidence in view.'),el('p','Select a record to inspect its reported details, source reference, and review limits.'),el('div','↗','empty-symbol'))}
function changeTab(next){
  kind=next;for(const button of document.querySelectorAll('.research-tabs button')){const active=button.dataset.kind===kind;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1}
  const sources=kind==='sources';$('recordsPanel').hidden=sources;$('sourcesPanel').hidden=!sources;
  if(sources){controller?.abort();request++;return}
  $('recordsPanel').setAttribute('aria-labelledby','tab-'+kind);$('query').value='';offset=0;
  optionList('operator',meta.operators[kind],'All names');optionList('recordType',meta.types[kind],kind==='orders'?'All review stages':'All notice types');
  $('typeLabel').textContent=kind==='orders'?'Evidence review stage':'Reported notice type';$('registerTitle').textContent=kind==='orders'?'Historical order evidence':'Reported well activity';
  $('scopeNote').textContent=kind==='orders'?'A selected historical sample: checked pilot evidence and candidate extractions are labeled separately. Present applicability has not been established.':'A selected sample of saved daily-report notices. Report publication dates are shown here; notice dates do not establish actual event dates. This is not a current activity feed.';
  resetInspector();loadRows();
}
async function loadRows(){
  if(kind==='sources')return;controller?.abort();controller=new AbortController();const token=++request;
  $('resultCount').textContent='Searching…';$('previousPage').disabled=true;$('nextPage').disabled=true;
  const params=new URLSearchParams({kind,q:$('query').value.trim(),operator:$('operator').value,type:$('recordType').value,offset:String(offset),limit:String(limit)});
  try{const data=await get('/api/forward/records?'+params,controller.signal);if(token!==request)return;total=data.total;offset=data.offset;
    $('resultCount').textContent=number(total)+' matching sample record'+(total===1?'':'s');$('recordList').replaceChildren();
    for(const row of data.rows){const key=kind+':'+row.id,button=el('button',undefined,'record-row');button.type='button';button.setAttribute('aria-pressed',String(selectedKey===key));
      const stamp=el('div',undefined,'record-date');stamp.append(el('strong',date(kind==='orders'?row.date:row.reportDate)),el('span',kind==='orders'?'document date':'report date'));
      const content=el('div',undefined,'record-content');content.append(el('strong',recordTitle(row)),el('small',[row.operator||row.applicant||'Operator / applicant unavailable',row.permit?'File '+row.permit:null,landLabel(row)||null].filter(Boolean).join(' · ')),el('span',readable(recordType(row)),'record-tag'+(candidate(row)?' candidate':'')));
      button.append(stamp,content,el('span','↗','record-arrow'));button.onclick=()=>{selectedKey=key;for(const sibling of $('recordList').children)sibling.setAttribute('aria-pressed',String(sibling===button));inspect(row)};$('recordList').append(button);
    }
    if(!data.rows.length)$('recordList').append(el('p','No records in this sample match those filters. Try a shorter name or clear the filters.','empty-message'));
    $('pageLabel').textContent=total?`${number(offset+1)}–${number(Math.min(offset+limit,total))} of ${number(total)}`:'0 records';$('previousPage').disabled=offset===0;$('nextPage').disabled=offset+limit>=total;
  }catch(error){if(error.name==='AbortError')return;$('resultCount').textContent='Unavailable';$('recordList').replaceChildren(el('p',error.message,'error-box'));$('pageLabel').textContent=''}
}
function fact(host,label,value){if(value===null||value===undefined||value==='')return;const group=el('div');group.append(el('dt',label),el('dd',String(value)));host.append(group)}
async function inspect(row){
  const token=++selectionRequest,host=$('inspector');host.replaceChildren(el('p',kind==='orders'?'HISTORICAL ORDER RECORD':'REPORTED ACTIVITY','eyebrow'),el('span',readable(recordType(row)),'detail-tag'+(candidate(row)?' candidate':'')),el('h3',recordTitle(row)));
  const facts=el('dl',undefined,'detail-facts');fact(facts,kind==='orders'?'Document date':'Report date',date(kind==='orders'?row.date:row.reportDate));fact(facts,'Date basis',row.dateBasis);fact(facts,'Operator / applicant',row.operator||row.applicant||'Unavailable');fact(facts,'File number',row.permit);fact(facts,'API',row.api);fact(facts,'Order number',row.orderNo);fact(facts,'Case number',row.caseNo);if(kind==='notices')fact(facts,'Reported event date',row.eventDate||'Not specified');fact(facts,'County',row.county);fact(facts,'Source page',row.sourcePage);if(kind==='orders')fact(facts,'Current applicability',readable(row.currentApplicability||'unresolved'));host.append(facts);
  if(landLabel(row)){const lands=el('dl',undefined,'detail-facts');fact(lands,'Historical land description',landLabel(row,Infinity));const provision=row.provisions?.[0];if(provision&&typeof provision==='object'){fact(lands,'Stated unit size',provision.spacingAcres===null||provision.spacingAcres===undefined?null:number(provision.spacingAcres)+' acres');fact(lands,'Stated horizontal well limit',provision.wellLimit)}host.append(lands)}
  if(row.summary)host.append(el('p',row.summary,'evidence-excerpt'));
  if(row.provisions?.length){const list=el('div');for(const provision of row.provisions.slice(0,4)){const text=typeof provision==='string'?provision:provision.text||provision.summary||provision.clause||provision.provisionText;if(text)list.append(el('p',text,'evidence-excerpt'))}host.append(list)}
  for(const evidence of (row.evidence||[]).slice(0,3)){if(evidence.quote){host.append(el('p',evidence.quote,'evidence-excerpt'));if(evidence.page)host.append(el('p','Source evidence · page '+evidence.page,'identity-note'))}}
  host.append(el('p',kind==='orders'?(candidate(row)?'Candidate extraction. Review against the source before relying on it. Present applicability and superseding orders remain unresolved.':'Checked historical evidence. This does not establish current controlling authority, a completed well, or a remaining drilling location.'):'A notice records what a source reported. It does not, by itself, verify present status, rig movement, drilling speed, or a future drilling commitment.','detail-note'));
  const flags=row.reviewFlags||row.qualityFlags;if(flags?.length)host.append(el('p','Review notes: '+flags.map(v=>readable(typeof v==='string'?v:v.type||v.message||'review required')).join(' · '),'identity-note'));
  const actions=el('div',undefined,'detail-actions'),url=publicURL(row.sourceURL);if(url){const link=el('a','Open source ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';actions.append(link)}host.append(actions);
  if(!url)host.append(el('p','A public document URL is not available for this saved record. The source reference is retained; no document link has been inferred.','identity-note'));
  if(url&&row.sourceURLStatus)host.append(el('p',row.sourceURLStatus,'identity-note'));
  if(row.sourceSHA256){const source=el('p','Source fingerprint: '+String(row.sourceSHA256).slice(0,16)+'…','identity-note');source.title=row.sourceSHA256;host.append(source)}
  const back=el('button','← Back to records','inspector-back');back.type='button';back.onclick=()=>$('recordList').closest('.record-register').scrollIntoView({block:'start'});host.prepend(back);
  if(matchMedia('(max-width:800px)').matches)host.scrollIntoView({block:'start'});
  if(row.permit){try{const match=await get('/api/forward/well-link?'+new URLSearchParams({permit:String(row.permit),api:String(row.api||'')}));if(token!==selectionRequest)return;if(match.matched){const link=el('a','View mapped well ↗','primary-action');link.href=match.url;actions.prepend(link);host.append(el('p',match.note,'identity-note'))}else host.append(el('p',match.reason||'No verified match to this viewer snapshot is available.','identity-note'))}catch{if(token===selectionRequest)host.append(el('p','Well-map matching is unavailable for this local session.','identity-note'))}}
}
function renderSources(){
  const snapshot=meta.snapshot||{};$('sourceCards').replaceChildren();
  for(const source of snapshot.sources||[]){const card=el('article',undefined,'source-card');card.append(el('h4',source.name||'Saved source'));if(Number.isFinite(source.recordCount)){card.append(el('strong',number(source.recordCount),'source-count'),el('span','records in this source snapshot','source-caption'))}card.append(el('p',`${number(source.exportedCount||0)} records included in this preview.`));if(source.status)card.append(el('p',readable(source.status)));if(source.note)card.append(el('p',source.note));if(source.dateStart||source.dateEnd)card.append(el('p',[source.dateStart?date(source.dateStart):'Unknown',source.dateEnd?date(source.dateEnd):'Unknown'].join(' → '),'source-dates'));for(const [i,reference]of(source.references||[]).entries()){const url=publicURL(reference.sourceURL);if(url){const link=el('a',`Stored docket source ${i+1} ↗`,'source-reference');link.href=url;link.target='_blank';link.rel='noopener noreferrer';card.append(link)}}$('sourceCards').append(card)}
  $('limitations').replaceChildren();for(const note of snapshot.limitations||[])$('limitations').append(el('li',typeof note==='string'?note:JSON.stringify(note)));
}
for(const button of document.querySelectorAll('.research-tabs button')){button.onclick=()=>changeTab(button.dataset.kind);button.onkeydown=e=>{const tabs=[...document.querySelectorAll('.research-tabs button')],index=tabs.indexOf(button);let target;if(e.key==='ArrowRight')target=tabs[(index+1)%tabs.length];if(e.key==='ArrowLeft')target=tabs[(index+tabs.length-1)%tabs.length];if(e.key==='Home')target=tabs[0];if(e.key==='End')target=tabs.at(-1);if(target){e.preventDefault();target.focus();changeTab(target.dataset.kind)}}}
let timer;$('query').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{offset=0;resetInspector();loadRows()},180)};
$('filters').onsubmit=e=>{e.preventDefault();clearTimeout(timer);offset=0;resetInspector();loadRows()};
for(const id of ['operator','recordType'])$(id).onchange=()=>{offset=0;resetInspector();loadRows()};
$('filters').onreset=()=>{clearTimeout(timer);setTimeout(()=>{offset=0;resetInspector();loadRows()},0)};
$('previousPage').onclick=()=>{offset=Math.max(0,offset-limit);resetInspector();loadRows()};$('nextPage').onclick=()=>{offset+=limit;resetInspector();loadRows()};
try{meta=await get('/api/forward/meta');$('noticeCount').textContent=number(meta.counts.notices);$('orderCount').textContent=number(meta.counts.orders);$('snapshotLabel').textContent=meta.snapshot.label||'Saved local evidence sample';$('backendStatus').textContent=(meta.backend.storage==='postgresql'?'PostgreSQL':'Local SQL')+' · read-only research API';renderSources();changeTab(meta.counts.notices?'notices':'orders')}catch(error){$('snapshotLabel').textContent='Research snapshot unavailable';$('backendStatus').textContent='The backend is not ready.';$('recordList').replaceChildren(el('p',error.message,'error-box'));$('scopeNote').textContent='No data has been substituted. Start the local server after importing the saved snapshot.';$('resultCount').textContent='Unavailable'}
