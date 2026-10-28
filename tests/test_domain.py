"""Pruebas locales de reglas y aislamiento con dobles del SDK, sin llamadas AWS."""
import base64
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class FakeClientError(Exception):
    def __init__(self, code):
        self.response = {'Error': {'Code': code}}


class FakeKey:
    def __init__(self, name):
        self.name = name

    def eq(self, value):
        return (self.name, value)


class FakeTable:
    def __init__(self):
        self.rows = {}
        self.conflict = False

    def put_item(self, **args):
        item = args['Item']
        key = (item['PK'], item['SK'])
        if key in self.rows:
            raise FakeClientError('ConditionalCheckFailedException')
        self.rows[key] = deepcopy(item)

    def get_item(self, **args):
        key = args['Key']
        item = self.rows.get((key['PK'], key['SK']))
        return {'Item': deepcopy(item)} if item else {}

    def query(self, **args):
        pk = args['KeyConditionExpression'][1]
        rows = sorted((deepcopy(v) for (p, _), v in self.rows.items() if p == pk),
                      key=lambda item: item['SK'], reverse=True)
        if 'ExclusiveStartKey' in args:
            rows = [r for r in rows if r['SK'] < args['ExclusiveStartKey']['SK']]
        page = rows[:args['Limit']]
        result = {'Items': page}
        if len(rows) > len(page):
            result['LastEvaluatedKey'] = {k: page[-1][k] for k in ('PK', 'SK')}
        return result

    def update_item(self, **args):
        key = args['Key']
        row = self.rows.get((key['PK'], key['SK']))
        values = args['ExpressionAttributeValues']
        if self.conflict or not row or row['estado'] != values[':previous']:
            raise FakeClientError('ConditionalCheckFailedException')
        row['estado'], row['actualizadoEn'] = values[':next'], values[':date']
        return {'Attributes': deepcopy(row)}


