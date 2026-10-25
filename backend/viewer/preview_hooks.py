"""Fail-closed, local-only timeline guards for the public viewer source.

The published app stays untouched. serve.py may apply transform_app in memory
before its existing local well-profile selection bridge. Exact-count anchors
make upstream changes an explicit review instead of a partly applied patch.
"""
from __future__ import annotations


def _once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"Local timeline hook {label!r} expected one source anchor; found {count}.")
    return text.replace(old, new, 1)


TIMELINE_GUARDS = """
// Local activity preview: independent overlays must respect timeline visibility.
let previewGammaWasDisabled=null;
function syncPreviewGamma(){
  const active=production.activityActive(),toggle=$('gammaEnabled');
  if(active){
    if(toggle&&previewGammaWasDisabled===null)previewGammaWasDisabled=toggle.disabled;
    if(gamma.enabled()){
      if(typeof gamma.setEnabled==='function')gamma.setEnabled(false);
      else if(toggle){toggle.checked=false;toggle.dispatchEvent(new Event('change',{bubbles:true}));}
    }
    if(toggle)toggle.disabled=true;
    if(gamma.group)gamma.group.visible=false;
    const hover=$('gammaHover');if(hover)hover.hidden=true;
  }else if(previewGammaWasDisabled!==null){
    if(toggle)toggle.disabled=previewGammaWasDisabled;
    previewGammaWasDisabled=null;
  }
}
document.addEventListener('viewer:timeline-changed',()=>{
  syncPreviewGamma();
  if(!manifest)return;
  if(selected&&!production.visible(selected))clearSelection();
  renderWellSearch();refreshDSUHighlight();renderSelection();syncGammaContext();
});
"""


