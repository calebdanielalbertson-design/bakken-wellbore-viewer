// Numerical tube buffers; no renderer dependency. Coordinates are survey coordinates.
// Attach the resulting mesh under the viewer's existing root so depth scaling agrees.
const clamp01 = x => Math.min(1, Math.max(0, x));

// Polynomial coefficients from Google's Apache-2.0 Turbo approximation:
// Copyright 2019 Google LLC. Authors Anton Mikhailov and Ruofei Du.
// https://gist.github.com/mikhailov-work/0d177465a8151eb6ede1768d51d476c7
const TURBO = [
  [0.13572138,4.61539260,-42.66032258,132.13108234,-152.94239396,59.28637943],
  [0.09140261,2.19418839,4.84296658,-14.18503333,4.27729857,2.82956604],
  [0.10667330,12.64194608,-60.58204836,110.36276771,-89.90310912,27.34824973]
];
export function turboSRGB(t) {
  t = clamp01(t);
  return TURBO.map(c => clamp01(c.reduceRight((a,b) => a*t+b,0)));
}
export function srgbToLinear(x) {
  return x <= 0.04045 ? x/12.92 : Math.pow((x+0.055)/1.055,2.4);
}
export function turboLinear(t) { return turboSRGB(t).map(srgbToLinear); }

const sub = (a,b) => [a[0]-b[0],a[1]-b[1],a[2]-b[2]];
const dot = (a,b) => a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const length = a => Math.hypot(...a);
const unit = a => { const d=length(a); return a.map(v=>v/d); };
const pos = s => [s.x,s.y,s.z];

// samples: {x,y,z,md,gr}; all measurements retain their original values.
// radiusAt returns an illustrative radius in coordinate units; it is not borehole size.
// colorAt returns LINEAR RGB. For a Three MeshBasicMaterial use toneMapped:false.
// maxGapMD must be set according to the resampling step (e.g. 2.5 * bin width).
// One output buffer set combines all valid runs. faceSources maps raycast faceIndex
// to two source sample indices; interpolate raw GR/MD between those samples for hover.
export function buildGammaTubeBuffers(samples, {
  sides=8, maxGapMD=Infinity, maxVertices=1000000,
  radiusAt=s=>Math.max(0,s.gr), colorAt=s=>turboLinear(s.gr/150)
}={}) {
  if (!Number.isInteger(sides) || sides<3) throw Error('sides must be an integer >= 3');
  const runs=[]; let run=[];
  const flush=()=>{if(run.length>1)runs.push(run);run=[];};
  for(let i=0;i<samples.length;i++) {
    const s=samples[i];
    if(!s || ![s.x,s.y,s.z,s.md,s.gr].every(Number.isFinite)) {flush();continue;}
    const radius=radiusAt(s);
    if(!Number.isFinite(radius)||radius<0) {flush();continue;}
    const previous=run.length?samples[run.at(-1).index]:null;
    if(previous && (s.md<=previous.md || s.md-previous.md>maxGapMD || length(sub(pos(s),pos(previous)))<1e-6)) flush();
    run.push({index:i,radius});
  }
  flush();
  const rings=runs.reduce((n,r)=>n+r.length,0), segments=rings-runs.length;
  if(rings*sides>maxVertices)throw Error(`Gamma geometry exceeds ${maxVertices} vertices; use a coarser MD bin or fewer wells.`);
  const positions=new Float32Array(rings*sides*3), colors=new Float32Array(positions.length);
  const indices=new Uint32Array(segments*sides*6),faceSources=new Uint32Array(segments*sides*4);
  const ringSources=new Uint32Array(rings),radii=new Float32Array(rings);
  let ring=0,ii=0,fi=0;
  for(const run of runs) {
    let normal=null;
    for(let j=0;j<run.length;j++,ring++) {
      const entry=run[j],p=pos(samples[entry.index]);
      const previous=pos(samples[run[Math.max(0,j-1)].index]);
      const next=pos(samples[run[Math.min(run.length-1,j+1)].index]);
      let tangent=sub(next,previous);
      if(length(tangent)<1e-6)tangent=j?sub(p,previous):sub(next,p);
      tangent=unit(tangent);
      if(normal)normal=sub(normal,tangent.map(v=>v*dot(normal,tangent)));
      if(!normal||length(normal)<1e-6)normal=cross(tangent,Math.abs(tangent[1])<0.9?[0,1,0]:[1,0,0]);
      normal=unit(normal);const binormal=unit(cross(tangent,normal)),rgb=colorAt(samples[entry.index]);
      if(!rgb||rgb.length!==3||!rgb.every(Number.isFinite))throw Error('colorAt returned invalid linear RGB');
      ringSources[ring]=entry.index;radii[ring]=entry.radius;
      for(let k=0;k<sides;k++) {
        const theta=2*Math.PI*k/sides,c=Math.cos(theta),s=Math.sin(theta),v=(ring*sides+k)*3;
        for(let axis=0;axis<3;axis++){positions[v+axis]=p[axis]+entry.radius*(normal[axis]*c+binormal[axis]*s);colors[v+axis]=rgb[axis];}
      }
      if(j)for(let k=0;k<sides;k++) {
        const a=(ring-1)*sides+k,b=(ring-1)*sides+(k+1)%sides,c=ring*sides+k,d=ring*sides+(k+1)%sides;
        indices.set([a,b,c,b,d,c],ii);ii+=6;
        faceSources.set([run[j-1].index,entry.index,run[j-1].index,entry.index],fi);fi+=4;
      }
    }
  }
  return {positions,colors,indices,faceSources,ringSources,radii,runCount:runs.length,segmentCount:segments};
}
