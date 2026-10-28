"""Configura el frontend y empaqueta el código para EC2. No crea recursos AWS."""
import json
from pathlib import Path
import shlex
import zipfile

root = Path(__file__).resolve().parents[1]
raw = json.loads((root / 'stack-outputs.json').read_text())
values = {v['OutputKey']: v['OutputValue'] for v in raw['Stacks'][0]['Outputs']}
config = {'websiteUrl': values['WebsiteUrl'], 'apiUrl': values['ApiUrl'],
          'clientId': values['ClientId'], 'cognitoDomain': values['CognitoDomain']}
(root / 'web/config.js').write_text('window.TICKETS_CONFIG = ' + json.dumps(config, indent=2) + ';\n')
env = {'AWS_DEFAULT_REGION': raw['Stacks'][0]['StackId'].split(':')[3],
       'TABLE_NAME': values['TableName'], 'COGNITO_ISSUER': values['Issuer'],
       'COGNITO_CLIENT_ID': values['ClientId']}
(root / 'deploy/service.env').write_text(''.join(f'{k}={v}\n' for k, v in env.items()))
with zipfile.ZipFile(root / 'application.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for folder in ('backend', 'web', 'deploy'):
        for source in sorted((root / folder).rglob('*')):
            if source.is_file() and '__pycache__' not in source.parts:
                archive.write(source, source.relative_to(root))
bucket = shlex.quote(values['BucketName'])
region = shlex.quote(env['AWS_DEFAULT_REGION'])
commands = [
    'set -eu',
    'cloud-init status --wait',
    'command -v aws >/dev/null || dnf install -y awscli2',
    'dnf install -y unzip',
    'stage=$(mktemp -d /var/tmp/tickets-release.XXXXXX)',
    f'aws s3 cp s3://{bucket}/application.zip "$stage/application.zip" --region {region} --only-show-errors',
    'unzip -q "$stage/application.zip" -d "$stage/app"',
    'bash "$stage/app/deploy/install.sh"',
    'rm -rf "$stage"'
]
(root / 'ssm-command.json').write_text(json.dumps({'commands': commands, 'executionTimeout': ['3600']}, indent=2))
print('Generados: web/config.js, deploy/service.env, application.zip y ssm-command.json')
for key in ('WebsiteUrl', 'BucketName', 'InstanceId', 'UserPoolId', 'PublicIp'):
    print(f'{key}: {values[key]}')
