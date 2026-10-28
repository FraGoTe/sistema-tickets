"""Verificación de access tokens Cognito en EC2, con firma RS256 y JWKS."""
import jwt
from jwt import PyJWKClient


class AccessDenied(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Verifier:
    def __init__(self, issuer, client_id):
        self.issuer = issuer
        self.client_id = client_id
        self.keys = PyJWKClient(issuer + '/.well-known/jwks.json', cache_keys=True, lifespan=3600)

    def verify(self, authorization):
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            raise AccessDenied(401, 'Se requiere un access token')
        try:
            token = parts[1]
            key = self.keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=['RS256'], issuer=self.issuer,
                                options={'verify_aud': False, 'require': ['exp', 'iat', 'sub', 'iss', 'client_id', 'token_use']})
        except jwt.PyJWKClientConnectionError:
            raise AccessDenied(503, 'No se pudo consultar el servicio de identidad') from None
        except jwt.PyJWTError:
            raise AccessDenied(401, 'Token inválido o vencido') from None
        if claims['client_id'] != self.client_id or claims['token_use'] != 'access':
            raise AccessDenied(401, 'Token de cliente o tipo incorrecto')
        if not isinstance(claims['sub'], str) or not claims['sub']:
            raise AccessDenied(401, 'Identidad inválida')
        if not isinstance(claims.get('scope'), str) or 'tickets-api/access' not in claims['scope'].split():
            raise AccessDenied(403, 'Scope insuficiente')
        return claims
