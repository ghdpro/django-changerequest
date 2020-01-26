"""django-changerequest forms"""

from django import forms


class HistoryCommentOptionalMixin(forms.Form):
    comment = forms.CharField(label='Comment / Source', required=False)


class HistoryCommentMandatoryMixin(forms.Form):
    comment = forms.CharField(label='Comment / Source', required=True)
