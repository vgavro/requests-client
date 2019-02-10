from setuptools import setup, find_packages

requires = [
    'requests[socks]>=2.13',
    'python-dateutil>=2.7',
    'marshmallow==3.0.0rc1',

    # development
    'ipython',
    'parso>=0.1.1',  # turns of verbose debug messages on ipython autocomplete
    'click',
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
    version='0.0.9',
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
