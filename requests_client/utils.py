import logging
import json
from datetime import datetime, date, timezone
from collections import OrderedDict, Mapping
from enum import Enum
from importlib import import_module

from marshmallow import missing


NO_DEFAULT = object()


class EnumByNameMixin:
    # Allows to get Enum mixed by value or by name
    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            try:
                return cls[value]
            except KeyError:
                try:
                    return cls[value.upper()]
                except KeyError:
                    pass
        return super()._missing_(value)


class Enum(EnumByNameMixin, Enum):
    pass


class class_or_instance_property(object):
    # https://stackoverflow.com/a/3203659/450103
    def __init__(self, getter):
        self.getter = getter

    def __get__(self, instance, owner):
        return self.getter(instance or owner)


class EntityLoggerAdapter(logging.LoggerAdapter):
    """
    Adds info about the entity to the logged messages.
    """
    def __init__(self, logger, entity):
        self.logger = logger
        self.entity = entity or '?'

    def process(self, msg, kwargs):
        return '[{}] {}'.format(self.entity, msg), kwargs


def resolve_obj_key(obj, key, default=NO_DEFAULT):
    if key.isdigit():
        try:
            return obj[int(key)]
        except Exception:
            try:
                return obj[key]
            except Exception as exc:
                if default is not NO_DEFAULT:
                    return default
                raise ValueError('Could not resolve "{}" on {} object: {}'.format(key, obj))
    else:
        try:
            return obj[key]
        except Exception:
            try:
                return getattr(obj, key)
            except Exception as exc:
                if default is not NO_DEFAULT:
                    return default
                raise ValueError('Could not resolve "{}" on {} object'.format(key, obj))


def resolve_obj_path(obj, path, default=NO_DEFAULT):
    dot_pos = path.find('.')
    if dot_pos == -1:
        return resolve_obj_key(obj, path, default)
    else:
        key, path = path[:dot_pos], path[(dot_pos + 1):]
        return resolve_obj_path(resolve_obj_key(obj, key, default),
                                path, default)


class AttrDict(dict):
    def __getattr__(self, attr):
        try:
            return self[attr]
        except KeyError:
            raise AttributeError(attr)

    def __dir__(self):
        # Autocompletion for ipython
        return super().__dir__() + list(self.keys())

    def __getstate__(self):
        # We need it for pickle because it depends on __getattr__
        return dict(self)

    def __setstate__(self, dict_):
        self.update(dict_)


def maybe_attr_dict(data):
    if isinstance(data, dict):
        return AttrDict({k: maybe_attr_dict(v) for k, v in data.items()})
    elif isinstance(data, (tuple, list, set)):
        return data.__class__(maybe_attr_dict(item) for item in data)
    return data


class cached_property(property):
    # https://github.com/pallets/werkzeug/blob/master/werkzeug/utils.py
    # Actually we're not using functools.lru_cache because we want to set
    # cached values outside the function sometime, and lru_cache
    # not give us easy way to do this.
    def __init__(self, func, name=None, doc=None):
        self.__name__ = name or func.__name__
        self.__module__ = func.__module__
        self.__doc__ = doc or func.__doc__
        self.func = func

    def __set__(self, obj, value):
        obj.__dict__[self.__name__] = value

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        value = obj.__dict__.get(self.__name__, missing)
        if value is missing:
            value = self.func(obj)
            obj.__dict__[self.__name__] = value
        return value


def repr_response(resp, full=False):
    # requests.models.Response
    if not full and len(resp.content) > 128:
        content = '{}...{}b'.format(resp.content[:128],
                                    len(resp.content))
    else:
        content = resp.content

    url = resp.url
    if resp.status_code in (301, 302):
        url += ' -> {}'.format(resp.headers.get('Location'))

    return '{} {} {}: {}'.format(resp.request.method, resp.status_code, url, content)


def repr_str_short(value, length=32):
    if len(value) > length:
        return value[:length] + '...'
    return value


class ReprMixin:
    def __repr__(self, *args, full=False, required=False, **kwargs):
        attrs = self.to_dict(*args, required=required, **kwargs)
        attrs = ', '.join(
            '{}={}'.format(k, repr(v) if full else repr_str_short(repr(v)))
            for k, v in attrs.items()
        )
        return '<{}({})>'.format(self.__class__.__name__, attrs)

    def to_dict(self, *args, exclude=[], required=True):
        return {
            k: self.__dict__[k] for k in (args or self.__dict__.keys())
            if (not k.startswith('_') and k not in exclude and
                (args and required or k in self.__dict__))
        }


class SlotsReprMixin(ReprMixin):
    def to_dict(self, *args, exclude=[], required=True):
        return {
            k: getattr(self, k) for k in (args or self.__slots__)
            if (not k.startswith('_') and k not in exclude and
                (args and required or hasattr(self, k)))
        }


def maybe_encode(string, encoding='utf-8'):
    return isinstance(string, bytes) and string or str(string).encode(encoding)


def maybe_decode(string, encoding='utf-8'):
    return isinstance(string, str) and string.decode(encoding) or string


def from_timestamp(timestamp, tzinfo=timezone.utc):
    return datetime.utcfromtimestamp(float(timestamp)).replace(tzinfo=tzinfo)


def to_timestamp(dt, utc_offset=True):
    """Converts to timestamp, preserves offset if utc_offset=False"""
    if dt.tzinfo is None or not utc_offset:
        return dt.replace(tzinfo=timezone.utc).timestamp()
    return dt.timestamp()


def utcnow():
    return datetime.now(tz=timezone.utc)


def import_string(import_name):
    *module_parts, attr = import_name.replace(':', '.').split('.')
    if not module_parts:
        raise ImportError('You must specify module and object, separated by ":" or ".", '
                          'got "{}" instead'.format(import_name))
    module = import_module('.'.join(module_parts))
    return getattr(module, attr)


def pprint(obj, indent=2, color=True, print_=True):
    # TODO: print_=True? really?

    if isinstance(obj, Mapping):
        # To convert dict-like objects, for example requests.structures.CaseInsensitiveDict
        obj = OrderedDict(obj)
    if isinstance(obj, bytes):
        try:
            obj = obj.decode('utf-8')
        except Exception:
            pass
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            pass

    def default(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        raise TypeError('Type %s not serializable' % type(obj))

    rv = json.dumps(obj, default=default, indent=indent, ensure_ascii=False)

    if color:
        try:
            from pygments import highlight
            from pygments.lexers import JsonLexer
            from pygments.formatters import Terminal256Formatter
            from pygments.styles.emacs import EmacsStyle
            from pygments.token import Number
        except ImportError:
            pass
        else:
            class Style(EmacsStyle):
                # TODO: this is not the best style, but better than default
                styles = {
                    **EmacsStyle.styles.copy(),
                    Number: 'bold #B88608',
                }
            rv = highlight(rv, JsonLexer(), Terminal256Formatter(style=Style))

    if print_:
        print(rv.strip(), end='')
    else:
        return rv.strip()
