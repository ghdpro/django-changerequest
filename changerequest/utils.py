"""django-changerequest utilities"""

from urllib.request import parse_http_list


def get_ip_from_request(request):
    """Extracts IP address from a request object"""
    # Code inspired by Flask's werkzeug/wrappers/base_request.py
    if 'HTTP_X_FORWARDED_FOR' in request.META:
        addr = parse_http_list(request.META.get('HTTP_X_FORWARDED_FOR'))
        if len(addr) > 0:
            return addr[0]
    # else
    return request.META.get('REMOTE_ADDR')
