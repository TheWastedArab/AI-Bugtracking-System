"""Reproducible training/evaluation. Model files are trusted local operator artifacts."""
import argparse
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
import random
import time
import numpy as np
from .ai import tokens


def read_rows(path):
    with open(path, encoding='utf-8') as source:
        return [json.loads(line) for line in source if line.strip()]


def text(row, assignment=False):
    result = row['title'] + ' ' + row.get('description', '')
    if assignment:
        # Duplicate *outcome* from an offline dataset is not used: unavailable at report time.
        result += ' component_' + row.get('component', 'general')
        result += ' severity_' + row.get('predicted_severity', 'Unclassified')
        result += ' duplicate_' + str(bool(row.get('known_duplicate', False)))
    return result


def split_rows(rows):
    unique, seen = [], set()
    for row in sorted(rows, key=lambda r: r.get('created_at', 0)):
        key = ' '.join(tokens(text(row)))
        if key not in seen:
            unique.append(row)
            seen.add(key)
    split = int(len(unique) * .8)
    if split < 10 or len(unique) - split < 2:
        raise ValueError('At least 15 distinct labelled reports are required')
    cutoff = unique[split].get('created_at', 0)
    train = [r for r in unique[:split] if not cutoff or r.get('label_at', 0) <= cutoff]
    if len(train) < 10:
        raise ValueError('Not enough outcomes known before the held-out time boundary')
    return train, unique[split:]


