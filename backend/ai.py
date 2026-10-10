"""Local inference only. Never downloads model weights during an API request."""
import os
import re
from functools import lru_cache
from collections import OrderedDict
from threading import RLock
from pathlib import Path
import numpy as np
from scipy.sparse import csc_matrix
from rank_bm25 import BM25Okapi
from sqlalchemy import func, select
from .models import Bug, Configuration, DeveloperProfile, Membership, ModelState, Resolution, User

_indices = OrderedDict()
_index_lock = RLock()
_embeddings = OrderedDict()
_embedding_lock = RLock()


def tokens(text):
    return re.findall(r'[a-z0-9_]+', text.lower())


def bm25_matrix(index):
    """Precompute the exact BM25 term contribution for fast sparse query sums."""
    vocabulary = {word: i for i, word in enumerate(index.idf)}
    row_ids, columns, values = [], [], []
    for row, frequencies in enumerate(index.doc_freqs):
        normalization = index.k1 * (1 - index.b + index.b * index.doc_len[row] / index.avgdl)
        for word, frequency in frequencies.items():
            row_ids.append(row)
            columns.append(vocabulary[word])
            values.append(index.idf[word] * frequency * (index.k1 + 1) / (frequency + normalization))
    return vocabulary, csc_matrix((values, (row_ids, columns)), shape=(index.corpus_size, len(vocabulary)), dtype=np.float32)


def settings(db):
    row = db.get(Configuration, 'triage')
    return {'duplicate_threshold': 0.65, 'cold_start_count': 100, 'rule_severity': False, **(row.value if row else {})}


@lru_cache(maxsize=4)
def severity_model(path, modified):
    import joblib
    return joblib.load(path)  # Only operator-provided local artifacts are accepted.


@lru_cache(maxsize=1)
def semantic_model(path):
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(2)
    return SentenceTransformer(path, local_files_only=True, device='cpu')


def vectors_for(path, texts):
    # Reuse candidate embeddings across keystrokes and concurrent requests.
    # One bounded cache per API process; no report text leaves this process.
    with _embedding_lock:
        missing = list(dict.fromkeys(text for text in texts if (path, text) not in _embeddings))
        if missing:
            vectors = semantic_model(path).encode(missing, normalize_embeddings=True)
            for text, vector in zip(missing, vectors):
                _embeddings[(path, text)] = vector
        result = np.stack([_embeddings[(path, text)] for text in texts])
        for text in texts:
            _embeddings.move_to_end((path, text))
        while len(_embeddings) > 4096:
            _embeddings.popitem(last=False)
        return result


def severity(text, config):
    path = Path(os.getenv('SEVERITY_MODEL', 'artifacts/severity.joblib'))
    if path.is_file():
        try:
            label = str(severity_model(str(path.resolve()), path.stat().st_mtime_ns).predict([text])[0])
            if label not in ('Low', 'Medium', 'High', 'Critical'):
                raise ValueError('Unknown label')
            return label, 'trained', 'Experimental model: review predictions. See evaluation results for measured accuracy.'
        except Exception:
            return 'Unclassified', 'unavailable', 'Severity model could not run; review manually.'
    if config['rule_severity']:
        words = set(tokens(text))
        label = 'Critical' if words & {'breach', 'corruption', 'outage'} else 'High' if words & {'crash', 'crashes', 'failure'} else 'Low' if words & {'typo', 'alignment', 'cosmetic'} else 'Medium'
        return label, 'rule-based', 'Keyword fallback; no trained-model confidence is available.'
    return 'Unclassified', 'unavailable', 'Severity model is not installed; review manually.'


