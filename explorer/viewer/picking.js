import * as THREE from 'three';

// Pick the displayed path width in CSS pixels, independent of orbit distance.
// Homogeneous clipping keeps close / behind-camera segments well behaved.
export function pickScreenSegments(objects,camera,pixel,width,height,maxRadius,radiusFor){
  camera.updateMatrixWorld();
  const vp=new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse),mvp=new THREE.Matrix4();
  let best=null,bestDistance=Infinity,bestDepth=Infinity;
  const [px,py]=pixel;
  for(const object of objects){
    if(!object.visible)continue;
    object.updateWorldMatrix(true,false);mvp.multiplyMatrices(vp,object.matrixWorld);const m=mvp.elements;
    const p=object.geometry.attributes.position.array,ids=object.userData.ids;
    for(let i=0;i<ids.length;i++){
      const j=i*6,ax=p[j],ay=p[j+1],az=p[j+2],bx=p[j+3],by=p[j+4],bz=p[j+5];
      if(ax===bx&&ay===by&&az===bz)continue;
      let x0=m[0]*ax+m[4]*ay+m[8]*az+m[12],y0=m[1]*ax+m[5]*ay+m[9]*az+m[13],z0=m[2]*ax+m[6]*ay+m[10]*az+m[14],w0=m[3]*ax+m[7]*ay+m[11]*az+m[15];
      let x1=m[0]*bx+m[4]*by+m[8]*bz+m[12],y1=m[1]*bx+m[5]*by+m[9]*bz+m[13],z1=m[2]*bx+m[6]*by+m[10]*bz+m[14],w1=m[3]*bx+m[7]*by+m[11]*bz+m[15];
      let t0=0,t1=1,discard=false;
      for(let plane=0;plane<2;plane++){
        const a=plane===0?w0+z0:w0-z0,b=plane===0?w1+z1:w1-z1;
        if(a<0&&b<0){discard=true;break}
        if(a<0||b<0){const t=a/(a-b),x=x0+(x1-x0)*t,y=y0+(y1-y0)*t,z=z0+(z1-z0)*t,w=w0+(w1-w0)*t,u=t0+(t1-t0)*t;if(a<0){x0=x;y0=y;z0=z;w0=w;t0=u}else{x1=x;y1=y;z1=z;w1=w;t1=u}}
      }
      if(discard||w0<=0||w1<=0)continue;
      const sx0=(x0/w0+1)*width*.5,sy0=(1-y0/w0)*height*.5,sx1=(x1/w1+1)*width*.5,sy1=(1-y1/w1)*height*.5;
      if(px<Math.min(sx0,sx1)-maxRadius||px>Math.max(sx0,sx1)+maxRadius||py<Math.min(sy0,sy1)-maxRadius||py>Math.max(sy0,sy1)+maxRadius)continue;
      const dx=sx1-sx0,dy=sy1-sy0,length=dx*dx+dy*dy;if(length<1e-10)continue;
      const s=Math.max(0,Math.min(1,((px-sx0)*dx+(py-sy0)*dy)/length));
      const distance=Math.hypot(px-sx0-dx*s,py-sy0-dy*s),radius=radiusFor(object,ids[i]);
      if(distance>radius||distance>bestDistance+.25)continue;
      const depth=(1-s)*z0/w0+s*z1/w1;
      if(Math.abs(distance-bestDistance)<=.25&&depth>=bestDepth)continue;
      const perspectiveT=(s/w1)/((1-s)/w0+s/w1),t=t0+(t1-t0)*perspectiveT;
      const point=new THREE.Vector3(ax+(bx-ax)*t,ay+(by-ay)*t,az+(bz-az)*t).applyMatrix4(object.matrixWorld);
      best={id:ids[i],point,object};bestDistance=distance;bestDepth=depth;
    }
  }
  return best;
}
