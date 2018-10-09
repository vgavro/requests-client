import logging
import os.path
from collections import Mapping

try:
    from configparser import RawConfigParser
except ImportError:
    # Python2
    from ConfigParser import RawConfigParser

try:
    import yaml
except ImportError:
    yaml = None


logger = logging.getLogger(__name__)


class CreateFromConfigMixin:
    @classmethod
    def create_from_config(cls, path=None):
        filename, kwargs = get_config(cls.__name__.replace('Client', '').lower(), path)
        logger.info('Creating %s from config %s', cls, filename)
        return cls(**kwargs)


def get_config(basename, path=None):
    if not path:
        path = [p % basename for p in ['%s.ini', '~/%s.ini', '%s.yaml', '~/%s.yaml']]
    elif isinstance(path, str):
        path = [path]

    for filename in map(os.path.expanduser, path):
        if os.path.exists(filename):
            if filename.endswith('.ini'):
                parser = RawConfigParser()
                parser.read_string('[_default_section]\n' + open(filename, 'r').read())
                section = basename if basename in parser else '_default_section'
                return filename, dict(parser[section])

            elif filename.endswith('.yaml') and yaml:
                data = yaml.load(open(filename, 'rb').read())
                if not isinstance(data, Mapping):
                    raise ValueError('Expected mapping in %s, got %s' % (filename, type(data)))
                if basename in data and isinstance(data[basename], Mapping):
                    return filename, data[basename]
                return filename, data

            else:
                raise ValueError('Unknown config extension: %s' % filename)

    raise RuntimeError('Config not found in %s (pyyaml installed %s)' % (path, bool(yaml)))
