"""django-changerequest models"""

import logging
import threading

from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.hashable import make_hashable

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib import messages as msg
from django.contrib.postgres.fields import JSONField

from .utils import (format_object_str, model_to_dict, formset_data_revert, formset_data_changed,
                    changed_keys, filter_data, get_ip_from_request, objectdict)

logger = logging.getLogger(__name__)


class ChangeRequest(models.Model):
    thread = threading.local()  # Used to store request via middleware

    class Type(models.IntegerChoices):
        """Constants that define actions for which ChangeRequest records can be saved

        The first three are obvious; 'Related' is used for associated data that usually
        has a 1-N relation with the main model for which history is being saved.
        """
        ADD = 1
        MODIFY = 2
        DELETE = 3
        RELATED = 4

    class Status(models.IntegerChoices):
        """Constants that define the status of a ChangeRequest

        Pending    = ChangeRequest is awaiting moderation; data is not yet committed to the database
        Approved   = ChangeRequest has been (automatically) approved and data is committed to the database
        Denied     = A moderator has denied the ChangeRequest
        Withdrawn  = The user has withdrawn the ChangeRequest themselves
        Reverted   = A moderator has "undone" the approval of a ChangeRequest and reverted data to how it was before
        """
        PENDING = 1
        APPROVED = 2
        DENIED = 3
        WITHDRAWN = 4
        REVERTED = 5

    # ChangeRequest does not support non-integer primary keys
    object_type = models.ForeignKey(ContentType, related_name='%(class)s_object', on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object = GenericForeignKey('object_type', 'object_id')
    object_str = models.CharField(max_length=250, blank=True)
    related_type = models.ForeignKey(ContentType, null=True, blank=True, related_name='%(class)s_related',
                                     on_delete=models.PROTECT)
    request_type = models.PositiveSmallIntegerField(choices=Type.choices)
    status = models.PositiveSmallIntegerField(choices=Status.choices, default=Status.PENDING)
    data_revert = JSONField(encoder=DjangoJSONEncoder, null=True, blank=True)
    data_changed = JSONField(encoder=DjangoJSONEncoder, null=True, blank=True)
    comment = models.TextField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='%(class)s_user', on_delete=models.PROTECT)
    user_ip = models.GenericIPAddressField(unpack_ipv4=True)
    mod = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='%(class)s_mod', null=True, blank=True,
                            on_delete=models.PROTECT)
    mod_ip = models.GenericIPAddressField(unpack_ipv4=True, null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True, blank=True)
    date_modified = models.DateTimeField(auto_now=True, blank=True)

    def __str__(self):
        return format_object_str(self.get_object_type(), self.object_str, self.object_id)
    
    @classmethod
    def get_request(cls):
        return cls.thread.request

    @classmethod
    def create(cls, obj: 'HistoryModel', request_type: int = None) -> object:
        """Creates a ChangeRequest object"""
        cr = cls()
        cr.set_object(obj)
        cr.set_request_type(request_type)
        cr.status = ChangeRequest.Status.PENDING
        if cr.request_type != ChangeRequest.Type.RELATED:
            cr.data_revert = obj.data_revert()
            cr.data_changed = model_to_dict(obj)
            if cr.request_type == ChangeRequest.Type.MODIFY:
                fields = changed_keys(cr.data_revert, cr.data_changed)
                if len(fields) > 0:  # Only filter data_revert & data_changed if there were changes found
                    cr.data_revert = filter_data(cr.data_revert, fields)
                    cr.data_changed = filter_data(cr.data_changed, fields)
            elif cr.request_type == ChangeRequest.Type.DELETE:
                cr.data_changed = None
        cr.set_user(ChangeRequest.get_request())
        return cr

    def set_object(self, obj: models.Model):
        if obj.pk:
            # Existing object
            self.object = obj
        else:
            # New object
            self.object_type = ContentType.objects.get_for_model(obj)
            self.object_id = None
        self.object_str = str(obj)

    def cache_object_type(self, object_type_id=None, object_type=None):
        # cache.get_or_set() is not usable here because accessing self.object_type members trigger database queries
        obj_type_id = object_type_id if object_type_id is not None else self.object_type_id
        model = cache.get(f'object-type-{obj_type_id}')
        if model is None:
            model = object_type.model_class() if object_type is not None else self.object_type.model_class()
            cache.set(f'object-type-{obj_type_id}', model)
        return model

    def get_object_type(self) -> str:
        # Django 3.0 now adds app label to string representation of object_type, so get model name another way
        return self.cache_object_type()._meta.verbose_name

    def get_related_type(self) -> str:
        return self.cache_object_type(self.related_type_id, self.related_type)._meta.verbose_name

    def set_request_type(self, request_type: int = None):
        if request_type is not None:
            self.request_type = request_type
        elif self.related_type is not None:
            self.request_type = ChangeRequest.Type.RELATED
        elif self.object is not None:
            self.request_type = ChangeRequest.Type.MODIFY
        else:
            self.request_type = ChangeRequest.Type.ADD

    def set_user(self, request: object):
        self.user = request.user
        self.user_ip = get_ip_from_request(request)

    def set_mod(self, request: object):
        self.mod = request.user
        self.mod_ip = get_ip_from_request(request)

    def log(self, action: str = None, obj: str = None):
        action = self.get_request_type_display() if action is None else action
        obj = self if obj is None else obj
        logger.info(f'ChangeRequest: [{action}] [{self.get_status_display()}] {obj}'
                    f' user "{self.user.username}" ({self.user.pk})' +
                    (f' mod "{self.mod.username}" ({self.mod.pk})' if self.mod else ''))

    def save(self, *args, **kwargs):
        # 1) Save ChangeRequest if request type is something like ADD or DELETE
        # -OR-
        # 2) Prevent duplicates: when modifying existing entries, only save if data_revert does not equal data_changed
        if (self.request_type not in (self.Type.MODIFY, self.Type.RELATED)) or (self.data_revert != self.data_changed):
            super().save(*args, **kwargs)

    def fields_verbose(self):
        return {f.name: f.verbose_name
                for f in self.cache_object_type()._meta.get_fields() if hasattr(f, 'verbose_name')}

    def resolve_field(self, name, value):
        field = self.cache_object_type()._meta.get_field(name)
        # Field is Foreign Key
        if isinstance(field, models.ForeignKey):
            try:
                obj = field.related_model.objects.get(**{field.remote_field.field_name: value})
                return str(obj)
            except models.ObjectDoesNotExist:
                pass  # Reference no longer exists (deleted?)
        # Other fields (code copied straight from django/db/models/base.py :: _get_FIELD_display)
        choices_dict = dict(make_hashable(field.flatchoices))
        return force_str(choices_dict.get(make_hashable(value), value), strings_only=True)

    def order_fields(self, data, related=False) -> dict:
        # JSON dict order isn't guaranteed
        if related:
            model = self.cache_object_type(self.related_type_id, self.related_type)
        else:
            model = self.cache_object_type()
        return {f.name: data[f.name] for f in model._meta.get_fields() if f.name in data}

    def diff(self):
        # ADD
        if self.data_revert is None:
            return self.order_fields(self.data_changed)
        # DELETE
        if self.data_changed is None:
            return self.order_fields(self.data_revert)
        # MODIFY
        result = {k: v for k, v in self.data_changed.items() if k not in self.data_revert or self.data_revert[k] != v}
        return self.order_fields(result)
    
    def diff_related(self):
        result = {}
        # Primary Key Field Name
        result['pk'] = pk = self.cache_object_type(self.related_type_id, self.related_type)._meta.pk.name
        # Fields
        result['fields'] = [field for field in
                            self.cache_object_type(self.related_type_id, self.related_type)._meta.get_fields()
                            if isinstance(field, models.Field)]
        # Get list of primary key values from existing rows (data_revert) to be able to check for new data
        existing = [
            item[pk] for item in self.data_revert if pk in item and item[pk]
        ] if self.data_revert is not None else []
        # {action} values are for detail views; {action_str} values are for list views
        # Build list of added rows and changed rows from data_changed
        result['added'] = []
        result['added_str'] = []
        changed = {}
        if self.data_changed is not None:
            for item in self.data_changed:
                if pk in item and item[pk] and item[pk] in existing:
                    # Existing row
                    changed[item[pk]] = item
                else:
                    # New row
                    result['added'].append(self.order_fields(item, related=True))
                    result['added_str'].append(self.cache_object_type(self.related_type_id, self.related_type)
                                               .__str__(objectdict(item)))
        # Build list of existing, modified and deleted rows
        # `existing` contains original data and `modified` contains list of fields that may have changed
        # Combined they allow data to be displayed with changes highlighted
        result['existing'] = {}
        result['modified'] = {}
        result['modified_str'] = []
        result['deleted'] = []
        result['deleted_str'] = []
        if self.data_revert is not None:
            for item in self.data_revert:
                row = item
                if item[pk] in changed:
                    diff = changed_keys(item, changed[item[pk]])
                    if len(diff) > 0:
                        result['modified'][item[pk]] = diff
                        result['modified_str'].append(self.cache_object_type(self.related_type_id, self.related_type)
                                                      .__str__(objectdict(item)))
                        row = changed[item[pk]]
                else:
                    result['deleted'].append(item[pk])
                    result['deleted_str'].append(self.cache_object_type(self.related_type_id, self.related_type)
                                                 .__str__(objectdict(item)))
                result['existing'][item[pk]] = self.order_fields(row, related=True)
        return result

    def get_absolute_url(self, view='history:detail'):
        return reverse(view, args=[self.pk])

    class Meta:
        permissions = (
            ('self_approve', 'Can self-approve add, modify & related requests'),
            ('self_delete', 'Can self-approve delete requests'),
            ('throttle_min', 'Subject to more lenient throttling'),
            ('throttle_off', 'Not subject to any throttling'),
            ('mod_approve', 'Can moderate add, modify & related requests'),
            ('mod_delete', 'Can moderate delete requests'),
        )


