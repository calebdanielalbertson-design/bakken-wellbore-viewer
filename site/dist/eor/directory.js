const $=id=>document.getElementById(id);let registry,projects=[];
const element=(tag,className,text)=>{const el=document.createElement(tag);if(className)el.className=className;if(text)el.textContent=text;return el};
const svgNS='http://www.w3.org/2000/svg';
const geometryCache=new Map();
function projectGeometry(id){
  if(!geometryCache.has(id))geometryCache.set(id,fetch(`/eor/data/${encodeURIComponent(id)}.json`).then(response=>{if(!response.ok)throw Error('Geometry not available');return response.json();}).catch(error=>{geometryCache.delete(id);throw error;}));
  return geometryCache.get(id);
}
async function planPreview(host,project){
  try{
    const geometry=await projectGeometry(project.id);
    const branches=geometry.wells.flatMap(w=>w.branches).filter(b=>b.points.length>1);const points=branches.flatMap(b=>b.points);if(!points.length)throw Error('No survey paths');
    const xs=points.map(p=>p[0]),zs=points.map(p=>p[2]);const xmin=Math.min(...xs),xmax=Math.max(...xs),zmin=Math.min(...zs),zmax=Math.max(...zs);const scale=Math.min(100/Math.max(1,xmax-xmin),140/Math.max(1,zmax-zmin));const cx=(xmin+xmax)/2,cz=(zmin+zmax)/2;
    const svg=document.createElementNS(svgNS,'svg');svg.setAttribute('viewBox','0 0 120 160');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${project.title}: actual surveyed paths in plan view`);
    for(const branch of branches){const path=document.createElementNS(svgNS,'polyline');path.setAttribute('points',branch.points.map(p=>`${60+(p[0]-cx)*scale},${80+(p[2]-cz)*scale}`).join(' '));path.setAttribute('fill','none');path.setAttribute('stroke','#075b88');path.setAttribute('stroke-width','1.4');path.setAttribute('stroke-linecap','round');svg.append(path)}
    const north=document.createElementNS(svgNS,'text');north.setAttribute('x','8');north.setAttribute('y','12');north.setAttribute('font-size','8');north.setAttribute('fill','#617e90');north.textContent='N ↑';svg.append(north);host.replaceChildren(svg,element('small','','Actual paths · plan'));
  }catch{host.replaceChildren(element('span','plan-error','Survey preview unavailable'))}
}
function card(project,index){
  const article=element('article','project-card'),preview=element('div','project-plan'),copy=element('div','project-copy');preview.append(element('small','','Loading paths…'));
  copy.append(element('p','project-number',`PROJECT ${String(index+1).padStart(2,'0')}`),element('h3','',project.title),element('p','project-operator',project.operator),element('p','project-method',project.method));
  const meta=element('div','project-metadata');meta.append(element('span','',`${project.wells.length} documented ${project.wells.length===1?'well':'wells'}`),element('span','',project.location));copy.append(meta,element('p','project-evidence',`${project.status}${project.statusDate?' · Source '+project.statusDate:''}`));
  const link=element('a','text-link','Explore project');link.href=`/eor/project/?project=${encodeURIComponent(project.id)}`;link.setAttribute('aria-label',`Explore ${project.title}`);link.append(element('span','','↗'));copy.append(link);article.append(preview,copy);planPreview(preview,project);return article;
}
function render(){
  const query=$('projectSearch').value.trim().toLowerCase(),operator=$('operatorFilter').value;
  const matching=projects.filter(p=>(operator==='all'||p.operator===operator)&&(!query||[p.title,p.operator,p.location,p.method,...p.wells.flatMap(w=>[w.name,w.fileNumber])].join(' ').toLowerCase().includes(query)));
  $('projectGrid').replaceChildren(...matching.map(p=>card(p,projects.indexOf(p))));$('emptyState').hidden=matching.length!==0;$('filterStatus').textContent=`${matching.length} of ${projects.length} projects shown`;
}
try{
  const response=await fetch('/eor/projects.json');if(!response.ok)throw Error('Project register is unavailable.');registry=await response.json();projects=registry.projects;
  if(!Array.isArray(projects)||!projects.length)throw Error('No project records are available.');
  const files=new Set(projects.flatMap(p=>p.wells.map(w=>w.fileNumber)));$('collectionSummary').textContent=`${projects.length} projects · ${files.size} documented wells · Curated source review`;
  for(const name of [...new Set(projects.map(p=>p.operator))].sort()){const option=element('option','',name);option.value=name;$('operatorFilter').append(option)}
  $('projectSearch').addEventListener('input',render);$('operatorFilter').addEventListener('change',render);$('clearFilters').addEventListener('click',()=>{$('projectSearch').value='';$('operatorFilter').value='all';render()});render();
}catch(error){$('collectionSummary').textContent=error.message;$('filterStatus').textContent='Please reload the project directory. Project data has not been substituted with example values.'}
