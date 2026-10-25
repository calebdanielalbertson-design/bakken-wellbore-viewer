export const clamp = x => Math.max(0,Math.min(1,x));
export const ease = x => {const t=clamp(x);return t*t*(3-2*t)};
export const mix = (a,b,t) => a+(b-a)*t;
export function planFrame(bounds,aspect,padding=1.14){
  return {center:[(bounds[0]+bounds[3])/2,(bounds[1]+bounds[4])/2,(bounds[2]+bounds[5])/2],half:Math.max((bounds[5]-bounds[2])/2,(bounds[3]-bounds[0])/(2*aspect))*padding};
}
export function zoomFrame(from,to,t){
  const u=ease(t);
  const half=Math.exp(mix(Math.log(from.half),Math.log(to.half),u));
  // Couple pan to visible span so the featured cluster stays in the frame.
  const pan=Math.abs(from.half-to.half)>1e-9?(from.half-half)/(from.half-to.half):u;
  return {center:from.center.map((v,i)=>mix(v,to.center[i],pan)),half};
}
export const perspectiveDistance=(half,fov=45)=>half/Math.tan(fov*Math.PI/360);
export const TOUR_SHOTS=[
  {at:0,end:2.8,key:'state',title:'North Dakota',tag:'START WITH THE BIG PICTURE',note:'Locate the Bakken well paths within the state boundary.'},
  {at:2.8,end:8,key:'zoom',title:'Move into the field',tag:'REGION → WELL CLUSTER',note:'One continuous zoom from statewide context to individual well paths.'},
  {at:8,end:10,key:'plan',title:'Plan view',tag:'NORTH UP',note:'See the spacing and direction of the laterals from above.'},
  {at:10,end:12,key:'side',title:'Side view',tag:'BELOW THE SURFACE',note:'See relative depth and the transition from vertical to lateral.'},
  {at:12,end:14,key:'section',title:'Well sections',tag:'EXPLORE IN 3D',note:'Orbit the paths and distinguish each classified section.'},
  {at:14,end:17,key:'azimuth',title:'Azimuth',tag:'DIRECTION',note:'A cyclic compass scale reveals the direction of each well path.'},
  {at:17,end:20,key:'dls',title:'Dogleg severity',tag:'DIRECTIONAL CHANGE',note:'Changes in survey direction per 100 ft of measured depth.'},
  {at:20,end:22,key:'curvature',title:'Curvature',tag:'DIRECTIONAL CHANGE',note:'The same directional change as DLS, expressed in rad/1,000 ft.'},
  {at:22,end:24,key:'tortuosity',title:'Local tortuosity',tag:'PATH SHAPE',note:'Path/chord ratio in a centered, up-to-1,000 ft MD window. End windows shorten.'},
  {at:24,end:26,key:'inclination',title:'Inclination',tag:'WELL ANGLE',note:'Degrees from downward vertical: 0° vertical, 90° horizontal.'},
  {at:26,end:28,key:'build',title:'Build / drop rate',tag:'CHANGE IN INCLINATION',note:'Positive increases inclination; negative decreases it.'},
  {at:28,end:30,key:'turn',title:'Turn rate',tag:'CHANGE IN AZIMUTH',note:'Signed change in azimuth per 100 ft of measured depth.'},
  {at:30,end:32,key:'tvd',title:'True vertical depth',tag:'DEPTH',note:'Relative TVD below each well’s reference. Not subsea elevation.'},
  {at:32,end:34,key:'md',title:'Measured depth',tag:'DISTANCE ALONG THE WELL',note:'Source measured depth follows the survey down the wellbore.'},
  {at:34,end:36,key:'departure',title:'Horizontal departure',tag:'LATERAL DISPLACEMENT',note:'Horizontal distance from each branch’s first available station.'},
  {at:36,end:39,key:'gamma',title:'Gamma ray',tag:'WELL LOGS IN 3D',note:'Measured gamma ray along four observed vertical survey branches.'},
  {at:39,end:42,key:'cbl',title:'CBL amplitude',tag:'WELL LOGS IN 3D',note:'Measured cement-bond log amplitude along the same four wells.'},
  {at:42,end:48,key:'oil',title:'Oil over time',tag:'MONTHLY PRODUCTION',note:'Watch production change across the same well paths, from 2016 to 2024.'},
  {at:48,end:50,key:'end',title:'Keep exploring',tag:'ONE CONNECTED VIEW',note:'From statewide context to well geometry, measured logs and production.'}
];
export const shotAt=t=>TOUR_SHOTS.find(s=>t<s.end)||TOUR_SHOTS.at(-1);
