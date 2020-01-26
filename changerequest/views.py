"""django-changerequest views"""

from django.db import transaction

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib import messages


class PermissionMessageMixin(PermissionRequiredMixin):
    """"
    PermissionRequiredMixin modified to show error message to user.

    By default the PermissionRequiredMixin does not generate an error message, it just redirects to the login page.
    As that can be confusing, this simple mixin makes sure the "permission_denied_message" string is returned to the
    user via the messages framework and also sets a reasonable default value for it.
    """
    permission_denied_message = 'You do not have sufficient permissions to access this page'

    def handle_no_permission(self):
        messages.error(self.request, self.permission_denied_message)
        return super().handle_no_permission()


class HistoryFormViewMixin:

    @transaction.atomic
    def form_valid(self, form):
        form.instance.comment = form.cleaned_data['comment']
        response = super().form_valid(form)
        return response
