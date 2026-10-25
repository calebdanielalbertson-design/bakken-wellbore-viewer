import * as THREE from 'three';
import {projectReference} from './reference-plane.js';

export const DSU_PALETTES={
  acres:['#ffffcc','#ffeda0','#fed976','#feb24c','#fd8d3c','#fc4e2a','#e31a1c','#bd0026','#800026'],
  development:['#f7fbff','#deebf7','#c6dbef','#9ecae1','#6baed6','#4292c6','#2171b5','#08519c','#08306b'],
  confidence:['#440154','#482878','#3e4989','#31688e','#26828e','#1f9e89','#35b779','#6ece58','#b5de2b','#fde725']
};
DSU_PALETTES.remaining=DSU_PALETTES.acres;
export const DSU_ACREAGE_COLORS={640:'#18a8a6',1280:'#12ca2c',1920:'#277df4',2560:'#ff8b1f',3840:'#9d63de',5120:'#db4b94'};
const finite=v=>typeof v==='number'&&Number.isFinite(v);
export function zoneInterval(zone,topOffset=0,bottomOffset=0){
  const top=finite(zone?.topFt)?zone.topFt:9000,bottom=finite(zone?.bottomFt)?zone.bottomFt:10000;
  const result=[top+topOffset,bottom+bottomOffset];
  if(!result.every(finite)||result[0]<0||result[1]<=result[0])throw Error('Upper depth must be at least zero and shallower than lower depth for every displayed DSU.');
  return result;
}
export function prepareDSUs(data,manifest){
  if(data?.type!=='FeatureCollection'||!Array.isArray(data.features)||data.metadata?.sourceCRS!=='EPSG:4269')throw Error('DSUs require a NAD83 longitude/latitude FeatureCollection.');
  const ids=new Set();
  return data.features.map(feature=>{
    const p=feature.properties,id=p?.id;
    if(!id||ids.has(id))throw Error('DSU identifiers must be present and unique.');ids.add(id);
    const bounds=[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];
    function projectGeometry(geometry,measure=false){
    if(!['Polygon','MultiPolygon'].includes(geometry?.type))throw Error('Unsupported DSU geometry.');
    const polygons=(geometry.type==='Polygon'?[geometry.coordinates]:geometry.coordinates).map(polygon=>polygon.map(ring=>{
      const clean=[];
      for(const c of ring){
        if(!Array.isArray(c)||!finite(c[0])||!finite(c[1])||Math.abs(c[0])>180||Math.abs(c[1])>90)throw Error('Invalid DSU coordinate.');
        const [x,,z]=projectReference(c[0],c[1],manifest),last=clean.at(-1);
        if(!last||last.x!==x||last.y!==z)clean.push(new THREE.Vector2(x,z));
      }
      if(clean.length>1&&clean[0].equals(clean.at(-1)))clean.pop();
      if(clean.length<3)throw Error('A DSU ring has fewer than three vertices.');
      if(measure)for(const v of clean){bounds[0]=Math.min(bounds[0],v.x);bounds[2]=Math.min(bounds[2],v.y);bounds[3]=Math.max(bounds[3],v.x);bounds[5]=Math.max(bounds[5],v.y)}
      return clean;
    }));
    if(!polygons.length||polygons.some(p=>!p.length))throw Error('Empty DSU footprint.');
    return polygons;
    }
    const polygons=projectGeometry(feature.geometry,true),nested=p.display?.outlineGeometry?{outline:projectGeometry(p.display.outlineGeometry),bands:p.display.bandGeometry?projectGeometry(p.display.bandGeometry):[],fallback:!!p.display.fallback}:null;
    const [top,bottom]=zoneInterval(p.zone);bounds[1]=-bottom;bounds[4]=-top;
    return {id,properties:p,polygons,nested,bounds};
  });
}
export function dsuScale(units,mode){
  if(mode==='acres'){
    const values=units.map(u=>u.properties.acres).filter(finite).sort((a,b)=>a-b);
    return [values[0]??0,Math.max((values[0]??0)+1,values[Math.floor((values.length-1)*.98)]??2560)];
  }
  return mode==='remaining'?[0,16]:[0,100];
}
export function dsuValue(unit,mode){
  if(mode==='acres'||mode==='acreage')return unit.properties.acres;
  const inventory=unit.properties.inventory;
  if(!inventory?.matched||inventory.underReview||!inventory.eligible)return null;
  return inventory[{remaining:'remainingWells',development:'developmentPercent',confidence:'confidence'}[mode]]??null;
}
export function dsuColor(unit,mode,range){
  if(mode==='acreage')return new THREE.Color(DSU_ACREAGE_COLORS[unit.properties.acres]||'#8c9baa');
  if(mode==='type')return new THREE.Color(unit.properties.spacingType==='SPC'?'#70c5e8':unit.properties.spacingType==='DRL'?'#cda3ff':'#6b7280');
  const value=dsuValue(unit,mode),palette=DSU_PALETTES[mode];
  if(!finite(value)||!palette)return new THREE.Color('#6b7280');
  const t=THREE.MathUtils.clamp((value-range[0])/(range[1]-range[0]),0,1)*(palette.length-1),i=Math.floor(t);
  return new THREE.Color(palette[i]).lerp(new THREE.Color(palette[Math.min(i+1,palette.length-1)]),t-i);
}

