// Run from the repository root: node tests/dsu.mjs
// Uses only Node.js and the viewer's vendored Three.js; no network or Python.
// Optional: --viewer PATH, --data PATH, --no-data. Installed viewer/data/dsu data is
// smoke-tested when present; all meaningful synthetic checks always run.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const args=process.argv.slice(2);
const option=name=>{const i=args.indexOf(name);if(i<0)return null;assert.ok(args[i+1]&&!args[i+1].startsWith('--'),name+' requires a path');return args[i+1];};
const viewerPath=path.resolve(option('--viewer')??'viewer');
const sourceUrl=name=>pathToFileURL(path.join(viewerPath,name)).href;
const THREE=await import(sourceUrl('vendor/three.module.js'));
const temporaryParent=await fs.realpath(os.tmpdir());
const temporary=await fs.mkdtemp(path.join(temporaryParent,'bakken-dsu-test-'));
const temporaryUrl=name=>pathToFileURL(path.join(temporary,name)).href;
try{
await fs.writeFile(path.join(temporary,'reference.mjs'),(await fs.readFile(path.join(viewerPath,'reference-plane.js'),'utf8')).replace("from 'three'",`from '${sourceUrl('vendor/three.module.js')}'`));
await fs.writeFile(path.join(temporary,'model.mjs'),(await fs.readFile(path.join(viewerPath,'dsu-model.js'),'utf8')).replace("from 'three'",`from '${sourceUrl('vendor/three.module.js')}'`).replace("from './reference-plane.js'",`from '${temporaryUrl('reference.mjs')}'`));
await fs.writeFile(path.join(temporary,'controller.mjs'),(await fs.readFile(path.join(viewerPath,'dsu.js'),'utf8')).replace("from 'three'",`from '${sourceUrl('vendor/three.module.js')}'`).replace("from './dsu-model.js'",`from '${temporaryUrl('model.mjs')}'`));
const {prepareDSUs,buildDSUPrisms,zoneInterval,dsuDisplayInterval,dsuScale,dsuValue,dsuColor,DSU_ACREAGE_COLORS}=await import(temporaryUrl('model.mjs'));
const {projectReference}=await import(temporaryUrl('reference.mjs'));
const {createDSUController}=await import(temporaryUrl('controller.mjs'));

const manifest={sourceCRS:'NAD83',origin:[-103,48]};
const [lon,lat]=manifest.origin;
const ring=points=>points.map(([x,y])=>[lon+x,lat+y]);
const square=(x,y,half)=>ring([[x-half,y-half],[x+half,y-half],[x+half,y+half],[x-half,y+half],[x-half,y-half]]);
const feature=(id,geometry,extra={})=>({type:'Feature',id,geometry,properties:{id,label:id,sourceRecord:id,acres:1280,spacingType:'SPC',
  zone:{topFt:100,bottomFt:200,method:'test',reference:'test relative TVD'},...extra}});
const fixtures={type:'FeatureCollection',metadata:{sourceCRS:'EPSG:4269',retrievedAtUTC:'2026-10-17'},features:[
  feature('hole',{type:'Polygon',coordinates:[square(0,0,.01),square(0,0,.003)]}),
  feature('multipart',{type:'MultiPolygon',coordinates:[[square(.04,0,.005)],[square(.06,0,.005)]]},{acres:2560}),
  feature('concave',{type:'Polygon',coordinates:[ring([[-.06,0],[-.04,0],[-.04,.005],[-.055,.005],[-.055,.02],[-.06,.02],[-.06,0]])]}),
  feature('narrow',{type:'Polygon',coordinates:[ring([[.09,-.005],[.0901,-.005],[.0901,.005],[.09,.005],[.09,-.005]])]})
]};
fixtures.features[0].properties.display={insetFt:100,bandWidthFt:50,fallback:false,
  outlineGeometry:{type:'Polygon',coordinates:[square(0,0,.009),square(0,0,.004)]},
  bandGeometry:{type:'MultiPolygon',coordinates:[[square(0,0,.009),square(0,0,.0085)],[square(0,0,.0045),square(0,0,.004)]]}};
fixtures.features[1].properties.display={insetFt:340,bandWidthFt:50,fallback:false,
  outlineGeometry:{type:'MultiPolygon',coordinates:[[square(.04,0,.0045)],[square(.06,0,.0045)]]},
  bandGeometry:{type:'MultiPolygon',coordinates:[[square(.04,0,.0045),square(.04,0,.004)],[square(.06,0,.0045),square(.06,0,.004)]]}};
fixtures.features[3].properties.display={insetFt:100,bandWidthFt:50,fallback:true,
  outlineGeometry:structuredClone(fixtures.features[3].geometry),bandGeometry:null};
const unchangedFixtures=JSON.stringify(fixtures);
const units=prepareDSUs(fixtures,manifest);
const signedArea=points=>points.reduce((area,a,i)=>{const b=points[(i+1)%points.length];return area+a.x*b.y-b.x*a.y;},0)/2;
const footprintArea=unit=>unit.polygons.reduce((area,rings)=>area+Math.abs(signedArea(rings[0]))-rings.slice(1).reduce((holes,hole)=>holes+Math.abs(signedArea(hole)),0),0);
function meshFrom(batch,parent=null){
  const mesh=new THREE.Mesh(batch.geometry,new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));
  if(parent)parent.add(mesh);mesh.updateWorldMatrix(true,true);return mesh;
}
function downHits(mesh,x,z,fromY=1000){return new THREE.Raycaster(new THREE.Vector3(x,fromY,z),new THREE.Vector3(0,-1,0)).intersectObject(mesh,false);}
function hitAt(mesh,x,y){const [px,,pz]=projectReference(lon+x,lat+y,manifest);return downHits(mesh,px,pz);}

