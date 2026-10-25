"""Create the local timeline controller from the unchanged published oil renderer."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workspace_paths as wp
ROOT = Path(__file__).resolve().parent
SOURCE = wp.SITE_DIST / 'viewer/production.js'
BASELINE = wp.WORK / 'fracfocus-release/baseline/viewer/production.js'
if BASELINE.is_file():
    SOURCE = BASELINE


def build():
    text = SOURCE.read_text(encoding='utf-8')
    def replace(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise ValueError('Controller source changed: ' + old[:90])
        text = text.replace(old, new, 1)
    replace("import {renderScopeHistory}", "import {createActivityModel,validateActivitySnapshot} from './activity-model.js';\nimport {renderScopeHistory}")
    replace('const lookup=`', '''const maskLookup=`
uniform sampler2D activityTexture;
uniform vec2 activitySize;
uniform float activityEnabled;
attribute float activityIndex;
varying float activityVisible;
float visibleAt(float index){
  if(activityEnabled<0.5)return 1.0;
  if(index<0.0)return 0.0;
  return texture2D(activityTexture,(vec2(mod(index,activitySize.x),floor(index/activitySize.x))+0.5)/activitySize).r;
}`;
const lookup=`${maskLookup}''')
    replace('uniform vec3 lime;', 'uniform float activityMode;\nuniform float activityEnabled;\nvarying float activityVisible;\nuniform vec3 lime;')
    replace('  if(wellContext>1.5', '  if(activityVisible<0.5)discard;\n  if(wellContext>1.5')
    replace('  float alpha=opacity;', '''  float alpha=opacity;
  if(activityEnabled>0.5){
    color=quantity>0.0?vec3(0.10,0.68,0.98):quantity>-1.5&&quantity<0.0?vec3(1.0,0.56,0.12):vec3(0.30,0.43,0.50);
    if(quantity<=0.0)alpha*=0.35;
  }''')
    replace('uniform float referenceWidth;', 'uniform float referenceWidth;\nuniform float referenceQuantity;')
    text = text.replace('quantity=oilAt(productionIndex);wellIndex=', 'activityVisible=visibleAt(activityIndex);quantity=oilAt(productionIndex);wellIndex=')
    replace('sqrt(quantity/10000.0)', 'sqrt(quantity/referenceQuantity)')
    replace('let requestedEnabled=initialEnabled;', "let mode=params.get('timeline')==='activity'?'activity':'oil';\n  let requestedEnabled=initialEnabled||mode==='activity',oilModel=null,activityModel=null,includeUnknown=false,activityError='',surveyWells=[];\n  let activityTexture=new THREE.DataTexture(new Float32Array([1]),1,1,THREE.RedFormat,THREE.FloatType);activityTexture.needsUpdate=true;")
    replace('const uniforms={oilTexture:', "const uniforms={activityTexture:{value:activityTexture},activitySize:{value:new THREE.Vector2(1,1)},activityEnabled:{value:0},activityMode:{value:0},referenceQuantity:{value:10000},oilTexture:")
    replace('uniforms.productionEnabled.value=enabled?1:0;', 'uniforms.productionEnabled.value=enabled?1:0;uniforms.activityEnabled.value=activityActive()?1:0;')
    replace('if(!enabled)stop();selection(selected);document.dispatchEvent', 'if(!enabled)stop();selection(selected);announce();document.dispatchEvent')
    replace("generation++;stop();model=null;", "generation++;stop();model=null;oilModel=null;activityModel=null;activityError='';")
    replace("function drawScopeHistory(){const host=$('dsuProduction');if(!host)return;", "function drawScopeHistory(){const host=$('dsuProduction');if(!host)return;if(mode==='activity'){host.replaceChildren();if(scopeHistory)host.textContent='The timeline shows frac activity for the selected area. Switch to Monthly oil for the production history.';return;}")
    start = text.index('  function drawLegend()')
    end = text.index('  function setMonth(', start)
    text = text[:start] + '''  function activityActive(){return enabled&&mode==='activity'&&!!activityModel}
  function visible(w){return !activityActive()||!!w&&activityModel.visible(w,month,includeUnknown)}
  function announce(){document.dispatchEvent(new CustomEvent('viewer:timeline-changed',{detail:{mode,enabled,date:model?.metadata.months[month]}}))}
  function drawLegend(){
    const water=mode==='activity',width=uniforms.referenceWidth.value,reference=water?10000000:10000;
    $('productionSizeValue').textContent=`${width} px at ${water?'10 million gal':'10,000 bbl'}`;
    $('productionLegend').replaceChildren();for(const value of [reference/10,reference,reference*4]){
      const row=document.createElement('div');row.className='production-key';const bar=document.createElement('i');bar.style.height=(width*Math.sqrt(value/reference))+'px';if(water)bar.style.background='#43c3ff';
      const label=document.createElement('span');label.textContent=fmt(value)+(water?' gal':' bbl');row.append(bar,label);$('productionLegend').append(row);
    }
    $('timelineWidthNote').textContent=water?'Width ∝ √reported carrier-water gallons, using one fixed scale across months. Blue width = reported frac water; thin amber = event with unavailable or review-required water; thin gray = no recorded event or reported zero.':'Width ∝ √monthly oil barrels, using one fixed scale across months. Thin muted lime = reported zero; gray = unavailable. Survey color options still apply.';
  }
  function updateVisibility(){
    if(!activityModel)return;
    const date=model?.metadata.months[month];activityTexture.image.data.fill(0);
    for(let i=0;i<activityModel.count;i++)activityTexture.image.data[i]=activityModel.visible(activityModel.metadata.wells[i],date,includeUnknown)?1:0;
    activityTexture.needsUpdate=true;
  }
  function statusText(){
    if(!model)return mode==='activity'?'Spud & frac activity unavailable: '+activityError:'Monthly oil unavailable for this dataset.';
    return `${monthLabel(model.metadata.months[0])}–${monthLabel(model.metadata.months.at(-1))} · ${fmt(model.scopeIndices.length)} mapped wells${scopeLabel?' in '+scopeLabel:''}`;
  }
''' + text[end:]
    replace("    model.uploadMonth(month,texture.image.data);texture.needsUpdate=true;", "    model.uploadMonth(month,texture.image.data);texture.needsUpdate=true;updateVisibility();")
    replace("    $('productionSummary').textContent=(scopeHistory", "    if(mode==='oil'){$('productionSummary').textContent=(scopeHistory")
    replace("    $('productionPrevious').disabled=", "    }\n    $('productionPrevious').disabled=")
    replace("    $('productionPrevious').disabled=", '''    if(mode==='activity'){
      const missing=s.unavailableWaterWells,hidden=s.hiddenFracWells;
      $('productionSummary').textContent=(scopeLabel?scopeLabel+' · ':'')+`${fmt(s.knownGallons)} known gal · ${fmt(s.fracWells)} wells with disclosures · ${fmt(s.spudded)} spuds`;
      $('productionCoverage').textContent=`${fmt(s.visibleWells)} wells shown · ${fmt(s.fracEvents)} disclosures. ${missing?fmt(missing)+(missing===1?' well lacks':' wells lack')+' usable water; sum is partial. ':''}${hidden?fmt(hidden)+' wells with events hidden by unknown spud date. ':''}${fmt(s.unknownSpudWells)} spud dates unavailable. Full volume assigned once to job-end month.`;
      const cutoff=activityModel.metadata.provenance.latest_job_end?.slice(0,7);
      if(cutoff&&date>cutoff){$('productionSummary').textContent=`${fmt(s.spudded)} spuds · Frac coverage unavailable after ${cutoff}`;$('productionCoverage').textContent=`${fmt(s.visibleWells)} wells shown. Supplied FracFocus history ends ${cutoff}; later treatment activity is unknown.`;}
    }
    $('productionPrevious').disabled=''')
    replace('    selection(selected);drawScopeHistory();', '    selection(selected);drawScopeHistory();announce();')
    start = text.index('  async function load(')
    end = text.index('  function decorate(', start)
    text = text[:start] + '''  function setMode(value,{preserve=true}={}){
    const previous=preserve?model?.metadata.months[month]:null;stop();mode=value==='activity'?'activity':'oil';
    model=mode==='activity'?activityModel:oilModel;
    $('timelineMode').value=mode;$('activityOptions').hidden=mode!=='activity';
    uniforms.activityMode.value=mode==='activity'?1:0;uniforms.referenceQuantity.value=mode==='activity'?10000000:10000;
    $('productionEnabled').disabled=!model;$('productionStatus').textContent=statusText();
    $('productionSourceNote').textContent=mode==='activity'?'Local GIS spud dates + FracFocus disclosures. The whole current mapped trajectory appears from its reported spud month: a timing proxy, not as-drilled geometry. The full reported carrier-water volume is assigned once to the job END month, not spread across days. No event does not establish no frac. Ambiguous disclosures and missing volumes are excluded from the known-volume sum.':model?.metadata.displayNote||'Historical monthly oil. Missing records do not establish a drilling date.';
    if(mode==='activity'&&activityModel){const p=activityModel.metadata.provenance;$('productionSourceNote').textContent+=` FracFocus source includes jobs ending through ${p.latest_job_end||'unknown'}; snapshot coverage is not proof of completeness.`;}
    if(!model){setEnabled(false,{remember:false});return;}
    model.setBranchScope(requestedScopeIds);
    $('productionStatus').textContent=statusText();
    texture.dispose();const width=Math.min(1024,Math.max(1,model.count)),height=Math.max(1,Math.ceil(model.count/width));
    texture=new THREE.DataTexture(new Float32Array(width*height).fill(-1),width,height,THREE.RedFormat,THREE.FloatType);texture.needsUpdate=true;texture.minFilter=texture.magFilter=THREE.NearestFilter;
    uniforms.oilTexture.value=texture;uniforms.textureSize.value.set(width,height);
    for(const v of views)for(let i=0;i<v.ids.length;i++){
      const index=model.renderByBranch[v.ids[i]]??-1;v.line.geometry.attributes.productionIndex.setX(i*2,index);v.line.geometry.attributes.productionIndex.setX(i*2+1,index);v.mesh.geometry.attributes.productionIndex.setX(i,index);
      v.line.geometry.attributes.productionIndex.needsUpdate=true;v.mesh.geometry.attributes.productionIndex.needsUpdate=true;
    }
    periods=playbackPeriods(model.metadata.months);
    if(mode==='activity'){
      const first=model.metadata.months.findIndex(m=>m>=('2009-01'));
      if(first>0)periods.push({start:first,end:model.metadata.months.length-1,label:'2009–present · FracFocus era'});
    }
    $('productionPeriod').replaceChildren();periods.forEach((p,i)=>{const option=document.createElement('option');option.value=i;option.textContent=p.label;$('productionPeriod').append(option)});
    const target=params.get('month')&&!preserve?params.get('month'):previous||(mode==='activity'?activityModel.metadata.provenance.latest_job_end?.slice(0,7):null);
    const targetIndex=target?model.metadata.months.indexOf(target):-1;
    const pi=targetIndex>=0?periods.findIndex(p=>targetIndex>=p.start&&targetIndex<=p.end):periods.length-1;
    setPeriod(Math.max(0,pi));if(targetIndex>=0)setMonth(targetIndex);
    setEnabled(requestedEnabled,{remember:false});drawLegend();
  }
  async function load(read,survey,manifestBytes){
    reset();const version=generation;surveyWells=survey.wells;
    const results=await Promise.allSettled([
      (async()=>{const raw=await read('production.json',true);const data=new Float32Array(await read(raw.valuesFile||raw.file||'oil.bin'));return createProductionModel(raw,data,survey.wells)})(),
      (async()=>{const response=await fetch('./activity.json');if(!response.ok)throw Error('Local activity snapshot is not prepared.');const raw=await response.json();await validateActivitySnapshot(raw,manifestBytes);return createActivityModel(raw,survey.wells)})()
    ]);
    if(version!==generation)return;
    if(results[0].status==='fulfilled')oilModel=results[0].value;
    if(results[1].status==='fulfilled'){
      activityModel=results[1].value;activityModel.setIncludeUnknown(includeUnknown);const width=Math.min(1024,Math.max(1,activityModel.count)),height=Math.max(1,Math.ceil(activityModel.count/width));activityTexture.dispose();
      activityTexture=new THREE.DataTexture(new Float32Array(width*height).fill(1),width,height,THREE.RedFormat,THREE.FloatType);activityTexture.needsUpdate=true;activityTexture.minFilter=activityTexture.magFilter=THREE.NearestFilter;
      uniforms.activityTexture.value=activityTexture;uniforms.activitySize.value.set(width,height);
    }else activityError=results[1].reason.message;
    setMode(mode,{preserve:false});
  }
  function maskLine(line){
    const ids=line.userData.ids,values=new Float32Array(ids.length*2).fill(-1);
    for(let i=0;i<ids.length;i++)values[i*2]=values[i*2+1]=activityModel?.renderByBranch[ids[i]]??-1;
    line.geometry.setAttribute('activityIndex',new THREE.BufferAttribute(values,1));
    if(line.userData.section!==4){
      line.material.onBeforeCompile=shader=>{
        Object.assign(shader.uniforms,{activityTexture:uniforms.activityTexture,activitySize:uniforms.activitySize,activityEnabled:uniforms.activityEnabled});
        shader.vertexShader=maskLookup+'\\n'+shader.vertexShader.replace('void main() {','void main() { activityVisible=visibleAt(activityIndex);');
        shader.fragmentShader='varying float activityVisible;\\n'+shader.fragmentShader.replace('void main() {','void main() { if(activityVisible<0.5)discard;');
      };
      line.material.customProgramCacheKey=()=> 'local-activity-mask-v1';line.material.needsUpdate=true;
    }
  }
''' + text[end:]
    replace('    if(!model)return;\n    const ids=line.userData.ids', '    maskLine(line);if(line.userData.section!==4||(!oilModel&&!activityModel))return;\n    const ids=line.userData.ids')
    replace('const p=model.renderByBranch[ids[i]]??-1;', 'const p=model?.renderByBranch[ids[i]]??-1;')
    replace("    g.setAttribute('uturnLateral'", "    const activityIndices=new Float32Array(ids.length);for(let i=0;i<ids.length;i++)activityIndices[i]=activityModel?.renderByBranch[ids[i]]??-1;g.setAttribute('activityIndex',new THREE.InstancedBufferAttribute(activityIndices,1));\n    g.setAttribute('uturnLateral'")
    replace("    const title=document.createElement('h4');title.textContent='Monthly oil production';", "    if(mode==='activity'){activitySelection(host,w,index);return;}\n    const title=document.createElement('h4');title.textContent='Monthly oil production';")
    hook = "  $('productionEnabled').onchange="
    insert = '''  function activitySelection(host,w,index){
    const row=activityModel.metadata.wells[index],date=model.metadata.months[month],water=model.value(month,index);
    const title=document.createElement('h4');title.textContent='Spud & frac activity';const spud=document.createElement('p');spud.textContent='Reported spud: '+(row?.spud_date||'unavailable');
    const value=document.createElement('p');value.className='production-well-value';value.textContent=`${monthLabel(date)}: ${model.status(month,index).water_status==='unmatched_identity'?'Activity identity unavailable':water>=0?fmt(water)+' gal reported water':water===-1?'Frac event · water unavailable / review required':'No recorded frac event'}`;
    if(date>model.metadata.provenance.latest_job_end?.slice(0,7))value.textContent=`${monthLabel(date)}: Outside supplied FracFocus history; activity unknown.`;
    const note=document.createElement('p');note.className='caption';note.textContent='Current mapped path shown from spud month. Water belongs to the whole well job; all mapped branches share its size, and totals count the well once.';host.append(title,spud,value,note);
    const events=(row?.events||[]).filter(e=>e.month&&e.month>=model.metadata.months[period.start]&&e.month<=model.metadata.months[period.end]);
    if(events.length){const label=document.createElement('p');label.className='caption';label.textContent='Jump to a recorded treatment:';host.append(label);for(const event of events.slice(-8)){const button=document.createElement('button');button.type='button';button.textContent=event.end+' · '+(event.water_gallons!==null&&!event.review_required?fmt(event.water_gallons)+' gal':'water unavailable / review');button.onclick=()=>{stop();const i=model.metadata.months.indexOf(event.month);if(i>=0){setEnabled(true);setMonth(i)}};host.append(button);}}
  }
  $('timelineMode').onchange=e=>setMode(e.target.value);
  $('activityUnknown').onchange=e=>{includeUnknown=e.target.checked;activityModel?.setIncludeUnknown(includeUnknown);setMonth(month)};
'''
    replace(hook, insert+hook)
    text = text.replace('!model.summaries[first].reported', "!(mode==='activity'?model.summaries[first].fracEvents:model.summaries[first].reported)")
    replace('return {load,reset,decorate,', 'return {activityActive,visible,load,reset,decorate,')
    replace("const raw=model.metadata;$('productionStatus').textContent=", "const raw=model.metadata;$('productionStatus').textContent=") # Guard unchanged seam.
    # Scope updates must apply to both independent datasets when modes change.
    replace('if(!model)return;model.setBranchScope(ids);const raw=', 'if(!model)return;model.setBranchScope(ids);const raw=')
    start = text.index('    pickPixels(w)')
    end = text.index('\n  };',start)
    text = text[:start] + '''    pickPixels(w){if(w&&!visible(w))return -1;if(uniforms.wellContext.value>0.5||!enabled||!model)return 5;const quantity=w?model.value(month,model.indexOf(w)):mode==='activity'?model.summaries[month].maximumWater:model.summaries[month].maximumOil;return Math.max(5,(quantity>0?uniforms.referenceWidth.value*Math.sqrt(quantity/uniforms.referenceQuantity.value):0)/2+3)}''' + text[end:]
    (ROOT / 'production.js').write_text(text, encoding='utf-8')


if __name__ == '__main__':
    build()
