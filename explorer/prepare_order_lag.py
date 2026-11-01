"""Order-to-drill lag, and whether hearing volume leads drilling.

Part 1, lag. For every spacing unit, two kinds of event:
- spacing: the unit's first dated linked order (the land's earliest order);
- density: each later dated order that raised the unit's well allowance.
The lag is the time from the order's signing to the first spud of a well assigned to the unit
(largest share of lateral, geometry only). A unit with no well yet is censored at the Well Index
date; a density increase with no well before the next increase is censored at that increase.
Medians and drilled-within shares are Kaplan-Meier estimates, so undrilled units count.
Spacing units whose first well was spudded more than LEAD_DAYS before the order are left out
(an earlier order is probably missing); a first spud within LEAD_DAYS before signing counts as
drilled at once (operators spud while the signed order is pending after the hearing).

Part 2, leading indicator. Monthly Bakken hearing orders (signing month) by type against monthly
horizontal spuds statewide (the NDIC Well Index has no rig count; spuds are drilling activity).
Both are 3-month sums compared year over year (log change), so the shared boom and bust trend
does not pass for a relation. For leads of 0-24 months: the correlation of order growth now with
spud growth later, and an out-of-sample test: does adding order growth to a model that already
knows spud growth forecast spuds h months ahead any better? Negative leads, and the reverse test
(spuds forecasting orders), check whether drilling leads the hearings instead.

Inputs: dsu-orders.json, dsu-well-membership.json, DSU geojson (acres), the NDIC Well Index, the
order timeline (order_timeline.json: every hearing order with signing date, type, Bakken flag).
Requires numpy.
"""
from __future__ import annotations
import argparse
import collections
import datetime
import json
import math
import pathlib
import re
import time

import numpy as np

from prepare_dsu_headroom import parse_spud, permit_key, read_well_index, unit_timeline, assign_exclusive, pool_class, MIN_INSIDE_FT
from prepare_density_payoff import increases

LEAD_DAYS = 120
ERAS = [(2000, 2009, '2000-2009'), (2010, 2014, '2010-2014 boom'), (2015, 2016, '2015-2016 downturn'),
        (2017, 2019, '2017-2019 recovery'), (2020, 2021, '2020-2021 pandemic'), (2022, 2026, '2022-2026')]
ORDER_TYPES = {'Spacing & field rules': 'spacing', 'Increased density': 'density', 'Pooling': 'pooling'}
SERIES_START = '2006-01'
SMOOTH = 3
LEADS = range(-18, 25)
TEST_LEADS = (6, 12, 18)
TEST_FROM = '2013-01'
MIN_GROUP = 30


def era(year):
    return next((name for lo, hi, name in ERAS if lo <= year <= hi), None)


