"""django-changerequest utilities"""

from urllib.request import parse_http_list

from django.db.models.fields.related import ManyToManyField
from django.db.models import FileField
from django.forms.models import model_to_dict as _model_to_dict


def format_object_str(object_type: str, object_str, object_id) -> str:
    """Returns a string with object type and a string representation of the object and/or the primary key"""
    result = f'{object_type}'
    if object_str:
        result += f' "{object_str}"'
    if object_id:
        result += f' ({object_id})'
    return result


def model_to_dict(instance: object, exclude_pk: bool = True) -> dict:
    """Converts model instance into a dictionary"""
    raw = _model_to_dict(instance)
    data = {}
    for field in instance._meta.get_fields():
        if field.name in raw:
            if isinstance(field, ManyToManyField):
                data[field.name] = [obj.pk for obj in raw[field.name]]
            elif isinstance(field, FileField):
                data[field.name] = str(raw[field.name])
            elif not exclude_pk or field.name != instance._meta.pk.name:
                data[field.name] = raw[field.name]
    return data


def data_m2m(form: object, instance: object, data_changed: dict) -> dict:
    """Extracts M2M data from form"""
    for field in instance._meta.get_fields():
        if isinstance(field, ManyToManyField) and field.name in form.cleaned_data:
            data_changed[field.name] = [obj.pk for obj in form.cleaned_data[field.name]]
    return data_changed


def formset_data_revert(formset) -> list:
    """Obtains unaltered data for a formset from database"""
    return [model_to_dict(obj, exclude_pk=False) for obj in formset.get_queryset().all()]


def formset_data_changed(formset) -> list:
    """Builds a list of (potentially altered and/or new) object instances from the formset"""
    result = []
    # Include original data (initial forms) if not marked for deletion
    result += [model_to_dict(form.instance, exclude_pk=False) for form in formset.initial_forms
               if form.instance.pk and form not in formset.deleted_forms]
    # Include new data (extra forms) if data was entered (has changed) and not marked for immediate deletion (why?!?)
    result += [model_to_dict(form.instance, exclude_pk=False) for form in formset.extra_forms
               if form.has_changed() and not (formset.can_delete and formset._should_delete_form(form))]
    return result


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
            return addr[0].strip('"')
    # else
    return request.META.get('REMOTE_ADDR')


class objectdict(dict):
    """.member access to dictionary attributes"""

    def __getattr__(self, item):
        if item in self:
            return self[item]
        else:
            raise AttributeError(f"'dict' object has no attribute '{item}'")
