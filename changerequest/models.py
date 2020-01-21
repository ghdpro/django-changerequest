"""django-changerequest models"""

import threading

from django.db import models


class ChangeRequest(models.Model):
    thread = threading.local()


class BaseHistoryModel(models.Model):
    """Adds logging features for for models with django-changerequest support"""

    class Meta:
        abstract = True


class HistoryModel(BaseHistoryModel):
    """Adds moderation features for models with django-changerequest support"""

    class Meta:
        abstract = True