class HistoryModel(models.Model):
    """Adds audit logging and staged editing support to models"""
    # Basic timestamp fields added to each model
    date_created = models.DateTimeField(auto_now_add=True, blank=True)
    date_modified = models.DateTimeField(auto_now=True, blank=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.comment = ''

    def data_revert(self):
        """Obtains unaltered data (before save) from database"""
        if self.pk:
            data = self.__class__.objects.get(pk=self.pk)
            return model_to_dict(data)
        return None  # else

    def save(self, *args, **kwargs):
        cr = ChangeRequest.create(self)
        cr.status = ChangeRequest.Status.APPROVED
        cr.comment = self.comment
        cr.save()
        if cr.pk:
            cr.log()
            if cr.status == ChangeRequest.Status.APPROVED:
                super().save(*args, **kwargs)
                # Now object is saved, get pk and save change request again
                cr.set_object(self)
                cr.save()
                # Only ADD/MODIFY as possible choices: DELETE and RELATED should be handled elsewhere
                verb = 'Added' if cr.request_type == ChangeRequest.Type.ADD else 'Updated'  # MODIFY
                msg.add_message(ChangeRequest.get_request(), msg.SUCCESS,
                                f'{verb} {cr.get_object_type()} "{cr.object_str}"')
            elif cr.status == ChangeRequest.Status.PENDING:
                msg.add_message(ChangeRequest.get_request(), msg.WARNING, f'Change request for '
                                f'{cr.get_object_type()} "{cr.object_str}" is pending moderator approval')

    def save_related(self, formset):
        cr = ChangeRequest.create(self, request_type=ChangeRequest.Type.RELATED)
        cr.related_type = ContentType.objects.get_for_model(formset.model)
        cr.status = ChangeRequest.Status.APPROVED
        cr.data_revert = formset_data_revert(formset)
        cr.data_changed = formset_data_changed(formset)
        cr.comment = self.comment
        cr.save()
        if cr.pk:
            cr.log()
            if cr.status == ChangeRequest.Status.APPROVED:
                formset.save()
                # Generate message(s)
                for obj in formset.new_objects:
                    msg.add_message(ChangeRequest.get_request(), msg.SUCCESS,
                                    f'Added {cr.get_related_type()} "{obj}"')
                    cr.log('Add', format_object_str(cr.get_related_type(), obj, obj.pk))
                for obj in formset.changed_objects:
                    msg.add_message(ChangeRequest.get_request(), msg.SUCCESS,
                                    f'Updated {cr.get_related_type()} "{obj}"')
                    cr.log('Modify', format_object_str(cr.get_related_type(), obj, obj.pk))
                for obj in formset.deleted_objects:
                    msg.add_message(ChangeRequest.get_request(), msg.SUCCESS,
                                    f'Deleted {cr.get_related_type()} "{obj}"')
                    cr.log('Delete', format_object_str(cr.get_related_type(), obj, obj.pk))
                # Refresh data_changed: any new instances should now have a pk set
                cr.data_changed = formset_data_revert(formset)
                cr.save()
            elif cr.status == ChangeRequest.Status.PENDING:
                msg.add_message(ChangeRequest.get_request(), msg.WARNING, f'Change request for '
                                f'{cr.get_related_type()} "{cr.object_str}" is pending moderator approval')

    def delete(self, *args, **kwargs):
        cr = ChangeRequest.create(self, request_type=ChangeRequest.Type.DELETE)
        cr.comment = self.comment
        cr.status = ChangeRequest.Status.APPROVED
        cr.save()
        super().delete(*args, **kwargs)
        msg.add_message(ChangeRequest.get_request(), msg.SUCCESS,
                        f'Deleted {cr.get_object_type()} "{cr.object_str}"')
        cr.log()

    class Meta:
        abstract = True
