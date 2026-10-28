"""Pruebas HTTP Flask y validación criptográfica, sin conexión con AWS."""
import importlib
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from test_domain import FakeTable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
with patch.dict(os.environ, {'TABLE_NAME': 'local', 'COGNITO_ISSUER': 'https://example.invalid/pool',
                            'COGNITO_CLIENT_ID': 'test-client', 'AWS_DEFAULT_REGION': 'us-east-1',
                            'AWS_ACCESS_KEY_ID': 'local-test', 'AWS_SECRET_ACCESS_KEY': 'local-test',
                            'AWS_EC2_METADATA_DISABLED': 'true'}):
    server = importlib.import_module('app')


class HttpAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        server.domain.TABLE = FakeTable()
        self.client = server.app.test_client()
        self.key_patch = patch.object(server.verifier.keys, 'get_signing_key_from_jwt',
                                      return_value=SimpleNamespace(key=self.private.public_key()))
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)

    def headers(self, changes=None, other_key=False):
        claims = {'sub': 'ana', 'iss': 'https://example.invalid/pool', 'client_id': 'test-client',
                  'token_use': 'access', 'scope': 'openid tickets-api/access',
                  'iat': int(time.time()), 'exp': int(time.time()) + 300}
        claims.update(changes or {})
        token = jwt.encode(claims, self.other if other_key else self.private, algorithm='RS256')
        return {'Authorization': 'Bearer ' + token}

    def test_health_and_unauthenticated_api(self):
        self.assertEqual(self.client.get('/healthz').status_code, 200)
        result = self.client.get('/tickets')
        self.assertEqual(result.status_code, 401)
        self.assertEqual(result.headers['Cache-Control'], 'no-store')

    def test_signature_issuer_client_type_and_expiry(self):
        for changes in ({'iss': 'https://attacker.invalid'}, {'client_id': 'other'},
                        {'token_use': 'id'}, {'exp': int(time.time()) - 60}):
            self.assertEqual(self.client.get('/tickets', headers=self.headers(changes)).status_code, 401)
        self.assertEqual(self.client.get('/tickets', headers=self.headers(other_key=True)).status_code, 401)
        self.assertEqual(self.client.get('/tickets', headers={'Authorization': 'Bearer bad'}).status_code, 401)

    def test_missing_scope_is_forbidden(self):
        self.assertEqual(self.client.get('/tickets', headers=self.headers({'scope': 'openid'})).status_code, 403)

    def test_create_update_and_cross_user_isolation(self):
        from urllib.parse import quote
        payload = {'titulo': 'No abre el aula', 'descripcion': 'La pantalla muestra un error de acceso.', 'prioridad': 'MEDIA'}
        created = self.client.post('/tickets', headers=self.headers(), json=payload)
        self.assertEqual(created.status_code, 201)
        path = '/tickets/' + quote(created.json['id'], safe='')
        self.assertEqual(self.client.get(path, headers=self.headers()).status_code, 200)
        self.assertEqual(self.client.get(path, headers=self.headers({'sub': 'bruno'})).status_code, 404)
        changed = self.client.patch(path, headers=self.headers(), json={'estado': 'EN_PROCESO'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json['estado'], 'EN_PROCESO')

    def test_bad_json_and_oversized_body(self):
        bad = self.client.post('/tickets', headers=self.headers(), data='{', content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        large = self.client.post('/tickets', headers=self.headers(), data='x' * 11000)
        self.assertEqual(large.status_code, 413)


if __name__ == '__main__':
    unittest.main()
