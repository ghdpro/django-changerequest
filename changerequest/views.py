"""django-changerequest views"""

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import HttpResponseRedirect, QueryDict
from django.urls import reverse
from django.views.generic import DetailView, ListView

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib import messages as msg

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
        msg.add_message(self.request, msg.ERROR, self.permission_denied_message)
        return super().handle_no_permission()


class HistoryFormViewMixin:

    @transaction.atomic
    def form_valid(self, form):
        # We don't call super() here because the original form_valid() calls form.save() without commit=False
        # If commit=True, then form.save() will *always* save ManyToMany fields, which is bad
        form.instance.comment = form.cleaned_data['comment']
        self.object = form.save(commit=False)
        # By using commit=False, the form gains a "save_m2m()" function, but doesn't actually save the instance
        # which is bad because django-changerequest functionilty is triggered there. So let's do it manually:
        form.instance.save(form=form)
        return HttpResponseRedirect(self.get_success_url())


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
    
    
class ListQueryStringMixin:
    """QueryString related functionality for ListViews

    ALLOWED_ORDER should be a dictionary where the keys are allowed values for
    the 'order' value in the query string and the values are what actual ORM ordering
    they should be translated to. It can have a 'DEFAULT' key for the default ordering,
    which shouldn't be duplicated as valid value (which means this 'order' value will
    not be included in a query string, but that's fine because it is the default anyway!)
    """
    ALLOWED_ORDER = {}

    def get_ordering(self):
        order = self.request.GET.get('order', '').strip().lower()
        if order in self.ALLOWED_ORDER:
            return self.ALLOWED_ORDER[order]
        # else: return default (if set)
        if 'DEFAULT' in self.ALLOWED_ORDER:
            return self.ALLOWED_ORDER['DEFAULT']

    def build_querystring(self, page: int = None, order: str = None) -> QueryDict:
        q = QueryDict(mutable=True)
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
            if 'page' in q:
                del q['page']
        elif o in self.ALLOWED_ORDER.keys():
            q['order'] = o
        return q

    def get_querystring(self, *args, **kwargs) -> str:
        q = self.build_querystring(*args, **kwargs)
        if len(q) > 0:
            return '?' + q.urlencode()
        return ''

    def get_order_direction(self, order: str) -> str:
        # Determines current order direction (up or down) based on what -new- value of "order" will be (=opposite)
        q = self.build_querystring(order=order)
        if q['order'][0] == '-':
            return 'up'
        return 'down'


class HistoryListView(PermissionMessageMixin, ListQueryStringMixin, ListView):
    permission_required = 'history.view_changerequest'
    template_name = 'history/list.html'
    model = ChangeRequest
    paginate_by = 25
    ALLOWED_ORDER = {
        'DEFAULT': ['-date_modified', '-date_created'],  # Also equivalent to '-date'
        'date': ['date_modified', 'date_created']
    }

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
        context['status'] = 'all'  # Default value
        status = self.request.GET.get('status', '').lower().strip()
        if status.title() in ChangeRequest.Status.labels:
            context['status'] = status
        return context

    def get_absolute_url(self):
        return reverse('history:browse')

    def build_querystring(self, page: int = None, order: str = None, status: str = None) -> QueryDict:
        q = super().build_querystring(page=page, order=order)
        # Status
        if status is not None:
            # Status can be 'all' (or other non-valid value) to remove it from query string
            if status.title() in ChangeRequest.Status.labels:
                q['status'] = status
                # New status filter should reset page
                if 'page' in q:
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
