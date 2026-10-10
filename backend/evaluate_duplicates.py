"""Evaluate retrieval from a JSONL corpus that includes actual duplicate_of IDs."""
import argparse
import json
from pathlib import Path
import numpy as np
from rank_bm25 import BM25Okapi
from .ai import tokens, semantic_model
from .training import read_rows, text


def evaluate(rows, model_path=None):
    rows=sorted(rows,key=lambda r:r['created_at'])
    pairs=[r for r in rows if r.get('duplicate_of') is not None]
    if not pairs:
        raise ValueError('No linked duplicate_of IDs. DUPLICATE status alone cannot establish retrieval ground truth.')
    corpus=[tokens(text(row)) or ['empty'] for row in rows]
    model=semantic_model(model_path) if model_path else None
    ranks=[];missing=0
    for query in pairs:
        eligible=[i for i,r in enumerate(rows) if r['created_at']<query['created_at']]
        target=next((i for i in eligible if str(rows[i]['id'])==str(query['duplicate_of'])),None)
        if target is None:
            missing+=1;continue
        index=BM25Okapi([corpus[i] for i in eligible])
        scores=index.get_scores(tokens(text(query)))
        top=[eligible[i] for i in sorted(range(len(eligible)),key=lambda i:scores[i],reverse=True)[:50]]
        if model and top:
            vectors=model.encode([text(query)]+[text(rows[i]) for i in top],normalize_embeddings=True)
            top=[top[i] for i in np.argsort(-(vectors[1:]@vectors[0]))]
        ranks.append(top.index(target)+1 if target in top else 1000000)
    if not ranks:raise ValueError('No duplicate targets occur earlier in the supplied corpus')
    return {'queries':len(ranks),'excluded_missing_or_future_targets':missing,'recall':{str(k):sum(r<=k for r in ranks)/len(ranks) for k in [1,5,10]},
            'mrr':sum(1/r if r<=50 else 0 for r in ranks)/len(ranks),
            'mean_average_precision':sum(1/r if r<=50 else 0 for r in ranks)/len(ranks),
            'note':'One relevant original per query; MAP equals MRR. Retrieval corpus is restricted to older reports.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('dataset');parser.add_argument('--model');parser.add_argument('--output',default='artifacts/duplicates.metrics.json');args=parser.parse_args()
    result=evaluate(read_rows(args.dataset),args.model);Path(args.output).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
