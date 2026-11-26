"""Native-screen transport over the existing Streamlit component connection.

No listener, port, database credential, or additional hosting service is added.
The existing controller remains responsible for every authorization check.
"""
import uuid
import json
import hashlib
from controller import handle_event, ist, is_admin


def handle_native_request(db, envelope, session, config, load_photo, seed_photo):
    if not isinstance(envelope, dict) or envelope.get('action') == 'ack':
        return None, False
    delivery = envelope.get('id')
    if not isinstance(delivery, str) or not isinstance(envelope.get('request'), dict):
        return None, False
    try:
        uuid.UUID(delivery)
    except (ValueError, TypeError):
        return None, False
    if session.get('native_delivery') == delivery:
        return None, False
    session['native_delivery'] = delivery
    request = dict(envelope['request'])
    response = {'delivery': delivery, 'id': request.get('id'), 'action': request.get('action'), 'ok': False}
    try:
        uuid.UUID(request.get('id', ''))
        action = request.get('action')
        allowed = {'native_sync', 'login', 'logout', 'add_item', 'replace_photo', 'member', 'issue', 'return', 'photos'}
        if action not in allowed:
            raise ValueError('Unknown request.')
        if action == 'native_sync':
            page = request.get('page', 1)
            if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 100000:
                raise ValueError('Choose a valid history page.')
            request = dict(request, action='history', page=page)
        # A delivery is processed once. An explicit retry with a new delivery may
        # reuse a ledger UUID: the Store deduplicates it durably across restarts.
        results = session.setdefault('native_results', {})
        mutation = action in {'add_item', 'replace_photo', 'member', 'issue', 'return'}
        if mutation and not is_admin(session):
            raise ValueError('Please sign in as admin to change records.')
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        saved = results.get(request['id'])
        if saved is not None:
            if saved['fingerprint'] != fingerprint:
                raise ValueError('This request ID has already been used.')
            return dict(saved['response'], delivery=delivery), False
        if session.get('processed_event') == request['id']:
            session.pop('processed_event', None)
        result, changed = handle_event(db, request, session, config, load_photo, seed_photo)
        if result is None:
            raise ValueError('No response. Refresh and try again.')
        response.update(result, action=action)
        if action == 'native_sync' and result.get('ok'):
            changed = True  # Android refresh bypasses the 30-second metadata cache.
        if result.get('ok') and action in {'issue', 'return'} and session.get('receipt'):
            with db.connect() as connection:
                row = db.execute(connection, 'SELECT created_at FROM mandal_transactions WHERE id=?', (request['id'],)).fetchone()
            if row:
                session['receipt']['when'] = ist(row['created_at'])
        if result.get('ok') and action in {'login', 'add_item', 'replace_photo', 'member', 'issue', 'return'}:
            session['history_page'] = 1
            session['history_rows'] = db.history()
        # Never retain plaintext passwords or image payloads in this response cache.
        # Failed requests are deliberately not cached: authorization can change.
        if result.get('ok') and action in {'add_item', 'replace_photo', 'member', 'issue', 'return'}:
            results[request['id']] = {'fingerprint': fingerprint, 'response': dict(response)}
            while len(results) > 20:
                results.pop(next(iter(results)))
        if action == 'logout':
            results.clear()
        return response, changed
    except (ValueError, TypeError, AttributeError) as exc:
        response['error'] = str(exc) if isinstance(exc, ValueError) else 'Invalid request.'
    except Exception:
        response['error'] = 'Could not complete the request. Refresh and try again.'
    return response, False
