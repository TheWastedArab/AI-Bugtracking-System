import json
from pathlib import Path
from unittest.mock import patch
import pytest
from backend.datasets import normalize
from backend.training import split_rows, text, train_severity
from backend.openapi_export import to_openapi30
from test_api import setup


def test_dataset_normalization_uses_early_features_and_hides_emails(tmp_path):
    source=tmp_path/'source';source.mkdir()
    records={'1':{'opening':10,'current_resolution':'FIXED'},'2':{'opening':20,'current_resolution':'DUPLICATE'}}
    (source/'reports.json').write_text(json.dumps({'reports':records}))
    fields={'short_desc':{'1':[{'when':10,'what':'Original title'},{'when':30,'what':'Later secret fix'}],'2':[{'when':20,'what':'Other report'}]},
            'severity':{'1':[{'when':10,'what':'normal'}],'2':[{'when':20,'what':'enhancement'}]},
            'component':{'1':[{'when':10,'what':'core'}]},'assigned_to':{'1':[{'when':15,'what':'developer@example.com'}]}}
    for key,value in fields.items():(source/f'{key}.json').write_text(json.dumps({key:value}))
    output=tmp_path/'normalized.jsonl';summary=normalize(source,output)
    row=json.loads(output.read_text())
    assert summary['normalized_reports']==1
    assert row['title']=='Original title' and row['severity']=='Medium'
    assert '@' not in row['assignee'] and row['duplicate_of'] is None


def test_training_split_and_serialized_inference(tmp_path):
    rows=[]
    for i in range(80):
        label=['Low','Medium','High','Critical'][i%4]
        rows.append({'title':f'{label} unique report number {i}','severity':label,'created_at':i+1,'label_at':i+1})
    train,test=split_rows(rows+[rows[0]])
    assert len(train)==64 and len(test)==16
    assert max(r['created_at'] for r in train)<min(r['created_at'] for r in test)
    with pytest.raises(ValueError):split_rows(rows[:3])
    output=tmp_path/'severity.joblib'
    result=train_severity(rows,output,cv=2)
    assert output.is_file() and len(result['confusion_matrix'])==4
    assert len(result['cv_macro_f1'])==2
    from backend import ai
    with patch.dict('os.environ',{'SEVERITY_MODEL':str(output)}):
        assert ai.severity('Critical unique report',{'rule_severity':False})[1]=='trained'
    output.write_text('invalid artifact')
    with patch.dict('os.environ',{'SEVERITY_MODEL':str(output)}):
        assert ai.severity('test',{'rule_severity':False})[0]=='Unclassified'
    assert 'duplicate_False' in text({'title':'test','duplicate':True},True)


def test_openapi_compatibility():
    from backend.main import app
    schema=to_openapi30(app.openapi())
    assert schema['openapi']=='3.0.3'
    assert '"type": "null"' not in json.dumps(schema)
    validator=pytest.importorskip('openapi_spec_validator')
    validator.validate(schema)


def test_authentication_rate_limit(setup):
    client,headers,project,factory=setup
    for i in range(10):
        assert client.post('/auth/resend',json={'email':'absent@example.com'}).status_code==202
    response=client.post('/auth/resend',json={'email':'absent@example.com'})
    assert response.status_code==429
    assert response.headers['retry-after']=='60'


def test_cached_sparse_bm25_preserves_reference_scores():
    import numpy as np
    from rank_bm25 import BM25Okapi
    from backend.ai import bm25_matrix
    corpus=[['checkout','crash','crash'],['payment','failure'],['editor','crash'],['cosmetic','typo']]
    reference=BM25Okapi(corpus)
    vocabulary,matrix=bm25_matrix(reference)
    query=['checkout','crash','crash']
    scores=np.asarray(matrix[:,[vocabulary[word] for word in query]].sum(axis=1)).ravel()
    assert np.allclose(scores,reference.get_scores(query),atol=1e-6)
