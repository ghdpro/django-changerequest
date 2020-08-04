from django.db import models

from changerequest.models import HistoryModel


class Question(HistoryModel):
    question_text = models.CharField(max_length=200)
    pub_date = models.DateTimeField('date published')


class Choice(HistoryModel):
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    choice_text = models.CharField(max_length=200)
    votes = models.IntegerField(default=0)


class PersonProfile(HistoryModel):
    description = models.TextField()


class Person(HistoryModel):
    name = models.CharField(verbose_name='person name', max_length=200)
    profile = models.OneToOneField(PersonProfile, on_delete=models.SET_NULL, null=True, blank=True)


class Book(HistoryModel):
    title = models.CharField(verbose_name='book title', max_length=200)
    author = models.ForeignKey(Person, related_name='author', on_delete=models.CASCADE)
    editor = models.ManyToManyField(Person, related_name='editor')


class Numbers(HistoryModel):
    big_integer = models.BigIntegerField()
    decimal = models.DecimalField(max_digits=5, decimal_places=2)
    float = models.FloatField()
    integer = models.IntegerField()
    positive_int = models.PositiveIntegerField()


class Letters(HistoryModel):
    char = models.CharField(max_length=10)
    email = models.EmailField()
    url = models.URLField()


class DateTime(HistoryModel):
    date_field = models.DateField()
    datetime_field = models.DateTimeField()
    duration = models.DurationField()
    time_field = models.TimeField()


class Files(HistoryModel):
    binary = models.BinaryField()
    file_field = models.FileField()
    image_field = models.ImageField()


class Other(HistoryModel):
    boolean = models.BooleanField()
    generic_ip = models.GenericIPAddressField()
    null_boolean = models.NullBooleanField()
    uuid = models.UUIDField()