def transform_app(text: str) -> str:
    """Adapt the exact public app to the local controller's activity contract.

    Controller additions: activityActive(), visible(w), decorate(line) for every
    section, and load(getter, manifest, manifestBytes). Monthly visibility updates
    are handled by its shader textures; these hooks never rebuild survey geometry.
    """
    if not isinstance(text, str):
        raise TypeError("Viewer source must be text.")
    crlf = "\r\n" in text
    text = text.replace("\r\n", "\n")
    text = _once(text,
        "if(section===4)production.decorate(l);",
        "production.decorate(l);", "decorate-all-sections")
    text = _once(text,
        "await production.load(async(name,json=false)=>{const buffer=await getter(name);return json?JSON.parse(new TextDecoder().decode(buffer)):buffer},m);",
        "await production.load(async(name,json=false)=>{const buffer=await getter(name);return json?JSON.parse(new TextDecoder().decode(buffer)):buffer},m,manifestBytes);",
        "bind-manifest-bytes")
    text = _once(text,
        "document.addEventListener('viewer:layers-changed',()=>{normalizeSelectionTarget();sidebar?.sync()});",
        TIMELINE_GUARDS + "\ndocument.addEventListener('viewer:layers-changed',()=>{normalizeSelectionTarget();sidebar?.sync()});",
        "timeline-listener")
    text = _once(text,
        "function syncGammaContext(){\n  const visible=gamma.contextVisible()&&wellContext!=='hidden';",
        "function syncGammaContext(){\n  syncPreviewGamma();\n  const visible=(production.activityActive()||gamma.contextVisible())&&wellContext!=='hidden';",
        "gamma-context")
    text = _once(text,
        "if(dsuOverlay)dsuOverlay.visible=visible&&wellContext==='normal';",
        "if(dsuOverlay)dsuOverlay.visible=visible&&wellContext==='normal'&&!production.activityActive();",
        "dsu-overlay-visibility")
    text = _once(text,
        "const key=`${epoch}|${dsuHighlightVersion}|${[...detail.keys()].join(',')}|${operatorFilter}|${[...visibleSections].join(',')}`;",
        "const key=`${epoch}|${dsuHighlightVersion}|${[...detail.keys()].join(',')}|${operatorFilter}|${[...visibleSections].join(',')}|activity:${production.activityActive()}`;",
        "dsu-highlight-cache")
    text = _once(text,
        "if(dsuOverlay){dispose(dsuOverlay);dsuOverlay=null}if(!dsuScope||!manifest)return;",
        "if(dsuOverlay){dispose(dsuOverlay);dsuOverlay=null}if(!dsuScope||!manifest||production.activityActive())return;",
        "dsu-highlight-guard")
    text = _once(text,
        "for(let j=0;j<p.length;j+=6){if(p[j]===p[j+3]&&p[j+1]===p[j+4]&&p[j+2]===p[j+5])continue;",
        "for(let j=0;j<p.length;j+=6){if(!production.visible(manifest.wells[line.userData.ids[j/6]]))continue;if(p[j]===p[j+3]&&p[j+1]===p[j+4]&&p[j+2]===p[j+5])continue;",
        "fit-only-visible-wells")
    text = _once(text,
        "include(dsu.visibleBounds());include(footage.visibleBounds());if(gamma.enabled())include(gamma.limits());",
        "include(dsu.visibleBounds());include(footage.visibleBounds());if(!production.activityActive()&&gamma.enabled())include(gamma.limits());",
        "fit-without-hidden-gamma")
    text = _once(text,
        "if(!selected||!selectedData)return;",
        "if(!selected||!selectedData||!production.visible(selected))return;",
        "selected-highlight-guard")
    text = _once(text,
        "async function select(w,focus=false,{keepDSUScope=false}={}){\n  if(!w||!operatorVisible(w.id))return;",
        "async function select(w,focus=false,{keepDSUScope=false}={}){\n  if(!w||!operatorVisible(w.id))return;\n  if(!production.visible(w)){say('This well is hidden at the selected timeline date. Move forward to its reported spud date, or enable unknown spud dates if its date is unavailable.');return;}",
        "selection-guard")
    text = _once(text,
        "const gammaHit=gamma.intersection(e,camera,rect);if(gammaHit){const well=manifest.wells.find(w=>w.permit===gammaHit.entry.permit&&w.branch===gammaHit.branch);if(well&&operatorVisible(well.id))return{well,point:gammaHit.point};}",
        "const gammaHit=production.activityActive()?null:gamma.intersection(e,camera,rect);if(gammaHit){const well=manifest.wells.find(w=>w.permit===gammaHit.entry.permit&&w.branch===gammaHit.branch);if(well&&operatorVisible(well.id)&&production.visible(well))return{well,point:gammaHit.point};}",
        "gamma-pick-guard")
    text = _once(text,
        "if(wellContext==='hidden'||!gamma.contextVisible())return null;",
        "if(wellContext==='hidden'||(!production.activityActive()&&!gamma.contextVisible()))return null;",
        "pick-context")
    text = _once(text,
        "(object,id)=>object.userData.section===4?production.pickPixels(manifest.wells[id]):5",
        "(object,id)=>!production.visible(manifest.wells[id])?-1:object.userData.section===4?production.pickPixels(manifest.wells[id]):5",
        "all-section-pick-guard")
    text = _once(text,
        "renderer.domElement.addEventListener('pointermove',e=>gamma.hover(e,camera,renderer.domElement.getBoundingClientRect()));",
        "renderer.domElement.addEventListener('pointermove',e=>{if(production.activityActive()){$('gammaHover').hidden=true;return;}gamma.hover(e,camera,renderer.domElement.getBoundingClientRect());});",
        "gamma-hover-guard")
    text = _once(text,
        "button.append(title,details);button.onclick=()=>{if(matchMedia('(max-width:560px)').matches)",
        "if(!production.visible(well)){const hiddenNote='Hidden at this timeline date · advance to the reported spud date, or include unknown dates if unavailable';details.textContent+=' · '+hiddenNote;button.title=hiddenNote;}button.append(title,details);button.onclick=()=>{if(matchMedia('(max-width:560px)').matches)",
        "search-hidden-state")
    return text.replace("\n", "\r\n") if crlf else text