def days(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def kaplan_meier(durations, observed):
    """[(t, survival)] at each distinct event time: share of events not yet drilled by t."""
    pairs = sorted(zip(durations, observed))
    at_risk, s, out, i = len(pairs), 1.0, [], 0
    while i < len(pairs):
        t = pairs[i][0]; d = c = 0
        while i < len(pairs) and pairs[i][0] == t:
            d += pairs[i][1]; c += 1; i += 1
        if d:
            s *= 1 - d / at_risk
            out.append((t, s))
        at_risk -= c
    return out


def survival_at(curve, t):
    s = 1.0
    for x, v in curve:
        if x > t:
            break
        s = v
    return s


def km_summary(rows):
    """Median lag and drilled-within shares (months) for event rows with lagDays/observed."""
    curve = kaplan_meier([r['lagDays'] for r in rows], [r['observed'] for r in rows])
    median = next((t for t, s in curve if s <= 0.5), None)
    within = lambda m: round(1 - survival_at(curve, m * 30.44), 3)
    return {'events': len(rows), 'drilled': sum(r['observed'] for r in rows),
            'medianMonths': round(median / 30.44, 1) if median is not None else None,
            'within6': within(6), 'within12': within(12), 'within24': within(24),
            'atOnce': round(sum(r['observed'] and r['lagDays'] == 0 for r in rows) / len(rows), 3) if rows else None}


def month_index(m):
    return int(m[:4]) * 12 + int(m[5:7]) - 1


def month_name(i):
    return f'{i // 12:04}-{i % 12 + 1:02}'


def yoy(values, smooth=SMOOTH):
    """Year-over-year log change of a trailing `smooth`-month sum; NaN where not defined."""
    v = np.asarray(values, float)
    s = np.convolve(v, np.ones(smooth), 'full')[:len(v)]
    s[:smooth - 1] = np.nan
    out = np.full(len(v), np.nan)
    out[12:] = np.log1p(s[12:]) - np.log1p(s[:-12])
    return out


def corr(a, b):
    ok = ~(np.isnan(a) | np.isnan(b))
    return float(np.corrcoef(a[ok], b[ok])[0, 1]) if ok.sum() > 24 else None


def lead_corr(x, y, h):
    """Correlation of x now with y h months later (h < 0: y h months earlier)."""
    if h < 0:
        return corr(x[-h:], y[:len(y) + h])
    return corr(x[:len(x) - h] if h else x, y[h:])


def forecast_test(x, y, h, start):
    """Out-of-sample: y[t+h] from y[t] alone vs y[t] and x[t], refit on all data known at t.

    Returns RMSEs and skill = 1 - RMSE(with x) / RMSE(y alone); positive means x helps.
    """
    errors_ar, errors_x, hits_ar, hits_x = [], [], [], []
    for t in range(start, len(y) - h):
        train = [k for k in range(t - h + 1) if not (math.isnan(y[k]) or math.isnan(x[k]) or math.isnan(y[k + h]))]
        if len(train) < 36 or math.isnan(y[t]) or math.isnan(x[t]) or math.isnan(y[t + h]):
            continue
        target = np.array([y[k + h] for k in train])
        a = np.column_stack([np.ones(len(train)), [y[k] for k in train]])
        b = np.column_stack([a, [x[k] for k in train]])
        pa = np.array([1, y[t]]) @ np.linalg.lstsq(a, target, rcond=None)[0]
        pb = np.array([1, y[t], x[t]]) @ np.linalg.lstsq(b, target, rcond=None)[0]
        errors_ar.append(y[t + h] - pa); errors_x.append(y[t + h] - pb)
        hits_ar.append((pa > 0) == (y[t + h] > 0)); hits_x.append((pb > 0) == (y[t + h] > 0))
    if not errors_ar:
        return None
    rmse = lambda e: float(np.sqrt(np.mean(np.square(e))))
    return {'lead': h, 'forecasts': len(errors_ar), 'rmseSpudsOnly': round(rmse(errors_ar), 4), 'rmseWithOrders': round(rmse(errors_x), 4),
            'skill': round(1 - rmse(errors_x) / rmse(errors_ar), 3),
            'directionSpudsOnly': round(float(np.mean(hits_ar)), 3), 'directionWithOrders': round(float(np.mean(hits_x)), 3)}


SUFFIX = r'\b(INC|CORP|CORPORATION|CO|COMPANY|LLC|L L C|LP|L P|LTD|LIMITED|PARTNERSHIP|USA|U S A|US)\b'
ALIASES = {'HESS BAKKEN INVESTMENTS II': 'HESS', 'ST MARY LAND & EXPL': 'SM ENERGY', 'ST MARY LAND & EXPLORATION': 'SM ENERGY',
           'BURLINGTON RESOURCES OIL & GAS': 'BURLINGTON RESOURCES', 'MARATHON OIL': 'MARATHON', 'STATOIL OIL & GAS': 'STATOIL',
           'WHITING OIL & GAS': 'WHITING', 'EQUINOR ENERGY': 'EQUINOR'}


def operator_name(s):
    """One name per operator: '&' for AND, no punctuation or corporate suffixes, a few known aliases."""
    key = re.sub(r'[.,()]', ' ', (s or '').upper()).replace(' AND ', ' & ')
    key = re.sub(r'\bPETRO- ', 'PETRO-', key)
    key = re.sub(SUFFIX, ' ', key)
    key = re.sub(r'\s+', ' ', key).strip()
    key = ALIASES.get(key, key)
    if not key:
        return 'Unknown'
    return re.sub(r'\b(Eog|Xto|Ii|Iii|Iv|Wpx|Qep|Nd|Sm|Hrc|Oxy|Bta|Mdu)\b', lambda m: m.group(1).upper(), key.title())


def build_lag(orders, applicants, unit_wells, spud, operator_of, cutoff):
    stats = collections.Counter(); events = []
    for unit, entry in orders.items():
        timeline = unit_timeline(entry)
        if not timeline['start']:
            continue
        dated = sorted(d for d in (spud.get(p) for p in unit_wells.get(unit, [])) if d)
        history = sorted((h for h in entry.get('footprints', [{}])[0].get('history', []) if h.get('date')), key=lambda h: h['date'])
        pool = entry.get('footprints', [{}])[0].get('pool')
        acres = entry.get('footprints', [{}])[0].get('acres')

        def first_spud(since, until=None):
            return next((d for d in dated if d >= since and (until is None or d < until)), None)

        def add(kind, date, order, until, first, **extra):
            lag = days(date, first) if first else days(date, until or cutoff)
            first_permit = next((p for p in unit_wells.get(unit, []) if spud.get(p) == first), None) if first else None
            applicant = applicants.get(str(order)) or (operator_of.get(first_permit) if first_permit else None)
            events.append({'unit': unit, 'kind': kind, 'date': date, 'year': int(date[:4]), 'era': era(int(date[:4])), 'order': order,
                           'operator': operator_name(applicant), 'pool': pool, 'acres': acres, 'firstSpud': first,
                           'lagDays': max(0, lag), 'observed': bool(first), **extra})

        # Spacing: the land's first dated order.
        start = timeline['start']
        first_order = next(h for h in history if h['date'] == start)
        lead_from = (datetime.date.fromisoformat(start) - datetime.timedelta(days=LEAD_DAYS)).isoformat()
        if dated and dated[0] < lead_from:
            stats['spacing_predrilled'] += 1
        elif start >= '2000-01-01':
            first = first_spud(lead_from)
            add('spacing', start, first_order['order'], None, first)
            stats['spacing_events'] += 1
        # Density: each raise of the allowance, censored at the next raise.
        ups = increases(timeline)
        for i, (date, before, after) in enumerate(ups):
            if date < '2000-01-01':
                continue
            nxt = ups[i + 1][0] if i + 1 < len(ups) else None
            order = next((h['order'] for h in history if h['date'] == date and h.get('wells') == after), None)
            first = first_spud(date, nxt)
            add('density', date, order, nxt, first, fromWells=before, toWells=after)
            stats['density_events'] += 1
    return events, stats


def build(dsu_path, orders_path, membership_path, well_index_path, timeline_path, output_path):
    started = time.perf_counter()
    read = lambda p: json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    acres = {f['properties']['id']: f['properties'].get('acres') for f in read(dsu_path)['features']}
    order_file = read(orders_path)
    orders, applicants = order_file['units'], order_file.get('applicants', {})
    membership = read(membership_path)['units']
    index_rows = read_well_index(well_index_path)
    spud = {permit_key(r['FileNo']): parse_spud(r.get('SpudDate')) for r in index_rows}
    operator_of = {permit_key(r['FileNo']): r.get('OriginalOperator') or r.get('CurrentOperator') for r in index_rows}
    horizontal = [spud[permit_key(r['FileNo'])] for r in index_rows if r.get('Wellbore') in ('HORIZONTAL', 'Confidential')]
    horizontal = [d for d in horizontal if d]
    cutoff = max(horizontal)

    # Bakken wells only: a Madison or Birdbear horizontal in a Bakken unit is not its first well.
    other = {permit_key(r['FileNo']) for r in index_rows if pool_class(r.get('ProducedPools')) == 'other'}
    candidates = collections.defaultdict(dict)
    for unit, rows in membership.items():
        for r in rows:
            if r['insideFt'] >= MIN_INSIDE_FT and r['permit'] not in other:
                candidates[r['permit']][unit] = r
    unit_wells = collections.defaultdict(list)
    for permit, cands in candidates.items():
        unit_wells[assign_exclusive(cands, acres)].append(permit)

    events, stats = build_lag(orders, applicants, unit_wells, spud, operator_of, cutoff)

    def grouped(key, minimum=1, order=None):
        out = []
        for kind in ('spacing', 'density'):
            g = collections.defaultdict(list)
            for e in events:
                if e['kind'] == kind and e[key] is not None:
                    g[e[key]].append(e)
            rows = [{'kind': kind, 'name': k, **km_summary(v)} for k, v in g.items() if len(v) >= minimum]
            out += sorted(rows, key=(lambda r: order.index(r['name'])) if order else (lambda r: (-r['events'], str(r['name']))))
        return out

    curves = {}
    for kind in ('spacing', 'density'):
        rows = [e for e in events if e['kind'] == kind]
        curve = kaplan_meier([e['lagDays'] for e in rows], [e['observed'] for e in rows])
        curves[kind] = [{'month': m, 'drilled': round(1 - survival_at(curve, m * 30.44), 4)} for m in range(0, 61)]
    for name in [n for _, _, n in ERAS]:
        for kind in ('spacing', 'density'):
            rows = [e for e in events if e['kind'] == kind and e['era'] == name]
            if len(rows) >= MIN_GROUP:
                curve = kaplan_meier([e['lagDays'] for e in rows], [e['observed'] for e in rows])
                curves[f'{kind}|{name}'] = [{'month': m, 'drilled': round(1 - survival_at(curve, m * 30.44), 4)} for m in range(0, 61)]

    # Part 2: monthly series.
    last = month_index(cutoff[:7]) - 1  # last complete month
    first = month_index(SERIES_START)
    months = [month_name(i) for i in range(first, last + 1)]
    pos = {m: i for i, m in enumerate(months)}
    spuds = np.zeros(len(months)); counts = {k: np.zeros(len(months)) for k in ('all', 'spacing', 'density', 'pooling')}
    for d in horizontal:
        if d[:7] in pos:
            spuds[pos[d[:7]]] += 1
    timeline = read(timeline_path)['rows']
    for r in timeline:
        if not r.get('date') or not r.get('bakken') or r['date'][:7] not in pos:
            continue
        i = pos[r['date'][:7]]
        counts['all'][i] += 1
        if r['type'] in ORDER_TYPES:
            counts[ORDER_TYPES[r['type']]][i] += 1
    growth_spuds = yoy(spuds)
    test_start = pos[TEST_FROM]
    leads, tests = [], []
    for series, values in counts.items():
        g = yoy(values)
        for h in LEADS:
            leads.append({'series': series, 'lead': h, 'growthCorr': round(lead_corr(g, growth_spuds, h), 3),
                          'levelCorr': round(lead_corr(values, spuds, h), 3)})
        for h in TEST_LEADS:
            t = forecast_test(g, growth_spuds, h, test_start)
            if t:
                tests.append({'series': series, **t})
    # The reverse question: does spud growth now forecast order growth later?
    reverse = []
    for series, values in counts.items():
        for h in TEST_LEADS:
            t = forecast_test(growth_spuds, yoy(values), h, test_start)
            if t:
                reverse.append({'series': series, **t})
    best = {s: max((r for r in leads if r['series'] == s), key=lambda r: r['growthCorr']) for s in counts}
    robustness = []
    for smooth in (3, 6, 12):
        gs = yoy(spuds, smooth)
        for series, values in counts.items():
            g = yoy(values, smooth)
            prof = [(h, lead_corr(g, gs, h)) for h in LEADS]
            h, c = max(prof, key=lambda x: x[1] if x[1] is not None else -9)
            robustness.append({'smooth': smooth, 'series': series, 'bestLead': h, 'corr': round(c, 3),
                               'corrAt12Ahead': round(dict(prof)[12], 3)})
    monthly = [{'month': m, 'spuds': int(spuds[i]), **{k: int(v[i]) for k, v in counts.items()},
                'spudGrowth': None if math.isnan(growth_spuds[i]) else round(float(growth_spuds[i]), 4),
                'orderGrowth': None if math.isnan(yoy(counts['all'])[i]) else round(float(yoy(counts['all'])[i]), 4)} for i, m in enumerate(months)]

    summary = {**dict(stats), 'wellIndexDate': cutoff, 'spacing': km_summary([e for e in events if e['kind'] == 'spacing']),
               'density': km_summary([e for e in events if e['kind'] == 'density']),
               'bestLead': {s: {'lead': r['lead'], 'growthCorr': r['growthCorr']} for s, r in best.items()},
               'months': [months[0], months[-1]]}
    result = {'version': 1, 'createdAtUTC': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'method': {'events': 'Spacing: a unit\'s first dated linked order. Density: each dated order that raised its allowance. Lag: signing date to the first spud of a well assigned to the unit (largest lateral share).',
                         'censoring': f'Kaplan-Meier: units with no well yet count as undrilled to {cutoff}; a density increase with no well before the next increase is censored there. A first spud up to {LEAD_DAYS} days before signing counts as lag 0; spacing units with earlier wells are left out.',
                         'operator': 'Applicant on the order where known, else the original operator of the first well.',
                         'wells': 'Wells whose Well Index pools are all non-Bakken (Madison unit horizontals, Birdbear re-entries) do not count as a first spud.',
                         'series': f'Bakken-flagged hearing orders by signing month and type; horizontal spuds statewide from the Well Index. Growth = log change of a {SMOOTH}-month sum over the same months a year earlier.',
                         'test': f'Out of sample from {TEST_FROM}: spud growth h months ahead forecast from current spud growth, with and without current order growth, refit each month on data known then. Skill = 1 - RMSE(with orders)/RMSE(spuds only). reverseTests swap the roles: order growth forecast with and without spud growth.',
                         'leads': 'growthCorr at lead h: order growth in month t against spud growth in month t+h; negative h compares with spuds h months earlier.',
                         'limitations': ['Spuds stand in for rigs: wells per rig rose several-fold, so spuds and rig counts diverge over time.',
                                         'Order dates are signing dates, a month or two after the hearing.', 'Confidential wells without a spud date are missing from recent months.',
                                         'Lag needs the order linked to a DSU; orders for units no longer in the DMR layer are absent.',
                                         'Two full cycles (2014-16 and 2020) dominate the series; the test has few independent turns.']},
              'summary': summary, 'byEra': grouped('era', 1, [n for _, _, n in ERAS]), 'byYear': grouped('year', 5),
              'byOperator': grouped('operator', MIN_GROUP), 'curves': curves, 'monthly': monthly, 'leads': leads, 'tests': tests, 'reverseTests': reverse, 'robustness': robustness,
              'events': sorted(events, key=lambda e: (e['date'], e['unit']))}
    pathlib.Path(output_path).write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({**summary, 'tests': tests, 'reverseTests': reverse, 'robustness': robustness, 'seconds': round(time.perf_counter() - started, 1)}, indent=1))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dsus'); parser.add_argument('orders'); parser.add_argument('membership'); parser.add_argument('well_index')
    parser.add_argument('timeline', help='order_timeline.json'); parser.add_argument('output')
    a = parser.parse_args(); build(a.dsus, a.orders, a.membership, a.well_index, a.timeline, a.output)
