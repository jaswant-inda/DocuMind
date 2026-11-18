"""Run retrieval evaluation against a running backend using stdlib HTTP."""
import argparse,json,statistics,time,urllib.request
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument("--url",default="http://localhost:8000");p.add_argument("--k",type=int,default=4);a=p.parse_args()
    cases=json.loads(Path(__file__).with_name("testset.json").read_text());ranks=[];latencies=[]
    for case in cases:
        body=json.dumps({"question":case["question"],"top_k":a.k}).encode()
        req=urllib.request.Request(a.url+"/query",data=body,headers={"Content-Type":"application/json"})
        start=time.perf_counter()
        with urllib.request.urlopen(req,timeout=90) as response: data=json.loads(response.read())
        latencies.append((time.perf_counter()-start)*1000);sources=data.get("sources",[])
        rank=next((i for i,s in enumerate(sources,1) if s["source_file"]==case["expected_source_file"] and s["page_number"]==case["expected_page"]),None)
        ranks.append(rank)
    hit=sum(x is not None for x in ranks)/len(ranks);mrr=sum(1/x if x else 0 for x in ranks)/len(ranks)
    print(f"cases={len(cases)} hit-rate@{a.k}={hit:.3f} MRR={mrr:.3f} avg-latency-ms={statistics.mean(latencies):.1f}")
if __name__=="__main__":main()
