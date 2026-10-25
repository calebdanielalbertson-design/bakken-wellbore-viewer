// Organize the existing viewer controls without duplicating their state or event handlers.
export function createSidebarController({surveyColors,production,dsu,footage,setWellContext=()=>{},resetView=()=>{},getSelection=()=>null,setSelectionTarget=()=>{},getSelectionTarget=()=> 'well',configureArea=()=>{}}){
  const $=id=>document.getElementById(id),aside=document.querySelector('main > aside');
  if(!aside)return {sync(){},setTab(){}};
  const make=(tag,className='',text='')=>{const node=document.createElement(tag);node.className=className;if(text)node.textContent=text;return node};
  const move=(host,...nodes)=>{for(const node of nodes.flat())if(node)host.append(node);return host};
  const labelFor=id=>document.querySelector(`label[for="${id}"]`);
  const field=(host,id)=>move(host,labelFor(id),$(id));
  const disclosure=(title,id)=>{const node=make('details','sidebar-disclosure');if(id)node.id=id;node.append(make('summary','',title));return node};
  const hideLegacy=node=>{if(node)node.classList.add('sidebar-legacy-control')};
  const existing={search:$('wellSearchPanel'),colors:document.querySelector('.survey-color-controls'),operator:$('operatorControls'),metric:$('surveyColorDetails'),gamma:document.querySelector('.gamma-controls'),reference:document.querySelector('.reference-controls'),context:document.querySelector('.well-context-controls'),dsu:document.querySelector('.dsu-controls'),footage:document.querySelector('.footage-controls'),production:$('productionPanel')};
  const shell=make('div','sidebar-shell'),head=make('div','sidebar-head'),scroll=make('div','sidebar-scroll');
  const heading=make('div','sidebar-heading');heading.append(make('h1','','Explore the Bakken'),make('span','sidebar-heading-note','3D well viewer'));head.append(heading,existing.search);
  const filterChip=make('div','sidebar-filter-chip'),filterText=make('span'),clearFilter=make('button','','Clear filter');filterChip.id='sidebarActiveFilter';clearFilter.id='sidebarClearOperator';clearFilter.type='button';clearFilter.addEventListener('click',()=>{$('operatorAll')?.click();queueSync()});filterChip.append(filterText,clearFilter);head.append(filterChip);

  const selectionCard=make('section','sidebar-selection');selectionCard.id='sidebarSelectionCard';selectionCard.setAttribute('aria-label','Selected item');
  const selectionKind=make('div','eyebrow'),selectionTitle=make('strong','sidebar-selection-title'),selectionHint=make('p','caption','Search above or click a well path to inspect it.');
  const selectionActions=make('div','sidebar-selection-actions'),zoom=make('button','primary','Zoom to selection'),clear=make('button','','Clear');zoom.type=clear.type='button';zoom.id='sidebarZoomSelection';clear.id='sidebarClearSelection';selectionActions.append(zoom,clear);
  const selectionDetails=disclosure('Details & production','sidebarSelectionDetails');
  const inspectors={well:make('div','sidebar-inspector'),dsu:make('div','sidebar-inspector'),township:make('div','sidebar-inspector')};
  move(inspectors.well,$('selection'),$('clearSelection'));move(inspectors.dsu,$('dsuSelection'),$('dsuOverlaps'),$('dsuWellDetails'));move(inspectors.township,$('footageSelection'));
  selectionDetails.append(...Object.values(inspectors));selectionCard.append(selectionKind,selectionTitle,selectionHint,selectionActions,selectionDetails);head.append(selectionCard);
  zoom.addEventListener('click',()=>getSelection()?.zoom?.());clear.addEventListener('click',()=>{getSelection()?.clear?.();sync()});

  const targetRow=make('div','sidebar-pick-row'),targetLabel=make('label','','Map clicks select'),target=make('select');target.id='sidebarPickTarget';targetLabel.htmlFor=target.id;
  for(const [value,text] of [['well','Wells'],['dsu','DSUs'],['township','Townships']]){const option=make('option','',text);option.value=value;target.append(option)}
  target.addEventListener('change',()=>{setSelectionTarget(target.value);sync()});targetRow.append(targetLabel,target);head.append(targetRow);
  const tablist=make('div','sidebar-tabs');tablist.setAttribute('role','tablist');tablist.setAttribute('aria-label','Viewer tools');const panels={},tabs={};
  for(const [key,title] of [['wells','Wells'],['areas','Areas'],['production','Production']]){
    const button=make('button','sidebar-tab',title);button.type='button';button.id=`sidebarTab-${key}`;button.setAttribute('role','tab');button.setAttribute('aria-controls',`sidebarPanel-${key}`);tabs[key]=button;tablist.append(button);
    const panel=make('section','sidebar-tabpanel');panel.id=`sidebarPanel-${key}`;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id);panels[key]=panel;scroll.append(panel);button.addEventListener('click',()=>setTab(key));
    button.addEventListener('keydown',event=>{const keys=Object.keys(tabs),index=keys.indexOf(key);let next;if(event.key==='ArrowRight')next=keys[(index+1)%keys.length];if(event.key==='ArrowLeft')next=keys[(index+keys.length-1)%keys.length];if(event.key==='Home')next=keys[0];if(event.key==='End')next=keys.at(-1);if(next){event.preventDefault();setTab(next);tabs[next].focus()}});
  }
  head.append(tablist);

  // Wells: one color control, its legend, and an operator filter in every color mode.
  const operatorLegend=$('operatorLegend')?.closest('details'),operatorNotes=disclosure('Operator attribution');
  if(existing.operator){
    for(const node of [...existing.operator.children])if(node.matches('p')&&node.id!=='operatorFilterSummary')operatorNotes.append(node);
    const opLabel=labelFor('operatorFilter');if(opLabel)opLabel.textContent='Filter wells by operator';
    move(operatorNotes,existing.operator.querySelector('.operator-actions'));
  }
  const colorHead=existing.colors?.querySelector('.section-head h2');if(colorHead)colorHead.textContent='Color well paths by';
  const sectionLegend=make('div','sidebar-section-legend');sectionLegend.id='sidebarSectionLegend';
  const sectionHeading=$('allSections')?.closest('.section-head');move(sectionLegend,sectionHeading,$('legend'),$('uturnLegend'));
  const sectionFilterSlot=make('div','sidebar-section-filter-slot');
  const wellAdvanced=disclosure('Advanced well display','sidebarWellsAdvanced');
  const trajectory=$('trajectoryShapes')?.closest('label');move(wellAdvanced,trajectory,$('shapeStatus'),sectionFilterSlot,operatorNotes);
  const metricCustomize=existing.metric?.querySelector('details');if(metricCustomize){metricCustomize.querySelector('summary').textContent='Custom color scales';move(wellAdvanced,metricCustomize)}
  if(existing.colors)move(existing.colors,sectionLegend,operatorLegend);
  move(panels.wells,existing.operator,existing.colors,wellAdvanced);
  if(existing.gamma){const logs=disclosure('Well log availability','sidebarLogs');logs.append(existing.gamma);panels.wells.append(logs)}

  // Areas: one geography choice; existing DSU and footage controllers remain authoritative.
  const areaIntro=make('p','sidebar-intro','Explore spacing units and township development scenarios.');
  const areaLabel=make('label','field','Show areas'),area=make('select');area.id='sidebarAreaLayer';areaLabel.htmlFor=area.id;
  for(const [value,text] of [['none','No area overlay'],['dsu','Drilling spacing units (DSUs)'],['township','Townships']]){const option=make('option','',text);option.value=value;area.append(option)}
  area.addEventListener('change',()=>{configureArea(area.value);sync()});panels.areas.append(areaIntro,areaLabel,area);
  const areaMessage=make('p','caption sidebar-area-hint','Choose an area layer to compare acreage or development.');panels.areas.append(areaMessage);
  const areaAdvanced=disclosure('Advanced area display & assumptions','sidebarAreasAdvanced');
  const dsuDetails=$('dsuDetails'),footageDetails=$('footageDetails');
  const dsuColors=make('div','sidebar-dsu-colors');dsuColors.id='sidebarDSUColors';
  field(dsuColors,'dsuColor');move(dsuColors,$('dsuColorbar'),$('dsuAcreageLegend'),$('dsuLegend'),$('dsuModelNote'));
  const dsuSearch=make('div','sidebar-dsu-search');dsuSearch.id='sidebarDSUSearch';field(dsuSearch,'dsuSearch');move(dsuSearch,$('dsuResults'));
  const approximate=dsuDetails?.querySelector('.dsu-approximation');
  const dsuAdvanced=make('div','sidebar-dsu-advanced');dsuAdvanced.id='sidebarDSUAdvanced';
  if(dsuDetails){for(const node of [...dsuDetails.children])if(node!==approximate)dsuAdvanced.append(node);move(dsuDetails,dsuColors,dsuSearch,approximate)}
  hideLegacy($('dsuInspect')?.closest('label'));const inspectionNote=$('dsuInspect')?.closest('label')?.nextElementSibling;if(inspectionNote?.tagName==='P')hideLegacy(inspectionNote);
  const dsuContext=make('div','sidebar-dsu-context');dsuContext.id='sidebarDSUContext';
  const dsuEnabledLabel=$('dsuEnabled')?.closest('label');move(dsuContext,dsuEnabledLabel);if(dsuEnabledLabel?.querySelector('span'))dsuEnabledLabel.querySelector('span').textContent='Also show DSU outlines with townships';
  if(existing.dsu?.querySelector('.section-head'))hideLegacy(existing.dsu.querySelector('.section-head'));
  move(areaAdvanced,dsuContext,dsuAdvanced);

  const metricGroup=make('div','sidebar-township-metric');metricGroup.id='sidebarTownshipMetric';field(metricGroup,'footageMetric');
  const scenarioGroup=make('div','sidebar-scenario');scenarioGroup.id='sidebarScenario';field(scenarioGroup,'footageScenario');
  const footageLegend=make('div','sidebar-footage-legend');move(footageLegend,$('footageColorbar'),$('footageLegend'));
  const townships=$('townshipControls');hideLegacy($('townshipInspect')?.closest('label'));
  hideLegacy($('footageEnabled')?.closest('label'));hideLegacy(labelFor('footageLayer'));hideLegacy($('footageLayer'));
  if(existing.footage?.querySelector('.section-head'))hideLegacy(existing.footage.querySelector('.section-head'));
  const inventoryNotes=disclosure('Capacity assumptions & data limits','sidebarInventoryNotes');
  if(footageDetails){for(const node of [...footageDetails.children])if(node!==townships){if(node.matches('details'))areaAdvanced.append(node);else if(!node.classList.contains('sidebar-legacy-control'))inventoryNotes.append(node)}move(footageDetails,metricGroup,scenarioGroup,footageLegend,townships)}
  const inventoryCaveat=make('p','caption sidebar-inventory-caveat','Scenario headroom, not verified drillable locations. Includes all surveyed operators; overlapping DSU totals must not be added.');
  const scenarioCaveat=make('p','caption','Low / Base / High are editable capacity assumptions, not forecasts.');scenarioGroup.append(scenarioCaveat);
  move(areaAdvanced,inventoryNotes);
  move(panels.areas,existing.dsu,existing.footage,inventoryCaveat,existing.context,areaAdvanced);
  const contextCaption=existing.context?.querySelector('.caption');if(contextCaption)contextCaption.textContent='Use faint gray or hide paths to make area colors easier to read.';

  // Production is opt-in; opening this tab never changes playback or enabled state.
  const productionIntro=make('p','sidebar-intro','Compare reported monthly oil and follow its changes over time.');panels.production.append(productionIntro);move(panels.production,existing.production);
  const sizeDetails=disclosure('Display size & legend','sidebarProductionSize');
  const sizeLabel=labelFor('productionSize'),sizeInput=$('productionSize'),sizeOutput=$('productionSizeValue'),productionLegend=$('productionLegend');
  const widthNote=productionLegend?.nextElementSibling;move(sizeDetails,sizeLabel,sizeInput,sizeOutput,productionLegend);if(widthNote?.tagName==='P')sizeDetails.append(widthNote);
  $('productionDetails')?.append(sizeDetails);
  const productionTip=make('p','caption','Playback appears over the map when the overlay is enabled. Select a well or DSU for its reported history in Details & production.');panels.production.append(productionTip);

  // View tools and dataset provenance stay accessible below the task panels.
  const stateFit=$('fitState'),cameraButtons=document.querySelector('.view-buttons');if(stateFit&&cameraButtons){stateFit.textContent='North Dakota';stateFit.setAttribute('aria-label','Fit all of North Dakota');cameraButtons.append(stateFit)}
  const settings=disclosure('View & dataset settings','sidebarSettings'),viewSettings=make('div','sidebar-view-settings');move(viewSettings,existing.reference);
  const scale=$('scale'),scaleCaption=scale?.nextElementSibling,scaleHeading=$('scaleValue')?.closest('.section-head');move(viewSettings,scaleHeading,scale,scaleCaption);settings.append(viewSettings);
  const dataDetails=disclosure('Dataset & sources','sidebarDataset');
  const datasetActions=make('div','sidebar-dataset-actions');move(datasetActions,$('sample'),$('folder')?.closest('label'));dataDetails.append(datasetActions);
  for(const node of [...aside.children]){
    if(node.matches('.eyebrow,h1'))continue;
    dataDetails.append(node);
  }
  settings.append(dataDetails);scroll.append(settings);
  const footer=make('div','sidebar-footer'),stateSummary=make('p','caption'),reset=make('button','sidebar-reset','Reset view & filters');stateSummary.id='sidebarStateSummary';stateSummary.setAttribute('aria-live','polite');reset.id='sidebarReset';reset.type='button';reset.addEventListener('click',()=>{resetView();setTab('wells');selectionDetails.open=false;sync()});footer.append(stateSummary,reset);
  aside.replaceChildren(shell);aside.classList.add('viewer-sidebar');shell.append(head,scroll,footer);document.documentElement.classList.add('unified-sidebar');

  let activeTab='wells',previousSelection='',scheduled=false;
  function setTab(key){
    if(!panels[key])return;
    activeTab=key;for(const name of Object.keys(tabs)){const active=name===key;tabs[name].setAttribute('aria-selected',String(active));tabs[name].tabIndex=active?0:-1;panels[name].hidden=!active}
    scroll.scrollTop=0;
  }
  function sync(){
    const selected=getSelection(),kind=selected?.kind||'',signature=selected?`${kind}:${selected.label}`:'';
    if(signature!==previousSelection){selectionDetails.open=false;previousSelection=signature}
    selectionCard.classList.toggle('has-selection',!!selected);selectionKind.textContent=selected?`Selected ${kind==='dsu'?'DSU':kind}`:'INSPECT THE MAP';selectionTitle.textContent=selected?.label||'';selectionTitle.hidden=!selected;
    selectionHint.hidden=!!selected;selectionActions.hidden=!selected;selectionDetails.hidden=!selected;
    for(const name of Object.keys(inspectors))inspectors[name].hidden=kind!==name;
    const choice=getSelectionTarget();target.value=['well','dsu','township'].includes(choice)?choice:'well';
    const townVisible=!!footage?.townshipVisible?.(),dsuVisible=!!$('dsuEnabled')?.checked,layer=townVisible?'township':dsuVisible?'dsu':'none';
    area.value=layer;areaMessage.hidden=layer!=='none';
    for(const option of target.options)option.disabled=option.value==='dsu'?!dsuVisible:option.value==='township'?!townVisible:false;
    const mode=surveyColors?.mode?.()||$('surveyColorMode')?.value||'section';
    if(mode==='section'){if(sectionLegend.parentNode!==existing.colors)existing.colors.append(sectionLegend)}else if(sectionLegend.parentNode!==sectionFilterSlot)sectionFilterSlot.append(sectionLegend);
    if(operatorLegend)operatorLegend.hidden=mode!=='operator';
    if(metricCustomize)metricCustomize.hidden=mode==='section'||mode==='operator';
    if(existing.operator){existing.operator.hidden=false;const ready=!!surveyColors?.operatorModel?.();$('operatorFilter').disabled=!ready;$('operatorFit').disabled=!ready;$('operatorAll').disabled=!ready}
    dsuColors.hidden=layer!=='dsu';dsuSearch.hidden=layer!=='dsu';dsuContext.hidden=layer!=='township';dsuAdvanced.hidden=!dsuVisible;
    if(existing.dsu)existing.dsu.hidden=!dsuVisible;if(existing.footage)existing.footage.hidden=layer==='none';
    metricGroup.hidden=layer!=='township';footageLegend.hidden=layer!=='township';
    const scenarioActive=layer==='township'||(layer==='dsu'&&$('dsuColor').value.startsWith('footage-'));
    scenarioGroup.hidden=!scenarioActive;inventoryCaveat.hidden=!scenarioActive;areaAdvanced.hidden=layer==='none';
    const operator=$('operatorFilter'),operatorFiltered=operator&&operator.value!=='all';filterChip.hidden=!operatorFiltered;const filterLabel=operatorFiltered?operator.options[operator.selectedIndex]?.textContent||'Operator filter':'';if(filterText.textContent!==filterLabel)filterText.textContent=filterLabel;if($('operatorFilterSummary'))$('operatorFilterSummary').hidden=!operatorFiltered&&mode!=='operator';
    const state=[];if(operatorFiltered)state.push(operator.options[operator.selectedIndex]?.textContent||'Operator filter');if(layer!=='none')state.push(layer==='dsu'?'DSUs visible':dsuVisible?'Townships + DSUs':'Townships visible');if(production?.enabled?.())state.push('Oil overlay on');state.push(`Select ${target.options[target.selectedIndex]?.textContent?.toLowerCase()||'wells'}`);
    const text=state.join(' · ');if(stateSummary.textContent!==text)stateSummary.textContent=text;
    footer.classList.toggle('has-filter',!!operatorFiltered);
  }
  function queueSync(){if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;sync()})}
  document.addEventListener('change',queueSync);
  for(const name of ['viewer:layers-changed','viewer:production-changed','viewer:selection-changed'])document.addEventListener(name,queueSync);
  for(const id of ['selection','dsuSelection','footageSelection','operatorLegend'])if($(id))new MutationObserver(queueSync).observe($(id),{childList:true,subtree:true,characterData:true});
  const params=new URLSearchParams(location.search);setTab(params.has('inventory')||params.has('dsu')?'areas':['1','on','true'].includes(params.get('production'))?'production':'wells');sync();
  return {sync,setTab};
}