// Batch every polygon and hole into two draw calls, retaining a triangle owner
// for picking. The depth interval is an illustration, not an order interpretation.
export function dsuDisplayInterval(unit,{topOffset=0,bottomOffset=0,layout='source',depthStep=0}={}){
  const [top,bottom]=zoneInterval(unit.properties.zone,topOffset,bottomOffset),acres=unit.properties.acres;
  const knots=[[1280,0],[1920,1],[2560,2],[3840,3],[5120,4]];let rank=0;
  if(acres>5120)rank=4+Math.log2(acres/5120);
  else for(let i=1;i<knots.length;i++)if(acres>knots[i-1][0]&&acres<=knots[i][0])rank=knots[i-1][1]+(acres-knots[i-1][0])/(knots[i][0]-knots[i-1][0]);
  const lift=layout==='nested'?rank*Math.max(0,Number.isFinite(depthStep)?depthStep:0):0;
  return {top:top-lift,bottom:bottom-lift,lift,zoneTop:top,zoneBottom:bottom};
}
export function buildDSUPrisms(units,{topOffset=0,bottomOffset=0,mode='acres',range=dsuScale(units,mode),layout='source',depthStep=0,colorForUnit=null}={}){
  const positions=[],edges=[],colors=[],edgeColors=[],owners=[],ranges=[],pickPositions=[],pickOwners=[];
  units.forEach((unit,owner)=>{
    const {top,bottom}=dsuDisplayInterval(unit,{topOffset,bottomOffset,layout,depthStep}),start=positions.length/3,edgeStart=edges.length/3;
    const nested=layout==='nested'&&unit.nested,outline=nested?nested.outline:unit.polygons,caps=nested?nested.bands:unit.polygons;
    const point=(v,y)=>[v.x,-y,v.y];
    const triangle=(a,b,c)=>{positions.push(...a,...b,...c);owners.push(owner)};
    const edge=(a,b)=>edges.push(...a,...b);
    const pickTriangle=(a,b,c)=>{pickPositions.push(...a,...b,...c);pickOwners.push(owner)};
    function cap(polygons,emit){for(const rings of polygons){
      const flattened=rings.flat(),faces=THREE.ShapeUtils.triangulateShape(rings[0],rings.slice(1));
      for(const [a,b,c] of faces){emit(point(flattened[a],top),point(flattened[b],top),point(flattened[c],top));emit(point(flattened[c],bottom),point(flattened[b],bottom),point(flattened[a],bottom))}
    }}
    cap(caps,triangle);
    for(const rings of outline){
      for(const ring of rings)for(let i=0;i<ring.length;i++){
        const a=ring[i],b=ring[(i+1)%ring.length],at=point(a,top),bt=point(b,top),ab=point(a,bottom),bb=point(b,bottom);
        if(!nested?.fallback){triangle(at,bt,bb);triangle(at,bb,ab)}edge(at,bt);edge(ab,bb);edge(at,ab);
      }
    }
    if(layout==='nested'){
      cap(unit.polygons,pickTriangle);
      for(const polygon of unit.polygons)for(const ring of polygon)for(let i=0;i<ring.length;i++){
        const a=ring[i],b=ring[(i+1)%ring.length];pickTriangle(point(a,top),point(b,top),point(b,bottom));pickTriangle(point(a,top),point(b,bottom),point(a,bottom));
      }
    }
    const color=colorForUnit?colorForUnit(unit):dsuColor(unit,mode,range),end=positions.length/3,edgeEnd=edges.length/3;
    for(let i=start;i<end;i++)colors.push(color.r,color.g,color.b);
    for(let i=edgeStart;i<edgeEnd;i++)edgeColors.push(color.r,color.g,color.b);
    ranges.push({start,end,edgeStart,edgeEnd});
  });
  const geometry=new THREE.BufferGeometry(),edgeGeometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));
  edgeGeometry.setAttribute('position',new THREE.Float32BufferAttribute(edges,3));edgeGeometry.setAttribute('color',new THREE.Float32BufferAttribute(edgeColors,3));
  geometry.computeBoundingSphere();edgeGeometry.computeBoundingSphere();
  let pickGeometry=geometry;
  if(layout==='nested'){pickGeometry=new THREE.BufferGeometry();pickGeometry.setAttribute('position',new THREE.Float32BufferAttribute(pickPositions,3));pickGeometry.computeBoundingSphere()}
  return {geometry,edgeGeometry,owners:new Uint32Array(owners),ranges,pickGeometry,pickOwners:new Uint32Array(layout==='nested'?pickOwners:owners)};
}
