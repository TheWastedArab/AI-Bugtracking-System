"""Convert MSR 2013 v02 history JSON without exposing developer email addresses."""
import argparse
import hashlib
import json
from pathlib import Path

SEVERITIES = {'trivial': 'Low', 'minor': 'Low', 'normal': 'Medium', 'major': 'High', 'critical': 'Critical', 'blocker': 'Critical'}


def normalize(source, output):
    source, output = Path(source), Path(output)
    records = json.loads((source / 'reports.json').read_text(encoding='utf-8'))['reports']
    for field in ['short_desc', 'severity', 'component', 'assigned_to']:
        history = json.loads((source / f'{field}.json').read_text(encoding='utf-8'))[field]
        for bug_id, record in records.items():
            events = sorted(history.get(bug_id, []), key=lambda event: event['when'])
            # Features use the earliest observed title/component, labels use the final outcome.
            event = (events[0] if field in ('short_desc', 'component') else events[-1]) if events else {}
            value = str(event.get('what', ''))
            if field == 'assigned_to':
                value = hashlib.sha256(value.lower().encode()).hexdigest()[:20] if value else ''
            record[field] = value
            record[field + '_when'] = event.get('when', 0)
        del history
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open('w', encoding='utf-8') as target:
        for bug_id, row in sorted(records.items(), key=lambda item: item[1]['opening']):
            if not row['short_desc'].strip() or row['severity'] not in SEVERITIES:
                continue
            result = {'id': bug_id, 'created_at': row['opening'], 'title': row['short_desc'], 'description': '',
                      'severity': SEVERITIES[row['severity']], 'component': row['component'],
                      'assignee': row['assigned_to'], 'label_at': max(row['severity_when'], row['assigned_to_when']),
                      'fixed': row.get('current_resolution') == 'FIXED',
                      'duplicate': row.get('current_resolution') == 'DUPLICATE', 'duplicate_of': None}
            target.write(json.dumps(result, ensure_ascii=False) + '\n')
            count += 1
    summary = {'source': source.name, 'input_reports': len(records), 'normalized_reports': count,
               'text': 'earliest observed title only; descriptions absent',
               'duplicate_evaluation': 'unavailable: original bug IDs absent',
               'excluded': 'enhancements, missing severity or title', 'assignees': 'SHA-256 pseudonyms; raw emails excluded'}
    output.with_suffix('.metadata.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', help='data/v02/eclipse or data/v02/mozilla directory')
    parser.add_argument('output', help='Output JSONL path')
    args = parser.parse_args()
    print(json.dumps(normalize(args.source, args.output), indent=2))
