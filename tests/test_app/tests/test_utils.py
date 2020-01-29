from django.test import TestCase

from changerequest import utils


class ChangeRequestUtilsTest(TestCase):

    def test_format_str(self):
        s = utils.format_object_str('test', None, None)
        self.assertEqual(s, 'test')
        s = utils.format_object_str('test', 'test', None)
        self.assertEqual(s, 'test "test"')
        s = utils.format_object_str('test', 'test', 'test')
        self.assertEqual(s, 'test "test" (test)')
