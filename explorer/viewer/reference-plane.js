import * as THREE from 'three';

// Same ellipsoidal east/north tangent-plane projection used by prepare_data.py.
// The state layer is NAD83. For WGS84 sample inputs this is an approximate
// geographic reference, not a survey-grade inter-datum transformation.
export function projectReference(lon, lat, manifest) {
  const r=Math.PI/180, [lon0,lat0]=manifest.origin.map(v=>v*r);
  const f=1/(manifest.sourceCRS==='NAD83'?298.257222101:298.257223563);
  const e2=f*(2-f),a=6378137;
  const ecef=(lo,la)=>{const n=a/Math.sqrt(1-e2*Math.sin(la)**2);return [n*Math.cos(la)*Math.cos(lo),n*Math.cos(la)*Math.sin(lo),n*(1-e2)*Math.sin(la)]};
  const center=ecef(lon0,lat0),p=ecef(lon*r,lat*r).map((v,i)=>v-center[i]);
  const east=-Math.sin(lon0)*p[0]+Math.cos(lon0)*p[1];
  const north=-Math.sin(lat0)*Math.cos(lon0)*p[0]-Math.sin(lat0)*Math.sin(lon0)*p[1]+Math.cos(lat0)*p[2];
  return [east/.3048,0,-north/.3048];
}

export function createReferencePlane(scene, labelHost) {
  let group=new THREE.Group(),labels=[],bounds=null,visible=true,generation=0;
  scene.add(group);
  const data=Promise.all(['north-dakota.geojson','places.geojson'].map(async name=>{
    const response=await fetch(new URL('./data/reference/'+name,import.meta.url));
    if(!response.ok)throw Error('Could not load the bundled North Dakota map.');
    return response.json();
  }));
  // A missing reference asset should not create an unhandled promise rejection
  // or prevent survey data from loading.
  data.catch(()=>{});
  function clear(){group.traverse(o=>{o.geometry?.dispose();o.material?.dispose()});group.clear();labels=[];labelHost.replaceChildren();bounds=null;}
  return {
    get bounds(){return bounds},
    get visible(){return visible},
    setVisible(value){visible=value;group.visible=value;labelHost.hidden=!value;},
    async setDataset(manifest){
      const version=++generation;clear();
      const [state,places]=await data;if(version!==generation)return;
      const features=state.features.filter(f=>f.properties.STATE==='38');
      if(features.length!==1)throw Error('The reference layer is not the North Dakota state boundary.');
      const feature=features[0],polygons=feature.geometry.type==='Polygon'?[feature.geometry.coordinates]:feature.geometry.coordinates;
      const box=new THREE.Box3();
      for(const polygon of polygons){
        const rings=polygon.map(ring=>ring.map(c=>{const p=new THREE.Vector3(...projectReference(c[0],c[1],manifest));box.expandByPoint(p);return p}));
        const shape=new THREE.Shape(rings[0].map(p=>new THREE.Vector2(p.x,p.z)));
        for(const ring of rings.slice(1))shape.holes.push(new THREE.Path(ring.map(p=>new THREE.Vector2(p.x,p.z))));
        const geometry=new THREE.ShapeGeometry(shape);geometry.rotateX(Math.PI/2);
        const plane=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({color:'#46899a',opacity:.07,transparent:true,side:THREE.DoubleSide,depthWrite:false}));
        plane.renderOrder=-10;group.add(plane);
        for(const ring of rings){
          const border=new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring),new THREE.LineBasicMaterial({color:'#8dbac8',transparent:true,opacity:.85,depthWrite:false}));
          border.renderOrder=-5;group.add(border);
        }
      }
      bounds=[box.min.x,0,box.min.z,box.max.x,0,box.max.z];
      for(const place of places.features){
        const c=place.geometry.coordinates,position=new THREE.Vector3(...projectReference(c[0],c[1],manifest));
        const label=document.createElement('span');label.className='place-label';label.textContent=place.properties.BASENAME||place.properties.NAME;
        labelHost.append(label);labels.push({label,position});
      }
      group.visible=visible;labelHost.hidden=!visible;
    },
    updateLabels(camera){
      if(!visible)return;
      const width=labelHost.clientWidth,height=labelHost.clientHeight;
      for(const {label,position} of labels){
        const p=position.clone().project(camera),x=(p.x+1)*width/2,y=(1-p.y)*height/2;
        const show=p.z>=-1&&p.z<=1&&x>15&&x<width-80&&y>75&&y<height-70;
        label.hidden=!show;if(show)label.style.transform=`translate(${x+8}px,${y-8}px)`;
      }
    }
  };
}
