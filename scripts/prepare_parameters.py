"""Genera parámetros privados antes de crear el stack. No imprime el secreto."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets

parser = argparse.ArgumentParser()
parser.add_argument('--prefix-list-id', required=True)
args = parser.parse_args()
if not re.fullmatch(r'pl-[a-z0-9]+', args.prefix_list_id):
    parser.error('Identificador de prefix list inválido')
root = Path(__file__).resolve().parents[1]
target = root / 'parameters.json'
if target.exists():
    raise SystemExit('parameters.json ya existe. Consérvalo para mantener el secreto del origen.')
data = [{'ParameterKey': 'CloudFrontPrefixListId', 'ParameterValue': args.prefix_list_id},
        {'ParameterKey': 'OriginSecret', 'ParameterValue': secrets.token_urlsafe(40)}]
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    json.dump(data, stream, indent=2)
print('parameters.json generado con permisos 600. No lo compartas.')