// Correct projection sign and duplicate closure handling.
assert.ok(new THREE.Vector3(...projectReference(lon,lat,manifest)).length()<1e-8);
assert.ok(projectReference(lon+.01,lat,manifest)[0]>0);
assert.ok(projectReference(lon,lat+.01,manifest)[2]<0);
assert.equal(units[0].polygons[0][0].length,4);
assert.equal(units[0].polygons[0][1].length,4);

// Earcut caps retain holes, concavity and disconnected parts; no rectangle replacement.
for(const unit of units){
  const batch=buildDSUPrisms([unit]);const p=batch.geometry.attributes.position.array;let area=0;
  for(let i=0;i<p.length;i+=9)if(p[i+1]===-100&&p[i+4]===-100&&p[i+7]===-100)
    area+=Math.abs((p[i+3]-p[i])*(p[i+8]-p[i+2])-(p[i+6]-p[i])*(p[i+5]-p[i+2]))/2;
  // Float32 positions at this map offset lose proportionally more precision in a narrow sliver.
  assert.ok(Math.abs(area-footprintArea(unit))/footprintArea(unit)<(unit.id==='narrow'?1e-3:1e-6),unit.id+' triangulated cap area');
  assert.equal(batch.owners.length,batch.geometry.attributes.position.count/3);
}
const holeBatch=buildDSUPrisms([units[0]]),holeMesh=meshFrom(holeBatch);
assert.equal(hitAt(holeMesh,0,0).length,0,'a ray through the hole does not hit a cap');
assert.ok(hitAt(holeMesh,.007,0).length>0,'outer polygon remains filled');
const multipartMesh=meshFrom(buildDSUPrisms([units[1]]));
assert.ok(hitAt(multipartMesh,.04,0).length>0);assert.ok(hitAt(multipartMesh,.06,0).length>0);
assert.equal(hitAt(multipartMesh,.05,0).length,0,'gap between multipart islands stays open');
const concaveMesh=meshFrom(buildDSUPrisms([units[2]]));
assert.equal(hitAt(concaveMesh,-.045,.015).length,0,'concave missing quadrant stays open');
assert.ok(hitAt(concaveMesh,-.058,.015).length>0);

// Owner indices remain aligned with real non-indexed triangle faceIndex values.
const combined=buildDSUPrisms(units),combinedMesh=meshFrom(combined);
for(const [owner,x,y] of [[0,.007,0],[1,.04,0],[2,-.058,.015]]){
  const hits=hitAt(combinedMesh,x,y);assert.ok(hits.length>0);
  assert.ok(hits.every(hit=>combined.owners[hit.faceIndex]===owner));
}
for(let i=0;i<combined.ranges.length;i++){
  const r=combined.ranges[i];assert.ok([...combined.owners.slice(r.start/3,r.end/3)].every(owner=>owner===i));
}

