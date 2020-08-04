from django.test import TestCase, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.storage.fallback import FallbackStorage

from changerequest import utils
from changerequest.models import ChangeRequest
from test_app import models


class ChangeRequestUtilsTest(TestCase):

    def setUp(self):
        # Set up / Fake middleware
        self.factory = RequestFactory()
        request = self.factory.get('/')
        user = get_user_model().objects.create_user(username='test_user', email='test@example.com')
        request.user = user
        session = SessionMiddleware()
        session.process_request(request)
        request.session.save()
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        ChangeRequest.thread.request = request

    def test_format_str(self):
        s = utils.format_object_str('test', None, None)
        self.assertEqual(s, 'test')
        s = utils.format_object_str('test', 'test', None)
        self.assertEqual(s, 'test "test"')
        s = utils.format_object_str('test', 'test', 'test')
        self.assertEqual(s, 'test "test" (test)')

    def test_model_to_dict(self):
        # Simple Model
        q = models.Question(question_text='What?')
        expected = {'question_text': 'What?', 'pub_date': None}
        self.assertDictEqual(utils.model_to_dict(q), expected)
        # Don't exclude Primary Key
        profile = models.PersonProfile(description='somebody')
        profile.save()
        expected = {'id': 1, 'description': 'somebody'}
        self.assertEqual(utils.model_to_dict(profile, exclude_pk=False), expected)
        # Model with One-to-One relation
        person1 = models.Person(name='john', profile=profile)
        expected = {'name': 'john', 'profile': 1}
        self.assertDictEqual(utils.model_to_dict(person1), expected)
        # Again, but now with the relation set to NULL
        person2 = models.Person(name='jane')
        expected = {'name': 'jane', 'profile': None}
        self.assertDictEqual(utils.model_to_dict(person2), expected)
        person1.save()
        person2.save()
        # Model with Foreign Key and Many-to-Many relation
        book = models.Book(title='Django')
        expected = {'title': 'Django', 'author': None, 'editor': []}
        self.assertDictEqual(utils.model_to_dict(book), expected)
        book.author = person1
        book.save()
        book.editor.add(person1)
        book.editor.add(person2)
        book.save()
        expected = {'title': 'Django', 'author': 1, 'editor': [1, 2]}
        self.assertDictEqual(utils.model_to_dict(book), expected)
        # Model with a FileField (empty)
        f = models.Files()
        expected = {'file_field': '', 'image_field': ''}
        self.assertDictEqual(utils.model_to_dict(f), expected)
        # Model with a FileField (set)
        f.file_field = SimpleUploadedFile('test.txt', b'Test')
        f.image_field = SimpleUploadedFile('tiny.gif', b'GIF89a\x01\x00\x01\x00\x00\xff\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x00;')
        expected = {'file_field': 'test.txt', 'image_field': 'tiny.gif'}
        self.assertDictEqual(utils.model_to_dict(f), expected)
        # Don't save the Files object as that will save files to storage

    def test_get_ip_from_request(self):
        # No Proxy
        request = ChangeRequest.get_request()
        self.assertEqual(utils.get_ip_from_request(request), '127.0.0.1')
        # Proxy
        request.META['HTTP_X_FORWARDED_FOR'] = '192.168.1.1'
        self.assertEqual(utils.get_ip_from_request(request), '192.168.1.1')
        request.META['HTTP_X_FORWARDED_FOR'] = '192.168.1.2, "192.168.255.255, "'
        self.assertEqual(utils.get_ip_from_request(request), '192.168.1.2')
        request.META['HTTP_X_FORWARDED_FOR'] = '"192.168.1.3"'
        self.assertEqual(utils.get_ip_from_request(request), '192.168.1.3')
