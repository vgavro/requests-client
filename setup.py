from setuptools import setup, find_packages

requires = [
    'requests[socks]>=2.13',
    'python-dateutil>=2.6',
    # TODO: migrate to >=3.0.0b8
    # see https://github.com/marshmallow-code/marshmallow/blob/dev/CHANGELOG.rst
    # for backward incompatible changes
    'marshmallow>=3.0.0b16',

    # development
    'ipython',
    'parso>=0.1.1',  # turns of verbose debug messages on ipython autocomplete
    'pdbpp',
    'colorama',
    'coloredlogs',
    'pygments',

    # tests
    'requests-mock',
    'pytest>=3.8',
    'pytest-cov',
    'pytest-flake8',
    'pytest-variables[yaml]',
]

setup(
    name='requests-client',
    version='0.0.1',
    description='http://github.com/vgavro/requests-client',
    long_description='http://github.com/vgavro/requests-client',
    license='BSD',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    author='Victor Gavro',
    author_email='vgavro@gmail.com',
    url='http://github.com/vgavro/requests-client',
    keywords='',
    packages=find_packages(),
    install_requires=requires,
)
