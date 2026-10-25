// The public static edition intentionally has no raw LAS/API dependency.
export function createGammaController(){
  const explain=()=>{const status=document.getElementById('gammaStatus');if(status)status.textContent='GR and CBL overlays are available in the local viewer. This public release includes well surveys, production and footage scenarios.';const hover=document.getElementById('gammaHover');if(hover)hover.hidden=true;};
  const noop=()=>{};explain();
  return {load:async()=>explain(),reset:explain,setPermitFilter:noop,selected:noop,
    enabled:()=>false,contextVisible:()=>true,intersection:()=>null,hover:noop,
    focus:noop,limits:()=>null,group:null};
}
