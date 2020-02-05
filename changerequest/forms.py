"""django-changerequest forms"""

from django import forms


class HistoryCommentOptionalForm(forms.Form):
    comment = forms.CharField(label='Comment / Source', required=False)


class HistoryCommentMandatoryForm(forms.Form):
    comment = forms.CharField(label='Comment / Source', required=True)
