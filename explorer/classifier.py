"""Transparent geometry-based well section classifier, with MD-based persistence.

Drillback is a user-defined visualization category, not evidence of a drilling
operation. Thresholds are tunable heuristics rather than industry standards.
Input stations must belong to ONE branch, sorted by strictly increasing MD.
"""
from dataclasses import asdict, dataclass
import numpy as np


@dataclass(frozen=True)
class Settings:
    vertical_max_deg: float = 6.5
    lateral_min_deg: float = 85.0
    curve_rate_deg_per_100ft: float = 4.5
    upper_well_max_deg: float = 35.0
    departure_start_deg: float = 3.0
    departure_min_ft: float = 75.0
    persistence_ft: float = 150.0
    min_stations: int = 3
    landing_context_deg: float = 70.0
    build_window_ft: float = 250.0
    main_build_rate_deg_per_100ft: float = 0.5
    max_survey_gap_ft: float = 1000.0

    def __post_init__(self):
        if not all(np.isfinite(v) and v > 0 for v in asdict(self).values()):
            raise ValueError('Classifier thresholds must be positive finite numbers.')
        if not (self.departure_start_deg < self.vertical_max_deg < self.upper_well_max_deg < self.landing_context_deg < self.lateral_min_deg <= 90):
            raise ValueError('Inclination thresholds must be in increasing order.')
        if not isinstance(self.min_stations, int) or self.min_stations < 3:
            raise ValueError('min_stations must be an integer >= 3.')


def runs(mask):
    edges=np.diff(np.r_[False,mask,False].astype(np.int8))
    return zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1))


def classify(stations, horizontal, settings=None):
    """Return section codes and reviewable intervals. stations: MD, inc, azi.

    horizontal: east/north coordinates in feet (either north sign is accepted).
    All masks use measured depth and minimum station evidence. Labels describe
    the incoming station segment. Never connect or derive rates across branches.
    """
    cfg=settings or Settings()
    a=np.asarray(stations,dtype=float);xy=np.asarray(horizontal,dtype=float)
    if a.ndim!=2 or a.shape[1]!=3 or xy.shape!=(len(a),2):
        raise ValueError('Expected Nx3 stations and Nx2 horizontal coordinates.')
    if not np.isfinite(a).all() or not np.isfinite(xy).all():
        raise ValueError('Station coordinates and survey values must be finite.')
    if len(a)==0:return np.empty(0,dtype=np.int8),[]
    md,raw,azi=a.T
    if np.any(np.diff(md)<=0):raise ValueError('MD must strictly increase within each branch.')
    # Detect separately across large survey gaps: no inferred excursion can bridge them.
    breaks=np.r_[0,np.flatnonzero(np.diff(md)>cfg.max_survey_gap_ft)+1,len(a)]
    if len(breaks)>2:
        labels=np.empty(len(a),dtype=np.int8);intervals=[]
        for lo,hi in zip(breaks,breaks[1:]):
            labels[lo:hi],found=classify(a[lo:hi],xy[lo:hi],cfg);intervals.extend(found)
        return labels,intervals
    inc=raw.copy()
    if len(a)>2:inc[1:-1]=np.median(np.stack([raw[:-2],raw[1:-1],raw[2:]]),axis=0)
    dmd=np.r_[np.nan,np.diff(md)];dmd[dmd<.1]=np.nan
    build=np.r_[np.nan,np.diff(raw)]/dmd*100
    ang=np.radians(raw);dazi=np.radians(np.r_[np.nan,(np.diff(azi)+180)%360-180])
    dogleg=np.degrees(np.arccos(np.clip(np.cos(np.r_[np.nan,ang[:-1]])*np.cos(ang)+np.sin(np.r_[np.nan,ang[:-1]])*np.sin(ang)*np.cos(dazi),-1,1)))/dmd*100
    section=np.select([raw<=cfg.vertical_max_deg,raw>=cfg.lateral_min_deg,(dogleg>=cfg.curve_rate_deg_per_100ft)|(np.abs(build)>=cfg.curve_rate_deg_per_100ft)],[0,4,2],default=1).astype(np.int8)
    # Protect the sustained terminal build, backtracking through positive MD-window
    # build until a tangent/return. Without a landing, protect an unclosed final
    # departure above the upper-well angle cap rather than guessing its purpose.
    main_start=len(a)
    landing=None
    for lo,hi in runs(inc>=cfg.landing_context_deg):
        if hi-lo>=cfg.min_stations and md[hi-1]-md[lo]>=cfg.persistence_ft:
            landing=lo;break
    if landing is None:
        high=np.flatnonzero(inc>cfg.upper_well_max_deg)
        if len(high):landing=int(high[0])
    if landing is not None:
        main_start=landing
        j=landing
        while j>0:
            k=max(0,int(np.searchsorted(md,md[j]-cfg.build_window_ft,side='right'))-1)
            if k==j:k=j-1
            rate=(inc[j]-inc[k])/(md[j]-md[k])*100
            # Backtracking may include a few flat stations at kickoff; trim to
            # the last near-minimum angle in the final window.
            if rate<cfg.main_build_rate_deg_per_100ft:break
            main_start=k;j=k
        if main_start<landing:
            low=inc[main_start]
            flat=np.flatnonzero(inc[main_start:landing+1]<=low+1.0)
            if len(flat):main_start+=int(flat[-1])
    eligible=(np.arange(len(a))<main_start)&(inc<=cfg.upper_well_max_deg)
    intervals=[];drill=np.zeros(len(a),dtype=bool)

    def add(lo,hi,reason):
        if hi-lo<cfg.min_stations or md[hi-1]-md[lo]<cfg.persistence_ft:return
        # Keep the anchor as its original section; color outgoing excursion
        # segments through their endpoint stations.
        section[lo+1:hi]=3;drill[lo+1:hi]=True
        departure=float(np.linalg.norm(xy[lo:hi]-xy[lo],axis=1).max())
        intervals.append({'mdStart':round(float(md[lo]),1),'mdEnd':round(float(md[hi-1]),1),'reason':reason,'peakInclination':round(float(inc[lo:hi].max()),2),'maxDepartureFt':round(departure,1)})

    # Color a pronounced sideways episode, including its outbound deflection.
    # A subsequent return to vertical is optional under the requested definition.
    for lo,hi in runs(eligible & (inc>=cfg.departure_start_deg)):
        start=max(0,lo-1);end=min(len(a),hi+1) if hi<len(a) and eligible[hi] else hi
        if hi-lo<cfg.min_stations or md[hi-1]-md[lo]<cfg.persistence_ft:continue
        departure=float(np.linalg.norm(xy[lo:hi]-xy[start],axis=1).max())
        if departure>=cfg.departure_min_ft:
            add(start,end,'Pronounced sideways deviation in vertical interval')

    # Smooth non-drillback singletons without erasing drillback evidence or
    # converting a raw near-horizontal observation to a different section.
    original=section.copy()
    for j in range(1,len(a)-1):
        if not drill[j] and original[j-1]==original[j+1] and original[j-1]!=3 and raw[j]<cfg.lateral_min_deg:section[j]=original[j-1]
    return section,intervals
