'use strict';
const config = window.TICKETS_CONFIG;
const el = id => document.getElementById(id);
let accessToken = null;
let expiresAt = 0;
let nextCursor = null;
let selected = null;
const transitions = { ABIERTO: 'EN_PROCESO', EN_PROCESO: 'CERRADO' };

function message(value) { el('message').textContent = value; }
function signedIn(value) {
  el('workspace').hidden = !value;
  el('login').hidden = value;
  el('logout').hidden = !value;
}
function base64url(bytes) {
  return btoa(String.fromCharCode.apply(null, bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
async function login() {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const state = base64url(crypto.getRandomValues(new Uint8Array(24)));
  sessionStorage.setItem('tickets-pkce', JSON.stringify({ verifier, state, created: Date.now() }));
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  const query = new URLSearchParams({
    response_type: 'code', client_id: config.clientId, redirect_uri: config.websiteUrl,
    scope: 'openid tickets-api/access', state,
    code_challenge_method: 'S256', code_challenge: base64url(new Uint8Array(digest))
  });
  location.assign(config.cognitoDomain + '/oauth2/authorize?' + query.toString());
}
async function finishLogin() {
  const query = new URLSearchParams(location.search);
  if (!query.has('code') && !query.has('error')) return false;
  const pending = sessionStorage.getItem('tickets-pkce');
  sessionStorage.removeItem('tickets-pkce');
  history.replaceState(null, '', '/');
  const saved = pending ? JSON.parse(pending) : null;
  if (!saved || saved.state !== query.get('state') || Date.now() - saved.created > 600000) {
    throw new Error('El intento de acceso expiró o el state no coincide. Inicie sesión de nuevo.');
  }
  if (query.has('error')) throw new Error('Cognito rechazó el inicio de sesión. Inténtelo de nuevo.');
  const response = await fetch(config.cognitoDomain + '/oauth2/token', {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'authorization_code', client_id: config.clientId,
      redirect_uri: config.websiteUrl, code: query.get('code'), code_verifier: saved.verifier })
  });
  const tokens = await response.json();
  if (!response.ok || !tokens.access_token) throw new Error('No se pudo completar el intercambio de código.');
  // Se descartan ID token y refresh token. El access token permanece solo en memoria.
  accessToken = tokens.access_token;
  expiresAt = Date.now() + tokens.expires_in * 1000;
  return true;
}
async function api(path, method, value) {
  if (!accessToken || Date.now() >= expiresAt) {
    accessToken = null;
    signedIn(false);
    throw new Error('La sesión local terminó. Inicie sesión de nuevo.');
  }
  const options = { method: method || 'GET', headers: { Authorization: 'Bearer ' + accessToken } };
  if (value !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(value);
  }
  const response = await fetch(config.apiUrl + path, options);
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) { accessToken = null; signedIn(false); }
    throw new Error(response.status + ': ' + (result.error || 'La API rechazó la solicitud'));
  }
  return result;
}
async function list(cursor) {
  let path = '/tickets?limit=20';
  if (cursor) path += '&cursor=' + encodeURIComponent(cursor);
  const result = await api(path);
  el('tickets').textContent = '';
  for (const item of result.items) {
    const li = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = item.titulo + ' · ' + item.estado;
    button.onclick = () => detail(item.id).catch(showError);
    li.appendChild(button);
    el('tickets').appendChild(li);
  }
  if (!result.items.length) {
    const li = document.createElement('li');
    li.textContent = 'No hay tickets en esta página.';
    el('tickets').appendChild(li);
  }
  nextCursor = result.cursor || null;
  el('next').hidden = !nextCursor;
}
async function detail(id) {
  selected = await api('/tickets/' + encodeURIComponent(id));
  el('fields').textContent = '';
  for (const field of ['id', 'titulo', 'descripcion', 'prioridad', 'estado', 'creadoEn', 'actualizadoEn']) {
    const dt = document.createElement('dt');
    dt.textContent = field;
    const dd = document.createElement('dd');
    dd.textContent = selected[field];
    el('fields').append(dt, dd);
  }
  const next = transitions[selected.estado];
  el('advance').hidden = !next;
  el('advance').textContent = next ? 'Cambiar a ' + next : '';
  el('detail').hidden = false;
}
function showError(error) { message(error.message || 'Ocurrió un error.'); }

el('login').onclick = () => login().catch(showError);
el('logout').onclick = () => {
  accessToken = null;
  expiresAt = 0;
  selected = null;
  sessionStorage.removeItem('tickets-pkce');
  signedIn(false);
  const query = new URLSearchParams({ client_id: config.clientId, logout_uri: config.websiteUrl });
  location.assign(config.cognitoDomain + '/logout?' + query.toString());
};
el('reload').onclick = () => list().catch(showError);
el('next').onclick = () => list(nextCursor).catch(showError);
el('create-form').onsubmit = async event => {
  event.preventDefault();
  el('create').disabled = true;
  try {
    const data = new FormData(event.target);
    const created = await api('/tickets', 'POST', {
      titulo: data.get('titulo'), descripcion: data.get('descripcion'), prioridad: data.get('prioridad')
    });
    event.target.reset();
    message('Ticket creado: ' + created.id);
    await list();
    await detail(created.id);
  } catch (error) { showError(error); }
  finally { el('create').disabled = false; }
};
el('advance').onclick = async () => {
  el('advance').disabled = true;
  try {
    const id = selected.id;
    await api('/tickets/' + encodeURIComponent(id), 'PATCH', { estado: transitions[selected.estado] });
    await detail(id);
    await list();
    message('Estado actualizado.');
  } catch (error) { showError(error); }
  finally { el('advance').disabled = false; }
};
(async () => {
  if (!config) throw new Error('Falta config.js. Ejecute scripts/configure_web.py y publique los archivos.');
  if (await finishLogin()) {
    signedIn(true);
    message('Sesión iniciada. Solo se muestran sus tickets.');
    await list();
  }
})().catch(showError);
