"""django-changerequest models"""

import logging
import threading

from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.urls import reverse

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib import messages as msg
from django.contrib.postgres.fields import JSONField

from .utils import format_object_str, model_to_dict, changed_keys, filter_data, get_ip_from_request

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

    def cache_object_type(self):
        # cache.get_or_set() is not usable here because accessing self.object_type members trigger database queries
        model = cache.get(f'object-type-{self.object_type_id}')
        if model is None:
            model = self.object_type.model_class()
            cache.set(f'object-type-{self.object_type_id}', model)
        return model

    def get_object_type(self) -> str:
        # Django 3.0 now adds app label to string representation of object_type, so get model name another way
        return self.cache_object_type()._meta.verbose_name

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

    def diff(self):
        model = self.cache_object_type()

        def order_fields(data) -> dict:
            # JSON dict order isn't guaranteed. Also replaces field name with verbose name.
            return {f.verbose_name: data[f.name] for f in model._meta.get_fields() if f.name in data}

        # ADD
        if self.data_revert is None:
            return order_fields(self.data_changed)
        # DELETE
        if self.data_changed is None:
            return order_fields(self.data_revert)
        # MODIFY
        result = {k: v for k, v in self.data_changed.items() if k not in self.data_revert or self.data_revert[k] != v}
        return order_fields(result)

    def get_absolute_url(self, view='history:detail'):
        return reverse(view, args=[self.pk])


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

    class Meta:
        abstract = True