// Depth offsets validate before rendering; parent exaggeration is applied once.
assert.deepEqual(zoneInterval(null),[9000,10000]);
assert.deepEqual(zoneInterval({topFt:100,bottomFt:200},-100,50),[0,250]);
for(const offsets of [[-101,0],[200,0],[0,-100],[NaN,0],[0,Infinity]])assert.throws(()=>zoneInterval({topFt:100,bottomFt:200},...offsets));
const parent=new THREE.Group();parent.scale.y=8;
const scaledBatch=buildDSUPrisms([units[0]],{topOffset:20,bottomOffset:30}),scaledMesh=meshFrom(scaledBatch,parent);
const scaledHits=hitAt(scaledMesh,.007,0);assert.ok(scaledHits.length>0);
assert.ok(Math.abs(scaledHits[0].point.y-(-120*8))<1e-6);
scaledBatch.geometry.computeBoundingBox();assert.equal(scaledBatch.geometry.boundingBox.min.y,-230);
const worldBounds=new THREE.Box3().setFromObject(scaledMesh);assert.equal(worldBounds.min.y,-230*8);assert.equal(worldBounds.max.y,-120*8);

// Genuine zero has a numeric palette color; missing and review retain gray.
const valueUnit=inventory=>({properties:{acres:1280,inventory}});
const available={matched:true,underReview:false,eligible:true,remainingWells:0,developmentPercent:0,confidence:0};
const zero=valueUnit(available),missing=valueUnit({...available,matched:false}),review=valueUnit({...available,underReview:true});
assert.equal(dsuValue(zero,'remaining'),0);assert.equal(dsuValue(zero,'development'),0);assert.equal(dsuValue(zero,'confidence'),0);
assert.equal(dsuValue(missing,'remaining'),null);assert.equal(dsuValue(review,'remaining'),null);
assert.equal(dsuColor(zero,'remaining',[0,16]).getHexString(),'ffffcc');
assert.equal(dsuColor(missing,'remaining',[0,16]).getHexString(),'6b7280');
assert.equal(dsuColor(review,'remaining',[0,16]).getHexString(),'6b7280');
assert.notDeepEqual(dsuColor(zero,'remaining',[0,16]),dsuColor(missing,'remaining',[0,16]));

// Nested display geometry is separate from source footprints and source depths.
const classColors={640:'#18a8a6',1280:'#12ca2c',1920:'#277df4',2560:'#ff8b1f',3840:'#9d63de',5120:'#db4b94'};
assert.deepEqual(DSU_ACREAGE_COLORS,classColors);
for(const [acres,color] of Object.entries(classColors))assert.equal(dsuColor({properties:{acres:+acres}},'acreage',[0,100]).getHexString(),color.slice(1));
assert.equal(dsuColor({properties:{acres:999}},'acreage',[0,100]).getHexString(),'8c9baa');
const sourceShape=JSON.stringify(units.map(unit=>({polygons:unit.polygons,bounds:unit.bounds,zone:unit.properties.zone})));
const nestedBatch=buildDSUPrisms(units,{layout:'nested',mode:'acreage'}),nestedMesh=meshFrom(nestedBatch);
const nestedPick=meshFrom({geometry:nestedBatch.pickGeometry});
assert.notEqual(nestedBatch.pickGeometry,nestedBatch.geometry);
assert.equal(nestedBatch.pickOwners.length,nestedBatch.pickGeometry.attributes.position.count/3);
assert.equal(new Set(nestedBatch.pickOwners).size,units.length,'every source record retains a pickable full footprint');
assert.equal(units[0].nested.outline[0].length,2,'nested outline retains its hole');
assert.equal(units[1].nested.outline.length,2,'nested outline retains disconnected islands');
assert.equal(hitAt(nestedMesh,0,0).length,0);assert.equal(hitAt(nestedPick,0,0).length,0);
assert.equal(hitAt(nestedMesh,.05,0).length,0);assert.equal(hitAt(nestedPick,.05,0).length,0);
assert.equal(hitAt(nestedMesh,.0448,0).length,0,'inset band does not fill the original outer margin');
const originalMarginHits=hitAt(nestedPick,.0448,0);assert.ok(originalMarginHits.length>0);
assert.ok(originalMarginHits.every(hit=>nestedBatch.pickOwners[hit.faceIndex]===1),'full source margin retains the correct owner');
const narrowRange=nestedBatch.ranges[3];assert.equal(narrowRange.start,narrowRange.end,'vanished narrow inset falls back to an unfilled outline');
assert.ok(narrowRange.edgeEnd>narrowRange.edgeStart,'narrow fallback remains visibly outlined');
const narrowHits=hitAt(nestedPick,.09005,0);assert.ok(narrowHits.length>0);
assert.ok(narrowHits.every(hit=>nestedBatch.pickOwners[hit.faceIndex]===3));
function containsRing(points,x,z){let inside=false;for(let i=0,j=points.length-1;i<points.length;j=i++){
  const a=points[j],b=points[i];if((a.y>z)!==(b.y>z)&&x<(b.x-a.x)*(z-a.y)/(b.y-a.y)+a.x)inside=!inside;
}return inside;}
const contains=(unit,x,z)=>unit.polygons.some(rings=>containsRing(rings[0],x,z)&&!rings.slice(1).some(ring=>containsRing(ring,x,z)));
const np=nestedBatch.geometry.attributes.position.array;
for(let i=0;i<np.length;i+=9)if(np[i+1]===np[i+4]&&np[i+4]===np[i+7]){
  const x=(np[i]+np[i+3]+np[i+6])/3,z=(np[i+2]+np[i+5]+np[i+8])/3;
  assert.ok(contains(units[nestedBatch.owners[i/9]],x,z),'nested band triangle lies within its original footprint and outside source holes');
}
const lifted=dsuDisplayInterval(units[1],{layout:'nested',depthStep:25,topOffset:10,bottomOffset:20});
assert.deepEqual(lifted,{top:60,bottom:170,lift:50,zoneTop:110,zoneBottom:220});
assert.deepEqual(dsuDisplayInterval(units[1],{layout:'source',depthStep:25}),{top:100,bottom:200,lift:0,zoneTop:100,zoneBottom:200});
const liftParent=new THREE.Group();liftParent.scale.y=8;
const liftBatch=buildDSUPrisms([units[1]],{layout:'nested',depthStep:25});
const liftedVisible=meshFrom(liftBatch,liftParent),liftedPick=meshFrom({geometry:liftBatch.pickGeometry},liftParent);
liftedVisible.geometry.computeBoundingBox();liftedPick.geometry.computeBoundingBox();
assert.equal(liftedVisible.geometry.boundingBox.max.y,-50);assert.equal(liftedPick.geometry.boundingBox.max.y,-50);
const liftedHits=hitAt(liftedPick,.0448,0);assert.ok(liftedHits.length>0);assert.ok(Math.abs(liftedHits[0].point.y-(-50*8))<1e-6);
assert.equal(sourceShape,JSON.stringify(units.map(unit=>({polygons:unit.polygons,bounds:unit.bounds,zone:unit.properties.zone}))));
assert.equal(JSON.stringify(fixtures),unchangedFixtures,'display preparation/building never alters source geometry, attributes or original zone');

