"""django-changerequest template tags"""

from django import template
from django.contrib.contenttypes.models import ContentType

from ..models import ChangeRequest

register = template.Library()


@register.simple_tag
def _history_view_method(obj, func, *args, **kwargs):
    # 'Private' template tag used in History views
    return getattr(obj, func)(*args, **kwargs)


@register.filter
def _history_get(dictionary, index):
    # 'Private' template tag used in History views
    return dictionary.get(index)


@register.inclusion_tag('history/object.html', takes_context=True)
def history_object(context, obj):
    history = ChangeRequest.objects.filter(object_id=obj.pk, object_type=ContentType.objects.get_for_model(obj),
                                           related_type=None)\
        .select_related('user').order_by('-date_modified', '-date_created')
    return {'history': history, 'perms': context['perms']}
