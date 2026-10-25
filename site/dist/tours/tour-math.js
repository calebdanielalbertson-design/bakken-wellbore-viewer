// Pure presentation math; exaggeration never changes measured survey values.
export function bounds(points) {
  const b=[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];
  for(const p of points)for(let k=0;k<3;k++){b[k]=Math.min(b[k],p[k]);b[k+3]=Math.max(b[k+3],p[k]);}
  return b;
}
export function center(b){return b.slice(0,3).map((v,k)=>(v+b[k+3])/2);}
export function transform(p,origin,exaggeration=1){return [p[0]-origin[0],(p[1]-origin[1])*exaggeration,p[2]-origin[2]];}
export function dominantDirection(points){
  if(points.length<2)return [0,0,1];
  const c=center(bounds(points));let xx=0,zz=0,xz=0;
  for(const p of points){const x=p[0]-c[0],z=p[2]-c[2];xx+=x*x;zz+=z*z;xz+=x*z;}
  const angle=.5*Math.atan2(2*xz,xx-zz);
  return [Math.cos(angle),0,Math.sin(angle)];
}
export function intervals(branch){
  // Producer emits inclusive point-index runs; never bridge recorded gaps.
  const ranges=branch.runs||[[0,branch.points.length-1]], out=[];
  for(const [start,end] of ranges)for(let i=start+1;i<=end;i++)if(branch.points[i-1]&&branch.points[i]){
    const a=branch.points[i-1],p=branch.points[i];
    if(!branch.displayMDRange||(a[3]>=branch.displayMDRange[0]&&p[3]<=branch.displayMDRange[1]))out.push([a,p]);
  }
  return out;
}
