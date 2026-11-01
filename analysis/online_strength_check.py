"""Bounded production read-only HTTPS verification. Never invokes the assistant."""
import asyncio
import hashlib
import json
import math
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import httpx

BASE = 'https://api-production-bb05d.up.railway.app'
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'analysis/online-strength-latest.json'
TOKEN = None
for line in (ROOT / '.env.local').read_text().splitlines():
    if line.startswith('CRM_TOKEN='):
        TOKEN = line.split('=', 1)[1].strip().strip('\"\'')
assert TOKEN, 'Local credential missing'
KINDS = ['companies', 'contacts', 'deals', 'products', 'line_items', 'tickets', 'notes', 'tasks', 'meetings', 'calls', 'emails']
report = {'started_at': datetime.now(timezone.utc).isoformat(), 'base_url': BASE,
          'deployment_verified_before': 'feec912b-c7b0-40e5-8648-3eaa217bc17e',
          'model_calls': 0, 'business_writes': 0, 'phases': [], 'checks': {}}

def save():
    OUT.write_text(json.dumps(report, indent=2))

def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

async def main():
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
    async with httpx.AsyncClient(base_url=BASE, timeout=10, limits=limits, headers={'Authorization': 'Bearer ' + TOKEN}) as api, httpx.AsyncClient(base_url=BASE, timeout=10) as ui:
        h = await ui.get('/health'); h.raise_for_status()
        report['health_before'] = h.json()
        auth = []
        for path in ['/crm/v3/objects/companies', '/crm/objects/2026-09/companies', '/openapi.json']:
            for headers in [{}, {'Authorization': 'Bearer invalid-strength-check'}]:
                r = await ui.get(path, headers=headers)
                auth.append(r.status_code == 401)
        report['checks']['bearer_rejections'] = all(auth)
        assert all(auth), 'Authentication regression'
        samples = {}
        totals = {}
        for kind in KINDS:
            r = await api.post(f'/crm/objects/2026-09/{kind}/search', json={'limit': 5})
            r.raise_for_status()
            data = r.json(); totals[kind] = data['total']
            if data['results']:
                samples[kind] = [str(x['id']) for x in data['results']]
        report['totals_before'] = totals
        record_jobs = []
        baseline = {}
        for kind, ids in samples.items():
            for ident in ids:
                path = f'/crm/objects/2026-09/{kind}/{ident}'
                r = await api.get(path); r.raise_for_status()
                baseline[path] = digest(r.json())
                record_jobs.append(('record', 'GET', path, None))
        async def phase(name, jobs, n, concurrency):
            queue = asyncio.Queue()
            for i in range(n): queue.put_nowait(jobs[i % len(jobs)])
            results = []; stopped = False
            async def worker():
                nonlocal stopped
                while not queue.empty() and not stopped:
                    group, method, path, body = queue.get_nowait()
                    start = time.perf_counter()
                    try:
                        r = await api.request(method, path, json=body) if body is not None else await api.request(method, path)
                        status = r.status_code
                        valid = status == 200
                        if valid:
                            data = r.json()
                            if group == 'record': valid = digest(data) == baseline[path]
                            elif group == 'search': valid = data['total'] == totals[path.split('/')[-2]]
                            else: valid = isinstance(data.get('results'), list)
                    except Exception as exc:
                        status = type(exc).__name__; valid = False
                    results.append((group, status, time.perf_counter()-start, valid))
                    if not valid: stopped = True
            start = time.perf_counter()
            await asyncio.gather(*(worker() for _ in range(concurrency)))
            groups = {}
            for group in sorted({x[0] for x in results}):
                rows = [x for x in results if x[0] == group]; durations = sorted(x[2] for x in rows)
                groups[group] = {'requests': len(rows), 'statuses': dict(Counter(str(x[1]) for x in rows)), 'content_valid': all(x[3] for x in rows), 'p50_ms': round(durations[len(rows)//2]*1000, 1), 'p95_ms': round(durations[math.ceil(len(rows)*.95)-1]*1000, 1), 'max_ms': round(max(durations)*1000, 1)}
            result = {'name': name, 'concurrency': concurrency, 'planned': n, 'completed': len(results), 'elapsed_seconds': round(time.perf_counter()-start, 2), 'groups': groups}
            report['phases'].append(result); save(); print(json.dumps(result), flush=True)
            assert not stopped, 'Load stopped after response/content failure'
        await phase('warmup', record_jobs, 100, 5)
        await phase('single_record_20', record_jobs, 1000, 20)
        mixed = list(record_jobs[:12])
        for kind in samples:
            mixed.extend([('search', 'POST', f'/crm/objects/2026-09/{kind}/search', {'limit': 20}), ('pagination', 'GET', f'/crm/v3/objects/{kind}?limit=50', None)])
        await phase('mixed_reads_20', mixed, 600, 20)
        seen = set(); after = None; pages = 0
        while True:
            params = {'limit':100}
            if after is not None: params['after'] = after
            r = await api.get('/crm/objects/2026-09/companies', params=params); r.raise_for_status(); d = r.json()
            ids = [str(x['id']) for x in d['results']]
            assert len(ids) == len(set(ids)) and not seen.intersection(ids), 'Duplicate pagination IDs'
            seen.update(ids); pages += 1
            after = d.get('paging', {}).get('next', {}).get('after')
            if after is None: break
            assert pages < 1000, 'Pagination did not terminate'
        report['checks']['company_pagination'] = {'pages': pages, 'unique_records': len(seen), 'matches_search_total': len(seen) == totals['companies']}
        assert len(seen) == totals['companies']
        page = await ui.get('/login'); page.raise_for_status()
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        login = await ui.post('/login', data={'csrf':csrf, 'token':TOKEN, 'next':'/'}, headers={'Origin':BASE})
        assert login.status_code == 303, 'Login failed'
        report['checks']['https_login'] = True
        cookie = login.headers.get('set-cookie', '').lower()
        report['checks']['cookie_flags'] = all(x in cookie for x in ['secure', 'httponly', 'samesite=lax'])
        r = await ui.get('/crm/objects/2026-09/companies')
        report['checks']['session_cannot_auth_api'] = r.status_code == 401
        paths = ['/', '/companies', '/companies/'+samples['companies'][0], '/deals', '/dormant-customers', '/tickets']
        uirows = []
        sem = asyncio.Semaphore(5)
        async def read_page(path):
            async with sem:
                start=time.perf_counter(); r=await ui.get(path)
                uirows.append({'path':path,'status':r.status_code,'ms':round((time.perf_counter()-start)*1000,1),'html': 'text/html' in r.headers.get('content-type','')})
        await asyncio.gather(*(read_page(p) for _ in range(5) for p in paths))
        report['ui_reads'] = uirows
        assert all(x['status']==200 and x['html'] for x in uirows), 'UI read failure'
        totals_after = {}
        for kind in KINDS:
            r=await api.post(f'/crm/objects/2026-09/{kind}/search',json={'limit':1}); r.raise_for_status(); totals_after[kind]=r.json()['total']
        report['totals_after'] = totals_after
        report['checks']['totals_unchanged'] = totals == totals_after
        stable = True
        for path, expected in baseline.items():
            r=await api.get(path); r.raise_for_status(); stable &= digest(r.json()) == expected
        report['checks']['sample_records_unchanged'] = stable
        report['sample_records_checked'] = len(baseline)
        h=await ui.get('/health'); h.raise_for_status(); report['health_after']=h.json()
        report['completed_at']=datetime.now(timezone.utc).isoformat()
        report['passed'] = all(v is not False for v in report['checks'].values())
        save(); print(json.dumps({'passed':report['passed'],'checks':report['checks'],'output':str(OUT)}),flush=True)

try:
    asyncio.run(main())
except Exception as exc:
    report['passed']=False; report['failure_type']=type(exc).__name__
    if isinstance(exc, httpx.HTTPStatusError):
        report['failed_request']={'path':exc.request.url.path,'status':exc.response.status_code}
    save()
    print('Verification stopped: '+type(exc).__name__, flush=True)
    raise SystemExit(1)
