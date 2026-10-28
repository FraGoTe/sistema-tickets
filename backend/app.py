"""Aplicación WSGI ejecutada por Gunicorn en EC2."""
import json
import os
import time
from uuid import uuid4

from flask import Flask, request, jsonify, g
from auth import Verifier, AccessDenied
import domain

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10000
verifier = Verifier(os.environ['COGNITO_ISSUER'], os.environ['COGNITO_CLIENT_ID'])


@app.before_request
def authenticate():
    g.request_id = str(uuid4())
    g.started = time.monotonic()
    if request.path == '/healthz':
        return None
    try:
        g.claims = verifier.verify(request.headers.get('Authorization', ''))
    except AccessDenied as exc:
        return jsonify(error=exc.message), exc.status


@app.after_request
def record(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Request-Id'] = g.get('request_id', '')
    print(json.dumps({'requestId': g.get('request_id'), 'method': request.method,
                      'status': response.status_code,
                      'durationMs': round((time.monotonic() - g.get('started', time.monotonic())) * 1000)}), flush=True)
    return response


@app.get('/healthz')
def health():
    return jsonify(status='ok')


@app.route('/tickets', methods=['GET', 'POST'])
@app.route('/tickets/<ticket_id>', methods=['GET', 'PATCH'])
def tickets(ticket_id=None):
    route = request.method + (' /tickets/{id}' if ticket_id else ' /tickets')
    status, value = domain.handle_request(route=route, claims=g.claims,
        raw_body=request.get_data(as_text=True), path_params={'id': ticket_id},
        query=request.args.to_dict(), request_id=g.request_id)
    return jsonify(value), status


@app.errorhandler(413)
def too_large(_):
    return jsonify(error='Cuerpo demasiado grande'), 413


@app.errorhandler(500)
def internal(_):
    return jsonify(error='Error interno'), 500