// Full-data smoke check is optional; synthetic tests below require no data files.
let realSummary='synthetic fixtures only (no optional local DSU data installed)';
const optionalData=path.resolve(option('--data')??path.join(viewerPath,'data/dsu/drilling-spacing-units.geojson'));
let hasData=false;if(!args.includes('--no-data'))try{await fs.access(optionalData);hasData=true;}catch(error){if(option('--data'))throw error;}
if(hasData){
  const real=JSON.parse(await fs.readFile(optionalData,'utf8'));
  const originalSources=JSON.stringify(real.features.map(feature=>[feature.geometry,feature.properties.zone]));
  const realUnits=prepareDSUs(real,manifest),realBatch=buildDSUPrisms(realUnits,{mode:'remaining'});
  assert.ok(realUnits.length>0,'optional installed DSU collection is nonempty');
  for(const geometry of [realBatch.geometry,realBatch.edgeGeometry]){
    for(const attribute of Object.values(geometry.attributes))assert.ok(attribute.array.every(Number.isFinite));
    geometry.computeBoundingBox();assert.ok([...geometry.boundingBox.min.toArray(),...geometry.boundingBox.max.toArray()].every(Number.isFinite));
    assert.ok(Number.isFinite(geometry.boundingSphere.radius)&&geometry.boundingSphere.radius>0);
  }
  assert.equal(realBatch.ranges.length,realUnits.length);
  assert.equal(realBatch.owners.length,realBatch.geometry.attributes.position.count/3);
  assert.equal(new Set(realBatch.owners).size,realUnits.length);
  assert.ok(realUnits.every(unit=>unit.bounds.every(Number.isFinite)));
  assert.deepEqual(dsuScale(realUnits,'remaining'),[0,16]);
  const realNested=buildDSUPrisms(realUnits,{layout:'nested',mode:'acreage',depthStep:250});
  for(const geometry of [realNested.geometry,realNested.edgeGeometry,realNested.pickGeometry]){
    for(const attribute of Object.values(geometry.attributes))assert.ok(attribute.array.every(Number.isFinite));
    geometry.computeBoundingBox();assert.ok([...geometry.boundingBox.min.toArray(),...geometry.boundingBox.max.toArray()].every(Number.isFinite));
  }
  assert.equal(realNested.pickOwners.length,realNested.pickGeometry.attributes.position.count/3);
  assert.equal(new Set(realNested.pickOwners).size,realUnits.length);
  assert.equal(originalSources,JSON.stringify(real.features.map(feature=>[feature.geometry,feature.properties.zone])));
  realSummary=`${realUnits.length} optional installed units (${realBatch.owners.length} source triangles; ${realNested.owners.length} nested triangles)`;
}

