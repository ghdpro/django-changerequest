"""django-changerequest views"""

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.http import urlencode
from django.views.generic import DetailView, ListView

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib import messages

from .forms import HistoryCommentOptionalForm
from .models import ChangeRequest


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
        return super().form_valid(form)


class HistoryFormsetViewMixin:
    formset_class = None

    def get_comment_form(self):
        if self.request.method in ('POST', 'PUT'):
            return HistoryCommentOptionalForm(prefix=self.get_prefix(), data=self.request.POST, files=self.request.FILES)
        else:
            return HistoryCommentOptionalForm(prefix=self.get_prefix())

    def get_context_data(self, **kwargs):
        if 'comment_form' not in kwargs:
            kwargs['comment_form'] = self.get_comment_form()
        return super().get_context_data(**kwargs)

    def get_form(self, form_class=None):
        if self.formset_class is None:
            raise ImproperlyConfigured('HistoryFormsetViewMixin requires formset class to be specified')
        return self.formset_class(**self.get_form_kwargs())

    def form_valid(self, form):
        # We don't call super() here because the original form_valid() from ModelFormMixin overwrites
        # self.object with output of form.save(), which is bad because form is a formset here
        comment_form = self.get_comment_form()
        if comment_form.is_valid():
            self.object.comment = comment_form.cleaned_data['comment']
        with transaction.atomic():
            self.object.save_related(form)
        return HttpResponseRedirect(self.get_success_url())


class HistoryDetailView(PermissionMessageMixin, DetailView):
    permission_required = 'changerequest.view_changerequest'
    template_name = 'history/detail.html'
    model = ChangeRequest


class HistoryListView(PermissionMessageMixin, ListView):
    permission_required = 'changerequest.view_changerequest'
    template_name = 'history/list.html'
    model = ChangeRequest
    paginate_by = 25

    def get_ordering(self):
        order = self.request.GET.get('order', '').strip().lower()
        if order == 'date':
            return 'date_modified', 'date_created'
        else:
            return '-date_modified', '-date_created'

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related('object_type', 'related_type', 'user')
        # Status
        status_lookup = {v.lower(): k for k, v in ChangeRequest.Status.choices}
        status = status_lookup.get(self.request.GET.get('status'), None)
        if status is not None:
            qs = qs.filter(status=status)
        # User
        user = self.request.GET.get('user', '').strip()
        if user:
            qs = qs.filter(user__username__icontains=user)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Status
        status = self.request.GET.get('status', '').lower().strip()
        if status.title() in ChangeRequest.Status.labels:
            context['status'] = status
        else:
            context['status'] = 'all'
        return context

    def get_url(self):
        return reverse('history:browse')

    def build_querystring(self, page=None, order=None, status=None):
        q = {}
        # Page
        if page is not None:
            q['page'] = page
        else:
            try:
                p = int(self.request.GET.get('page', 0))
                if p > 0:
                    q['page'] = p
            except ValueError:
                pass
        # Order
        o = self.request.GET.get('order', '').lower().strip()
        if order is not None:
            if o == order:
                q['order'] = order[1:] if order[0] == '-' else '-' + order
            else:  # Also inverse of '-order'
                q['order'] = order
            # New sort order should reset page
            if q.get('page', None) is not None:
                del q['page']
        elif o in ['date', '-date']:
            q['order'] = o
        # Status
        if status is not None:
            # Status can be 'all' (or other non-valid value) to remove it from query string
            if status.title() in ChangeRequest.Status.labels:
                q['status'] = status
                # New status filter should reset page
                if q.get('page', None) is not None:
                    del q['page']
        else:
            s = self.request.GET.get('status', '').lower().strip()
            if s.title() in ChangeRequest.Status.labels:
                q['status'] = s
        # User
        user = self.request.GET.get('user', '').strip()
        if user:
            q['user'] = user
        return q

    def get_querystring(self, *args, **kwargs):
        q = self.build_querystring(*args, **kwargs)
        if len(q) > 0:
            return '?' + urlencode(q)
        return ''
