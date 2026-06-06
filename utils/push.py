import os
import requests

FCM_SERVER_KEY = os.environ.get('FCM_SERVER_KEY', '')


def send_push(fcm_token: str, title: str, body: str, data: dict = None):
    if not FCM_SERVER_KEY or not fcm_token:
        return
    payload = {
        'to': fcm_token,
        'notification': {'title': title, 'body': body, 'sound': 'default'},
        'data': data or {},
    }
    try:
        requests.post(
            'https://fcm.googleapis.com/fcm/send',
            json=payload,
            headers={
                'Authorization': f'key={FCM_SERVER_KEY}',
                'Content-Type': 'application/json',
            },
            timeout=5,
        )
    except Exception:
        pass