def duplicates(db, project_id, text, limit=3):
    signature = tuple(db.execute(select(func.count(Bug.id), func.sum(Bug.version), func.max(Bug.id)).where(Bug.project_id == project_id)).one())
    key = (db.get_bind(), project_id)
    with _index_lock:
        cached = _indices.get(key)
        if cached is None or cached[0] != signature:
            rows = db.execute(select(Bug.id, Bug.title, Bug.description).where(Bug.project_id == project_id).order_by(Bug.id)).all()
            corpus = [tokens(b.title + ' ' + b.description) or ['empty'] for b in rows]
            postings = {}
            for i, words in enumerate(corpus):
                for word in set(words):
                    postings.setdefault(word, set()).add(i)
            vocabulary, matrix = bm25_matrix(BM25Okapi(corpus)) if corpus else ({}, None)
            cached = (signature, rows, corpus, vocabulary, matrix, postings)
            _indices[key] = cached
            _indices.move_to_end(key)
            while len(_indices) > 16:
                _indices.popitem(last=False)
        _, rows, corpus, vocabulary, matrix, postings = cached
    if not rows or not tokens(text):
        return {'mode': 'bm25', 'candidates': []}
    # BM25Okapi can yield non-positive IDF on tiny demo corpora; retain lexical matches.
    query = set(tokens(text))
    eligible = sorted(set().union(*(postings.get(word, set()) for word in query)))
    query_columns = [vocabulary[word] for word in tokens(text) if word in vocabulary]
    scores = np.asarray(matrix[:, query_columns].sum(axis=1)).ravel()
    if len(eligible) > 50:
        eligible_array = np.asarray(eligible)
        selected = np.argpartition(scores[eligible_array], len(eligible) - 50)[-50:]
        eligible = eligible_array[selected].tolist()
    ordered = sorted(((i, scores[i]) for i in eligible), key=lambda pair: (float(pair[1]), len(query & set(corpus[pair[0]]))), reverse=True)
    indices = [i for i, _ in ordered]
    mode = 'bm25'
    warning = 'Semantic model not installed; lexical suggestions are not duplicate probabilities.'
    ranked = [(i, float(score)) for i, score in ordered]
    model_path = os.getenv('SEMANTIC_MODEL_PATH')
    if model_path and indices:
        try:
            vectors = vectors_for(model_path, [text] + [rows[i].title + ' ' + rows[i].description for i in indices])
            ranked = sorted([(i, float(np.dot(vectors[0], vectors[n + 1]))) for n, i in enumerate(indices)], key=lambda pair: pair[1], reverse=True)
            ranked = [(i, score) for i, score in ranked if score >= settings(db)['duplicate_threshold']]
            mode, warning = 'bm25+sentence-bert', None
        except Exception:
            warning = 'Semantic inference unavailable; showing lexical suggestions.'
    return {'mode': mode, 'warning': warning, 'candidates': [
        {'id': rows[i].id, 'title': rows[i].title, 'score': round(score, 4),
         'similarity_percent': round(max(0, score) * 100, 1) if mode != 'bm25' else None}
        for i, score in ranked[:limit]]}


def model_status(db, project_id):
    count = db.scalar(select(func.count(Resolution.id)).where(Resolution.project_id == project_id)) or 0
    threshold = settings(db)['cold_start_count']
    state = db.get(ModelState, project_id)
    return {'verified_assigned_count': count, 'required_count': threshold,
            'remaining': max(0, threshold - count), 'cold_start': count < threshold,
            'status': state.status if state else 'cold_start', 'trained_at': state.trained_at if state else None,
            'error': state.error if state else None}


def workload(db, project_id, user_id):
    return db.scalar(select(func.count(Bug.id)).where(Bug.project_id == project_id, Bug.assignee_id == user_id, Bug.status.in_(['Open', 'In Progress']))) or 0


def recommendations(db, bug):
    state = model_status(db, bug.project_id)
    profiles = db.scalars(select(DeveloperProfile).join(User, User.id == DeveloperProfile.user_id)
                         .join(Membership, (Membership.user_id == User.id) & (Membership.project_id == DeveloperProfile.project_id))
                         .where(DeveloperProfile.project_id == bug.project_id, DeveloperProfile.active.is_(True), User.active.is_(True), Membership.role.in_(['developer', 'manager']))).all()
    query = set(tokens(bug.title + ' ' + bug.description))
    results = []
    trained_scores = {}
    model = db.get(ModelState, bug.project_id)
    if not state['cold_start'] and model and model.artifact:
        try:
            from .training import predict_assignment
            trained_scores = predict_assignment(model.artifact, bug)
        except Exception:
            state['error'] = 'Trained inference unavailable; using declared skills and components.'
    for profile in profiles:
        load = workload(db, bug.project_id, profile.user_id)
        if profile.availability == 'Unavailable' or load >= profile.capacity:
            continue
        skill_matches = [s for s in profile.skills if set(tokens(s)) & query]
        component_match = bug.component.lower() in profile.components
        history_count = db.scalar(select(func.count(Resolution.id)).where(Resolution.project_id == bug.project_id, Resolution.user_id == profile.user_id)) or 0
        if not trained_scores and not (profile.skills and profile.components):
            continue
        score = len(skill_matches) + 2 * component_match + (1 - load / profile.capacity)
        if trained_scores:
            score += 5 * trained_scores.get(profile.user_id, 0)
        reasons = [f'{load}/{profile.capacity} active bugs']
        if skill_matches:
            reasons.append('Skills: ' + ', '.join(skill_matches))
        if component_match:
            reasons.append('Declared component match: ' + bug.component)
        if trained_scores and profile.user_id in trained_scores:
            reasons.append('Learned assignment score using text, severity and duplicate status')
        results.append({'user_id': profile.user_id, 'name': db.get(User, profile.user_id).name,
                        'score': round(score, 4), 'reasons': reasons, 'limited_history': history_count == 0,
                        'matching_new_developer': history_count == 0 and bool(skill_matches)})
    results.sort(key=lambda x: (-x['score'], x['user_id']))
    top = results[:3]
    newcomer = next((r for r in results if r['matching_new_developer']), None)
    if not state['cold_start'] and newcomer and newcomer not in top:
        top = top[:2] + [newcomer]
    mode = 'model-based' if trained_scores else 'rule-based' if top else 'manual'
    return {'mode': mode, 'model_state': state, 'recommendations': top,
            'message': 'Human assignment is required.' if not top else 'Suggestions only; the project manager makes the assignment.'}