// Exercise controller visibility/pick ownership under nonuniform parent depth scale.
class Element{constructor(){this.children=[];this.style={};this.value='';this.checked=false;this.textContent='';this.hidden=false;}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}setAttribute(){} }
const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
globalThis.document={getElementById:$,createElement:()=>new Element()};
globalThis.fetch=async()=>({ok:true,json:async()=>structuredClone(fixtures)});
const root=new THREE.Group();root.scale.y=8;const messages=[],focuses=[];
const controller=createDSUController(root,{say:message=>messages.push(message),focus:b=>focuses.push(b)});
controller.setDataset(manifest);await controller.setVisible(true);$('dsuInspect').checked=true;
const camera=new THREE.OrthographicCamera(-6000,6000,6000,-6000,.1,100000);
camera.position.set(0,10000,0);camera.up.set(0,0,-1);camera.lookAt(0,-1000,0);camera.updateProjectionMatrix();camera.updateMatrixWorld();
const rect={left:0,top:0,width:1000,height:1000};
const eventAt=(x,y)=>{const point=new THREE.Vector3(...projectReference(lon+x,lat+y,manifest)).project(camera);return{clientX:(point.x+1)*500,clientY:(1-point.y)*500};};
assert.equal(controller.pick(eventAt(.007,0),camera,rect),true);
assert.ok($('dsuSelection').children.at(-1).textContent.includes('hole'));
const controllerGroup=root.children.find(child=>child.name==='Approximate DSU zones');
const selectedButton=()=>$('dsuSelection').children.find(child=>child.textContent==='Show only this DSU'||child.textContent==='Show all DSUs');
assert.ok(selectedButton(),'selected DSU provides an isolation button');
selectedButton().onclick();assert.equal($('dsuFilter').value,'selected');
assert.equal(controllerGroup.children.find(child=>child.isMesh).geometry.attributes.position.count,buildDSUPrisms([units[0]],{layout:'nested'}).geometry.attributes.position.count);
assert.ok($('dsuSelection').children.at(-1).textContent.includes('hole'));
selectedButton().onclick();assert.equal($('dsuFilter').value,'all');
assert.equal(controllerGroup.children.find(child=>child.isMesh).geometry.attributes.position.count,nestedBatch.geometry.attributes.position.count);
assert.equal(controller.pick(eventAt(0,0),camera,rect),true);assert.match(messages.at(-1),/No DSU box/);
const oblique=new THREE.PerspectiveCamera(45,1,.1,100000),target=new THREE.Vector3(...projectReference(lon+.007,lat,manifest));target.y=-800;
oblique.position.copy(target).add(new THREE.Vector3(2000,5000,3000));oblique.lookAt(target);oblique.updateProjectionMatrix();oblique.updateMatrixWorld();
assert.equal(controller.pick({clientX:500,clientY:500},oblique,rect),true);
assert.ok($('dsuSelection').children.at(-1).textContent.includes('hole'),'perspective ray retains the same triangle owner under parent scale');
// The hidden full-source target follows the same exploded display lift and filter as visible bands.
const partTarget=new THREE.Vector3(...projectReference(lon+.0448,lat,manifest));
const partCamera=new THREE.OrthographicCamera(-1000,1000,1000,-1000,.1,100000);
partCamera.position.set(partTarget.x,10000,partTarget.z);partCamera.up.set(0,0,-1);partCamera.lookAt(partTarget.x,-800,partTarget.z);partCamera.updateProjectionMatrix();partCamera.updateMatrixWorld();
$('dsuDepthSeparation').onchange({target:{value:'25'}});
assert.equal(controller.pick({clientX:500,clientY:500},partCamera,rect),true);
assert.ok($('dsuSelection').children.at(-1).textContent.includes('multipart'));
$('dsuSelection').children.find(child=>child.textContent==='Zoom to DSU').onclick();
assert.equal(focuses.at(-1)[1],-150);assert.equal(focuses.at(-1)[4],-50,'zoom bounds include the same display lift');
$('dsuLayout').onchange({target:{value:'source'}});
assert.equal(controllerGroup.children.filter(child=>child.isMesh).length,1,'source layout uses its visible mesh for picking');
assert.equal($('dsuDepthSeparation').disabled,true);
$('dsuSelection').children.find(child=>child.textContent==='Zoom to DSU').onclick();
assert.equal(focuses.at(-1)[1],-200);assert.equal(focuses.at(-1)[4],-100);
$('dsuLayout').onchange({target:{value:'nested'}});
assert.equal(controllerGroup.children.filter(child=>child.isMesh).length,2,'nested layout has a separate hidden full-source target');
assert.equal(controllerGroup.children.filter(child=>child.isMesh&&child.visible===false).length,1);
$('dsuFilter').onchange({target:{value:'acres-1280'}});
controller.pick({clientX:500,clientY:500},partCamera,rect);assert.match(messages.at(-1),/No DSU box/,'filtered hidden pick target cannot capture a click');
$('dsuFilter').onchange({target:{value:'all'}});
await controller.setVisible(false);assert.equal(controller.pick(eventAt(.007,0),camera,rect),false);
assert.equal(controller.inspecting(),false);

