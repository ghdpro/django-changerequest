"""django-changerequest utilities"""

from urllib.request import parse_http_list

from django.db.models.fields.related import ManyToManyField
from django.db.models import FileField
from django.forms.models import model_to_dict as _model_to_dict


def format_object_str(object_type: str, object_str, object_id) -> str:
    """Returns a string with object type and a string representation of the object and/or the primary key"""
    result = '{}'.format(object_type)
    if object_str:
        result += ' "{}"'.format(object_str)
    if object_id:
        result += " ({})".format(object_id)
    return result


def model_to_dict(instance: object, exclude_pk: bool = True) -> dict:
    """Converts model instance into a dictionary"""
    raw = _model_to_dict(instance)
    data = {}
    for field in instance._meta.get_fields():
        if field.name in raw:
            if isinstance(field, ManyToManyField):
                continue  # TODO: implement M2M field support
            elif isinstance(field, FileField):
                data[field.name] = str(raw[field.name])
            elif not exclude_pk or field.name != instance._meta.pk.name:
                data[field.name] = raw[field.name]
    return data


def changed_keys(a: dict, b: dict) -> list:
    """Compares two dictionaries and returns list of keys where values are different"""
    # Note! This function disregards keys that don't appear in both dictionaries
    return [k for k in (a.keys() & b.keys()) if a[k] != b[k]]


def filter_data(data: dict, keys: list) -> dict:
    """Returns a dictionary with only key/value pairs where the key is in the keys list"""
    return {k: data[k] for k in keys if k in data}


def get_ip_from_request(request: object) -> str:
    """Extracts IP address from a request object"""
    # Code inspired by Flask's werkzeug/wrappers/base_request.py
    if 'HTTP_X_FORWARDED_FOR' in request.META:
        addr = parse_http_list(request.META.get('HTTP_X_FORWARDED_FOR'))
        if len(addr) > 0:
            return addr[0]
    # else
    return request.META.get('REMOTE_ADDR')
