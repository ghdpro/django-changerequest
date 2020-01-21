"""django-changerequest middleware"""

from .models import ChangeRequest


class ChangeRequestMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # To be able to log user activities, we need access to the request object
        ChangeRequest.thread.request = request
        response = self.get_response(request)
        del ChangeRequest.thread.request
        return response
