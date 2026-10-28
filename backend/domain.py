"""Reglas de tickets compartidas por las rutas Flask del servidor EC2."""
import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

TABLE = boto3.resource('dynamodb').Table(os.environ['TABLE_NAME'])
ID_PATTERN = re.compile(r'^TICKET#\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z#[0-9a-f-]{36}$')
NEXT = {'ABIERTO': 'EN_PROCESO', 'EN_PROCESO': 'CERRADO'}


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def response(status, value):
    return {'statusCode': status,
            'headers': {'Content-Type': 'application/json', 'Cache-Control': 'no-store'},
            'body': json.dumps(value, ensure_ascii=False)}


def public(item):
    return dict(id=item['SK'], **{k: v for k, v in item.items() if k not in ('PK', 'SK')})


def body(raw):
    try:
        raw = raw or '{}'
        if len(raw.encode('utf-8')) > 10000:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeError):
        raise ApiError(400, 'JSON inválido o cuerpo demasiado grande') from None


def text(value, low, high, field):
    if not isinstance(value, str) or not low <= len(value.strip()) <= high:
        raise ApiError(400, f'{field}: se requieren entre {low} y {high} caracteres')
    return value.strip()


def ticket_key(pk, path_params):
    # Flask entrega el identificador decodificado. No decodificar otra vez.
    ticket_id = (path_params or {}).get('id', '')
    if not ID_PATTERN.fullmatch(ticket_id):
        raise ApiError(400, 'Identificador inválido')
    return {'PK': pk, 'SK': ticket_id}


def cursor_decode(token, pk):
    try:
        if len(token) > 1000:
            raise ValueError()
        value = json.loads(base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True))
        if not isinstance(value, dict) or set(value) != {'PK', 'SK'}:
            raise ValueError()
        if value['PK'] != pk or not isinstance(value['SK'], str) or not ID_PATTERN.fullmatch(value['SK']):
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeError):
        raise ApiError(400, 'Cursor inválido para este usuario') from None


def dispatch(route, claims, raw_body, path_params, query):
    if not claims.get('sub') or claims.get('token_use') != 'access':
        raise ApiError(401, 'Se requiere un access token válido')
    if 'tickets-api/access' not in claims.get('scope', '').split():
        raise ApiError(403, 'Scope insuficiente')
    pk = 'USER#' + claims['sub']

    if route == 'POST /tickets':
        data = body(raw_body)
        if set(data) != {'titulo', 'descripcion', 'prioridad'}:
            raise ApiError(400, 'Campos esperados: titulo, descripcion y prioridad')
        title = text(data['titulo'], 5, 100, 'Título')
        description = text(data['descripcion'], 10, 1000, 'Descripción')
        if data['prioridad'] not in ('BAJA', 'MEDIA', 'ALTA'):
            raise ApiError(400, 'Prioridad inválida')
        date = now()
        item = {'PK': pk, 'SK': f'TICKET#{date}#{uuid4()}', 'titulo': title,
                'descripcion': description, 'prioridad': data['prioridad'],
                'estado': 'ABIERTO', 'creadoEn': date, 'actualizadoEn': date}
        TABLE.put_item(Item=item, ConditionExpression='attribute_not_exists(PK)')
        return response(201, public(item))

    if route == 'GET /tickets':
        params = query or {}
        if set(params) - {'limit', 'cursor'}:
            raise ApiError(400, 'Parámetro de consulta desconocido')
        try:
            limit = int(params.get('limit', '20'))
            if not 1 <= limit <= 20:
                raise ValueError()
        except (ValueError, TypeError):
            raise ApiError(400, 'limit debe estar entre 1 y 20') from None
        args = {'KeyConditionExpression': Key('PK').eq(pk), 'Limit': limit,
                'ScanIndexForward': False, 'ConsistentRead': True}
        if params.get('cursor'):
            args['ExclusiveStartKey'] = cursor_decode(params['cursor'], pk)
        result = TABLE.query(**args)
        output = {'items': [public(item) for item in result.get('Items', [])]}
        if result.get('LastEvaluatedKey'):
            output['cursor'] = base64.urlsafe_b64encode(
                json.dumps(result['LastEvaluatedKey']).encode()).decode().rstrip('=')
        return response(200, output)

    if route in ('GET /tickets/{id}', 'PATCH /tickets/{id}'):
        key = ticket_key(pk, path_params)
        item = TABLE.get_item(Key=key, ConsistentRead=True).get('Item')
        if item is None:
            raise ApiError(404, 'Ticket no encontrado')
        if route.startswith('GET'):
            return response(200, public(item))
        data = body(raw_body)
        if set(data) != {'estado'}:
            raise ApiError(400, 'Solo se permite actualizar estado')
        previous = item['estado']
        target = NEXT.get(previous)
        if target is None or data['estado'] != target:
            raise ApiError(409, 'Transición de estado no permitida')
        try:
            result = TABLE.update_item(
                Key=key, UpdateExpression='SET #s = :next, actualizadoEn = :date',
                ConditionExpression='attribute_exists(PK) AND #s = :previous',
                ExpressionAttributeNames={'#s': 'estado'},
                ExpressionAttributeValues={':next': target, ':date': now(), ':previous': previous},
                ReturnValues='ALL_NEW')
        except ClientError as exc:
            if exc.response['Error']['Code'] == 'ConditionalCheckFailedException':
                raise ApiError(409, 'El ticket cambió. Actualice el detalle') from None
            raise
        return response(200, public(result['Attributes']))
    raise ApiError(404, 'Ruta no encontrada')


def handle_request(route, claims, raw_body='', path_params=None, query=None, request_id=None):
    started = time.monotonic()
    error_type = None
    try:
        result = dispatch(route, claims, raw_body, path_params, query)
    except ApiError as exc:
        result = response(exc.status, {'error': exc.message})
    except ClientError as exc:
        error_type = exc.response.get('Error', {}).get('Code', 'ClientError')
        if error_type in ('ProvisionedThroughputExceededException', 'ThrottlingException', 'RequestLimitExceeded'):
            result = response(429, {'error': 'Capacidad temporalmente agotada. Reintente después'})
        else:
            result = response(500, {'error': 'Error interno'})
    except Exception as exc:
        error_type = type(exc).__name__
        result = response(500, {'error': 'Error interno'})
    print(json.dumps({'requestId': request_id,
                      'route': route, 'status': result['statusCode'],
                      'durationMs': round((time.monotonic() - started) * 1000),
                      'errorType': error_type}))
    return result['statusCode'], json.loads(result['body'])
