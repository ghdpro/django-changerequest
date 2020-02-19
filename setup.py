from setuptools import setup, find_packages
from changerequest import __version__


def read(file):
    with open(file, 'r') as f:
        return f.read()


setup(
    name='django-changerequest',
    version='.'.join(str(x) for x in __version__),
    description='A package for the Django Framework that provides auditing and staged editing functionality',
    long_description=read('README.rst'),
    long_description_content_type='text/x-rst',
    packages=find_packages(),
    install_requires=[
        'django>=3.0.3',
    ],
    python_requires='>=3.7',
    author='Gerard Krijgsman',
    author_email='python@visei.com',
    url='https://github.com/ghdpro/django-changerequest',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Framework :: Django :: 3.0',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3 :: Only',
    ]
)
