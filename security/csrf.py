import secrets

from flask import abort, jsonify, request, session


def get_csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def protect_state_changing_request():
    if request.method in {'GET', 'HEAD', 'OPTIONS', 'TRACE'}:
        return None

    expected = session.get('_csrf_token')
    provided = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
    if expected and provided and secrets.compare_digest(expected, provided):
        return None

    if request.is_json:
        return jsonify({'success': False, 'message': 'The request could not be verified. Refresh and try again.'}), 400
    abort(400, description='The request could not be verified. Refresh the page and try again.')
