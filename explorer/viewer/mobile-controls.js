// Compact touch controls share the existing viewer controllers and data state.
export function createMobileControls({surveyColors,production,dsu,footage,setWellContext=()=>{}}){
  const $=id=>document.getElementById(id),media=matchMedia('(max-width:800px)');
  const viewport=$('viewport'),toolbar=viewport.querySelector('.view-top');
  let collapsed=!production.enabled(),previousProductionEnabled=production.enabled();
  function sync(){
    const colorReady=!$('surveyColorMode').disabled;
    for(const [id,mode] of [['mobileSections','section'],['mobileOperators','operator']]){
      $(id).disabled=!colorReady||(mode==='operator'&&!surveyColors.operatorModel());
      $(id).setAttribute('aria-pressed',String(surveyColors.mode()===mode));
    }
    $('mobileDSU').setAttribute('aria-pressed',String($('dsuEnabled').checked));
    $('mobileTownships').setAttribute('aria-pressed',String(footage.townshipVisible()));
    const ready=production.ready();
    $('mobileProductionToggle').disabled=!ready;
    for(const id of ['mobileProductionToggle','mobileProductionPanelToggle']){
      $(id).setAttribute('aria-expanded',String(!collapsed));
      $(id).textContent=collapsed?'Show production':'Hide production';
    }
    $('mobileProductionToggle').title=ready?'Show or hide playback without changing lateral sizes':$('productionStatus').textContent;
    document.documentElement.classList.toggle('mobile-production-collapsed',collapsed);
  }
  function setCollapsed(value){
    collapsed=!!value;
    if(media.matches&&collapsed)production.pause();
    if(!collapsed&&production.ready()&&!production.enabled())production.setEnabled(true);
    sync();
  }
  $('mobileSections').onclick=()=>{setWellContext('normal');surveyColors.setMode('section')};
  $('mobileOperators').onclick=()=>{setWellContext('normal');surveyColors.setMode('operator')};
  $('mobileDSU').onclick=()=>{dsu.setVisible(!$('dsuEnabled').checked);sync()};
  $('mobileTownships').onclick=()=>{footage.setTownshipVisible(!footage.townshipVisible());sync()};
  for(const id of ['mobileProductionToggle','mobileProductionPanelToggle'])$(id).onclick=()=>setCollapsed(!collapsed);
  $('mobileProductionHide').onclick=()=>{setCollapsed(true);$('mobileProductionToggle').focus()};
  document.addEventListener('viewer:layers-changed',sync);
  document.addEventListener('viewer:production-changed',()=>{
    const enabled=production.enabled();
    if(enabled&&!previousProductionEnabled)collapsed=false;
    if(!enabled)collapsed=true;
    previousProductionEnabled=enabled;sync();
  });
  document.addEventListener('viewer:production-play',()=>{if(media.matches)setCollapsed(false)});
  for(const id of ['dsuEnabled','footageEnabled','footageLayer','dsuColor'])$(id).addEventListener('change',sync);
  function resize(){
    sync();
  }
  media.addEventListener('change',resize);
  new ResizeObserver(()=>{
    viewport.style.setProperty('--mobile-toolbar-bottom',`${Math.ceil(toolbar.offsetTop+toolbar.offsetHeight+10)}px`);
  }).observe(toolbar);
  resize();
  return {sync};
}
