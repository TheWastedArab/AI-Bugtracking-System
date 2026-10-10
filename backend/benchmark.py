"""Opt-in local API load measurement; run only against an isolated test project."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import time
import httpx


def run(url, token, project, concurrency=50):
    headers={'Authorization':'Bearer '+token}
    def request(index, endpoint):
        started=time.perf_counter()
        with httpx.Client(timeout=60) as client:
            if endpoint=='submit':
                response=client.post(f'{url}/projects/{project}/bugs',headers=headers,json={
                    'title':f'Load test checkout report {time.time_ns()}-{index}',
                    'description':'Synthetic load test: checkout reports a failure when an empty basket is submitted.',
                    'steps':'Submit an empty basket','environment':'Isolated load test','component':'checkout'})
            elif endpoint=='duplicates':
                response=client.post(f'{url}/projects/{project}/duplicates',headers=headers,json={
                    'title':'Checkout crash','description':'Checkout crashes when an empty basket is submitted.',
                    'steps':'Test','environment':'Load test'})
            else:
                response=client.get(f'{url}/projects/{project}/bugs?q=checkout',headers=headers)
        return {'seconds':time.perf_counter()-started,'status':response.status_code}
    results={}
    for endpoint in ['search','duplicates','submit']:
        request(0,endpoint)  # Warm up indexes and model inference.
        baseline=[request(i,endpoint) for i in range(5)]
        started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            values=list(executor.map(lambda i:request(i,endpoint),range(concurrency)))
        duration=time.perf_counter()-started
        latencies=sorted(x['seconds'] for x in values)
        mean=statistics.mean(latencies);base=statistics.mean(x['seconds'] for x in baseline)
        results[endpoint]={'requests':len(values),'successes':sum(200<=x['status']<300 for x in values),
                           'mean_seconds':mean,'p95_seconds':latencies[int(.95*(len(latencies)-1))],
                           'baseline_mean_seconds':base,'mean_degradation_percent':(mean/base-1)*100,
                           'requests_per_second':len(values)/duration}
    return {'concurrency':concurrency,'results':results,'note':'Client connection setup included; local machine and SQLite results are not production SLA evidence.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8765')
    parser.add_argument('--email',default='admin@example.com')
    parser.add_argument('--password',required=True)
    parser.add_argument('--project',type=int,default=1)
    parser.add_argument('--output',default='artifacts/load.metrics.json')
    args=parser.parse_args()
    response=httpx.post(args.url+'/auth/login',json={'email':args.email,'password':args.password})
    response.raise_for_status()
    results=run(args.url,response.json()['access_token'],args.project)
    Path(args.output).write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))
