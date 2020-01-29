from django.apps import apps
from django.test import TestCase

from changerequest.apps import ChangerequestConfig


class ChangeRequestOtherTest(TestCase):

    def test_apps(self):
        self.assertEqual(ChangerequestConfig.name, 'changerequest')
        self.assertEqual(apps.get_app_config('changerequest').name, 'changerequest')