// A delayed prior dataset fetch cannot overwrite a newer dataset projection.
let releaseFirst,fetches=0;
globalThis.fetch=async()=>{fetches++;if(fetches===1)await new Promise(resolve=>releaseFirst=resolve);return{ok:true,json:async()=>structuredClone(fixtures)};};
controller.setDataset(manifest);const oldLoad=controller.setVisible(true);await Promise.resolve();
const shifted={sourceCRS:'NAD83',origin:[lon+.5,lat]};controller.setDataset(shifted);await controller.setVisible(true);
const group=root.children.find(child=>child.name==='Approximate DSU zones');
const currentGeometry=group.children.find(child=>child.isMesh).geometry;
releaseFirst();await oldLoad;
assert.equal(group.children.find(child=>child.isMesh).geometry,currentGeometry,'stale earlier load cannot replace current geometry');
controller.setDataset(null);assert.equal(group.children.length,0);assert.equal(controller.inspecting(),false);

// Overlapping source records remain independently selectable, including identical footprints.
const duplicate=structuredClone(fixtures.features[0]);duplicate.id=duplicate.properties.id='overlap';duplicate.properties.sourceRecord='overlap';
const overlapping={...fixtures,features:[fixtures.features[0],duplicate]};
globalThis.fetch=async()=>({ok:true,json:async()=>structuredClone(overlapping)});
const overlapRoot=new THREE.Group();overlapRoot.scale.y=8;
const overlapController=createDSUController(overlapRoot,{say(){},focus(){}});
overlapController.setDataset(manifest);await overlapController.setVisible(true);$('dsuInspect').checked=true;
assert.equal(overlapController.pick(eventAt(.007,0),camera,rect),true);
const chooser=$('dsuOverlaps').children[1];assert.equal(chooser.children.length,2);
chooser.value='1';chooser.onchange();assert.ok($('dsuSelection').children.at(-1).textContent.includes('overlap'));
const overlapGroup=overlapRoot.children.find(child=>child.name==='Approximate DSU zones');
selectedButton().onclick();assert.equal($('dsuFilter').value,'selected');
assert.equal(overlapGroup.children.find(child=>child.isMesh).geometry.attributes.position.count,buildDSUPrisms([units[0]],{layout:'nested'}).geometry.attributes.position.count);
overlapController.setDataset(null);assert.equal($('dsuFilter').value,'all');assert.equal(overlapGroup.children.length,0);
console.log(`PASS: DSU holes/multipart/concavity, nested bands/fallback/source preservation, acreage colors, lifted source picking, triangle owners, depth offsets/root scaling, zero vs missing/review, overlap selection/isolation, visibility and stale dataset replacement; ${realSummary}.`);
}finally{
  // Validate the resolved temporary target before recursive cleanup on Windows.
  const resolved=await fs.realpath(temporary);
  assert.equal(path.dirname(resolved),temporaryParent);
  assert.ok(path.basename(resolved).startsWith('bakken-dsu-test-'));
  await fs.rm(resolved,{recursive:true,force:true});
}