def train_severity(rows, output, cv=0):
    import joblib
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.naive_bayes import MultinomialNB
    from sklearn.pipeline import Pipeline
    from sklearn.svm import LinearSVC
    rows = [r for r in rows if r.get('severity') in ('Low', 'Medium', 'High', 'Critical')]
    train, test = split_rows(rows)
    pipeline = Pipeline([('tfidf', TfidfVectorizer(max_features=30000, ngram_range=(1, 2), sublinear_tf=True)),
                         ('ensemble', VotingClassifier([('svm', LinearSVC(class_weight='balanced', random_state=42)),
                            ('forest', RandomForestClassifier(n_estimators=80, max_depth=32, class_weight='balanced_subsample', n_jobs=2, random_state=42)),
                            ('nb', MultinomialNB(alpha=.5))], voting='hard'))])
    x, y = [text(r) for r in train], [r['severity'] for r in train]
    folds = None
    if cv:
        if min(Counter(y).values()) < cv:
            raise ValueError('Too few training examples per class for the requested folds')
        folds = cross_val_score(pipeline, x, y, cv=StratifiedKFold(cv, shuffle=True, random_state=42), scoring='f1_macro', n_jobs=1).tolist()
    pipeline.fit(x, y)
    started = time.perf_counter()
    predicted = pipeline.predict([text(r) for r in test])
    labels = ['Low', 'Medium', 'High', 'Critical']
    metrics = {'model': 'TF-IDF + SVM/RandomForest/NaiveBayes majority vote', 'train_count': len(train), 'test_count': len(test),
               'split': 'chronological 80/20; exact-text duplicates removed; train outcomes known before cutoff',
               'accuracy': accuracy_score([r['severity'] for r in test], predicted),
               'classification_report': classification_report([r['severity'] for r in test], predicted, labels=labels, output_dict=True, zero_division=0),
               'confusion_matrix': confusion_matrix([r['severity'] for r in test], predicted, labels=labels).tolist(), 'labels': labels,
               'batch_seconds': time.perf_counter() - started, 'cv_macro_f1': folds,
               'target_accuracy': .85, 'title_only_dataset': all(not r.get('description') for r in rows)}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    joblib.dump(pipeline, temporary)
    temporary.replace(output)
    output.with_suffix('.metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    return metrics


def network(vocabulary_size, classes):
    import torch
    from torch import nn
    class CNNLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = nn.Embedding(vocabulary_size, 48, padding_idx=0)
            self.conv = nn.Conv1d(48, 64, 3, padding=1)
            self.lstm = nn.LSTM(64, 48, batch_first=True)
            self.output = nn.Linear(48, classes)

        def forward(self, values):
            length = values.ne(0).sum(1).clamp(min=1)
            embedded = self.embedding(values).transpose(1, 2)
            features = torch.relu(self.conv(embedded)).transpose(1, 2)
            hidden, _ = self.lstm(features)
            return self.output(hidden[torch.arange(values.shape[0], device=values.device), length - 1])
    return CNNLSTM()


def encode(texts, vocab):
    return [[vocab.get(t, 1) for t in tokens(t)[:80]] + [0] * (80 - min(80, len(tokens(t)))) for t in texts]


def train_assignment(rows, output, epochs=6):
    import torch
    from torch.utils.data import DataLoader, TensorDataset
    torch.manual_seed(42)
    torch.set_num_threads(2)
    random.seed(42)
    rows = [r for r in rows if r.get('assignee') is not None and r.get('fixed', True)]
    train, test = split_rows(rows)
    counts = Counter(str(r['assignee']) for r in train)
    classes = sorted(k for k, count in counts.items() if count >= 3)
    if len(classes) < 2:
        raise ValueError('Need at least two assignees with three training records each')
    train = [r for r in train if str(r['assignee']) in classes]
    words = Counter(t for r in train for t in tokens(text(r, True)))
    vocab = {word: n + 2 for n, (word, _) in enumerate(words.most_common(12000))}
    model = network(len(vocab) + 2, len(classes))
    x = torch.tensor(encode([text(r, True) for r in train], vocab), dtype=torch.long)
    y = torch.tensor([classes.index(str(r['assignee'])) for r in train], dtype=torch.long)
    loader = DataLoader(TensorDataset(x, y), batch_size=128, shuffle=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=.002)
    for epoch in range(epochs):
        model.train()
        total = 0.
        for batch, targets in loader:
            optimizer.zero_grad()
            loss = torch.nn.functional.cross_entropy(model(batch), targets)
            loss.backward()
            optimizer.step()
            total += float(loss.detach())
        print(f'Assignment epoch {epoch + 1}/{epochs}: loss={total / len(loader):.4f}', flush=True)
    model.eval()
    rankings = []
    with torch.no_grad():
        for start in range(0, len(test), 256):
            values = torch.tensor(encode([text(r, True) for r in test[start:start + 256]], vocab), dtype=torch.long)
            rankings.extend(model(values).argsort(dim=1, descending=True).tolist())
    ranks = [next((i + 1 for i, index in enumerate(order) if classes[index] == str(row['assignee'])), len(classes) + 1) for row, order in zip(test, rankings)]
    known = sum(str(r['assignee']) in classes for r in test)
    random_mnr = (known * (len(classes) - 1) / 2 + (len(test) - known) * len(classes)) / len(test)
    mnr = float(np.mean([r - 1 for r in ranks]))
    metrics = {'model': 'CNN-LSTM', 'train_count': len(train), 'test_count': len(test), 'developer_classes': len(classes),
               'top_k_accuracy': {str(k): sum(rank <= min(k, len(classes)) for rank in ranks) / len(ranks) for k in [1, 3, 5]},
               'unseen_assignee_test_count': len(test) - known, 'simulated_mnr': mnr, 'random_expected_mnr': random_mnr,
               'mnr_reduction': 1 - mnr / random_mnr if random_mnr else 0,
               'simulation': 'rank minus one; unseen assignees require exhausting the candidate list; not observed reassignments',
               'split': 'chronological with exact-text deduplication and outcome cutoff', 'epochs': epochs}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    torch.save({'state': model.state_dict(), 'vocab': vocab, 'classes': classes}, temporary)
    temporary.replace(output)
    output.with_suffix('.metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    return metrics


@lru_cache(maxsize=8)
def load_assignment(path, modified):
    import torch
    artifact = torch.load(path, map_location='cpu', weights_only=True)
    model = network(len(artifact['vocab']) + 2, len(artifact['classes']))
    model.load_state_dict(artifact['state'])
    model.eval()
    return artifact, model


def predict_assignment(path, bug):
    import torch
    artifact, model = load_assignment(path, Path(path).stat().st_mtime_ns)
    row = {'title': bug.title, 'description': bug.description, 'component': bug.component,
           'predicted_severity': bug.severity, 'known_duplicate': bool(bug.duplicate_of)}
    with torch.no_grad():
        scores = model(torch.tensor(encode([text(row, True)], artifact['vocab']), dtype=torch.long)).softmax(1)[0].tolist()
    return {int(label): score for label, score in zip(artifact['classes'], scores)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('task', choices=['severity', 'assignment'])
    parser.add_argument('dataset')
    parser.add_argument('--output', required=True)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--epochs', type=int, default=6)
    parser.add_argument('--cv', type=int, default=0)
    args = parser.parse_args()
    rows = read_rows(args.dataset)
    if args.limit:
        # Sample evenly over time; no random post-split leakage.
        rows = [rows[int(i)] for i in np.linspace(0, len(rows) - 1, min(args.limit, len(rows)))]
    metrics = train_severity(rows, args.output, args.cv) if args.task == 'severity' else train_assignment(rows, args.output, args.epochs)
    print(json.dumps(metrics, indent=2))