def load_app():
    boto = types.ModuleType('boto3')
    boto.resource = lambda *a: types.SimpleNamespace(Table=lambda *a: FakeTable())
    condition = types.ModuleType('boto3.dynamodb.conditions')
    condition.Key = FakeKey
    exceptions = types.ModuleType('botocore.exceptions')
    exceptions.ClientError = FakeClientError
    modules = {'boto3': boto, 'boto3.dynamodb': types.ModuleType('boto3.dynamodb'),
               'boto3.dynamodb.conditions': condition, 'botocore': types.ModuleType('botocore'),
               'botocore.exceptions': exceptions}
    spec = importlib.util.spec_from_file_location('tickets_app', Path(__file__).resolve().parents[1] / 'backend/domain.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules), patch.dict(os.environ, {'TABLE_NAME': 'local'}):
        spec.loader.exec_module(module)
    return module


app = load_app()


class BackendTests(unittest.TestCase):
    def setUp(self):
        app.TABLE = FakeTable()

    def call(self, route, user='ana', value=None, ticket=None, params=None):
        event = {'routeKey': route, 'requestContext': {'requestId': 'test', 'authorizer': {'jwt': {'claims': {
            'sub': user, 'token_use': 'access', 'scope': 'openid tickets-api/access'}}}},
                 'queryStringParameters': params, 'pathParameters': {'id': ticket}}
        if value is not None:
            event['body'] = json.dumps(value)
        return app.handle_request(route, event['requestContext']['authorizer']['jwt']['claims'],
                                  event.get('body', ''), event['pathParameters'], params, 'test')

    def create(self, user='ana'):
        status, result = self.call('POST /tickets', user, {
            'titulo': 'Error en el aula', 'descripcion': 'No puedo abrir la página del aula.', 'prioridad': 'MEDIA'})
        self.assertEqual(status, 201)
        return result

    def test_create_and_detail(self):
        item = self.create()
        status, detail = self.call('GET /tickets/{id}', ticket=item['id'])
        self.assertEqual(status, 200)
        self.assertEqual(detail['estado'], 'ABIERTO')
        self.assertNotIn('PK', detail)

    def test_other_user_cannot_read_or_update(self):
        item = self.create()
        self.assertEqual(self.call('GET /tickets/{id}', 'bruno', ticket=item['id'])[0], 404)
        self.assertEqual(self.call('PATCH /tickets/{id}', 'bruno', {'estado': 'EN_PROCESO'}, item['id'])[0], 404)
        self.assertEqual(self.call('GET /tickets/{id}', ticket=item['id'])[1]['estado'], 'ABIERTO')

    def test_list_is_partitioned(self):
        ana = self.create()
        self.create('bruno')
        status, result = self.call('GET /tickets')
        self.assertEqual(status, 200)
        self.assertEqual([r['id'] for r in result['items']], [ana['id']])

    def test_owner_injection_rejected(self):
        status, _ = self.call('POST /tickets', value={'titulo': 'Error aula', 'descripcion': 'Descripción válida',
                                                     'prioridad': 'MEDIA', 'PK': 'USER#bruno'})
        self.assertEqual(status, 400)
        self.assertFalse(app.TABLE.rows)

    def test_empty_title_rejected(self):
        status, _ = self.call('POST /tickets', value={'titulo': '', 'descripcion': 'Descripción válida', 'prioridad': 'ALTA'})
        self.assertEqual(status, 400)

    def test_transitions_and_closed_ticket(self):
        item = self.create()
        for state in ('EN_PROCESO', 'CERRADO'):
            status, result = self.call('PATCH /tickets/{id}', value={'estado': state}, ticket=item['id'])
            self.assertEqual(status, 200)
            self.assertEqual(result['estado'], state)
        self.assertEqual(self.call('PATCH /tickets/{id}', value={'estado': 'ABIERTO'}, ticket=item['id'])[0], 409)

    def test_skip_state_rejected(self):
        item = self.create()
        self.assertEqual(self.call('PATCH /tickets/{id}', value={'estado': 'CERRADO'}, ticket=item['id'])[0], 409)

    def test_conditional_write_conflict(self):
        item = self.create()
        app.TABLE.conflict = True
        self.assertEqual(self.call('PATCH /tickets/{id}', value={'estado': 'EN_PROCESO'}, ticket=item['id'])[0], 409)

    def test_pagination_and_cross_user_cursor(self):
        for _ in range(3): self.create()
        status, first = self.call('GET /tickets', params={'limit': '2'})
        self.assertEqual(status, 200)
        self.assertEqual(len(first['items']), 2)
        status, second = self.call('GET /tickets', params={'limit': '2', 'cursor': first['cursor']})
        self.assertEqual(len(second['items']), 1)
        self.assertNotIn(second['items'][0]['id'], [r['id'] for r in first['items']])
        self.assertEqual(self.call('GET /tickets', user='bruno', params={'cursor': first['cursor']})[0], 400)

    def test_invalid_cursor_and_limit(self):
        for params in ({'limit': '21'}, {'limit': 'abc'}, {'cursor': '%%%'}):
            self.assertEqual(self.call('GET /tickets', params=params)[0], 400)

    def test_missing_identity_rejected(self):
        self.assertEqual(app.handle_request('GET /tickets', {})[0], 401)

    def test_id_token_and_missing_scope_rejected(self):
        for claims, expected in (({'sub': 'ana', 'token_use': 'id'}, 401),
                                 ({'sub': 'ana', 'token_use': 'access', 'scope': 'openid'}, 403)):
            event = {'routeKey': 'GET /tickets', 'requestContext': {'authorizer': {'jwt': {'claims': claims}}}}
            self.assertEqual(app.handle_request('GET /tickets', claims)[0], expected)

    def test_invalid_json(self):
        self.assertEqual(app.body('{"estado":"CERRADO"}')['estado'], 'CERRADO')
        with self.assertRaises(app.ApiError): app.body('[]')
        with self.assertRaises(app.ApiError): app.body('{')


if __name__ == '__main__':
    unittest.main()
