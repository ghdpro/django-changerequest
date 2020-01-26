"""django-changerequest models"""

import threading

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField

from .utils import format_object_str, model_to_dict, changed_keys, filter_data, get_ip_from_request


class ChangeRequest(models.Model):
    thread = threading.local()  # Used to store request via middleware

    class Type:
        """Constants that define actions for which ChangeRequest records can be saved

        The first three are obvious; 'Related' is used for associated data that usually
        has a 1-N relation with the main model for which history is being saved.
        """
        ADD = 1
        MODIFY = 2
        DELETE = 3
        RELATED = 4
        choices = (
            (ADD, 'Add'),
            (MODIFY, 'Modify'),
            (DELETE, 'Delete'),
            (RELATED, 'Related')
        )

    class Status:
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
        choices = (
            (PENDING, 'Pending'),
            (APPROVED, 'Approved'),
            (DENIED, 'Denied'),
            (WITHDRAWN, 'Withdrawn'),
            (REVERTED, 'Reverted'),
        )
        lookup = dict((v[1].lower(), v[0]) for k, v in enumerate(choices))

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
        return format_object_str(self.object_type, self.object_str, self.object_id)

    @classmethod
    def create(cls, obj: object, request_type: int = None) -> object:
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
        cr.set_user(ChangeRequest.thread.request)
        return cr

    def set_object(self, obj):
        if obj.pk:
            # Existing object
            self.object = obj
        else:
            # New object
            self.object_type = ContentType.objects.get_for_model(obj)
            self.object_id = None
        self.object_str = str(obj)

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

    def save(self, *args, **kwargs):
        # 1) Save ChangeRequest if request type is something like ADD or DELETE
        # -OR-
        # 2) Prevent duplicates: when modifying existing entries, only save if data_revert does not equal data_changed
        if (self.request_type not in (self.Type.MODIFY, self.Type.RELATED)) or (self.data_revert != self.data_changed):
            super().save(*args, **kwargs)


class HistoryModel(models.Model):
    """Adds audit logging and moderation features for for models with django-changerequest support"""
    # Basic timestamp fields added to each model
    date_created = models.DateTimeField(auto_now_add=True, blank=True)
    date_modified = models.DateTimeField(auto_now=True, blank=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._comment = ''

    @property
    def comment(self):
        return self._comment

    @comment.setter
    def comment(self, comment):
        self._comment = comment

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
            models.Model.save(self, *args, **kwargs)

    class Meta:
        abstract = True
