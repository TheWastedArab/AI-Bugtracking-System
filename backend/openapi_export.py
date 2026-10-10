"""Convert the emitted schema to OpenAPI 3.0.3 for the report's API contract."""
import copy
import json
from pathlib import Path


def to_openapi30(schema):
    schema = copy.deepcopy(schema)
    schema['openapi'] = '3.0.3'
    def convert(node):
        if isinstance(node, dict):
            if node.pop('contentMediaType', None) == 'application/octet-stream':
                node['format'] = 'binary'
            node.pop('contentEncoding', None)
            if 'const' in node:
                node['enum'] = [node.pop('const')]
            if 'anyOf' in node and any(x == {'type': 'null'} for x in node['anyOf']):
                choices = [x for x in node.pop('anyOf') if x != {'type': 'null'}]
                node['nullable'] = True
                if len(choices) == 1:
                    choice = choices[0]
                    if '$ref' in choice:
                        node['allOf'] = [choice]
                    else:
                        node.update(choice)
                else:
                    node['anyOf'] = choices
            for value in node.values():
                convert(value)
        elif isinstance(node, list):
            for value in node:
                convert(value)
    convert(schema)
    return schema


if __name__ == '__main__':
    from .main import app
    target = Path('docs/openapi.json')
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(to_openapi30(app.openapi()), indent=2), encoding='utf-8')
    print(target)
