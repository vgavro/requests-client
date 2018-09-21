import logging
import json
from datetime import datetime, date, timezone


class EntityLoggerAdapter(logging.LoggerAdapter):
    """
    Adds info about the entity to the logged messages.
    """
    def __init__(self, logger, entity):
        self.logger = logger
        self.entity = entity or '?'

    def process(self, msg, kwargs):
        return '[{}] {}'.format(self.entity, msg), kwargs


def _resolve_obj_key(obj, key, suppress_exc):
    if key.isdigit():
        try:
            return obj[int(key)]
        except Exception:
            try:
                return obj[key]
            except Exception as exc:
                if suppress_exc:
                    return exc
                raise ValueError('Could not resolve "{}" on {} object: {}'.format(key, obj))
    else:
        try:
            return obj[key]
        except Exception:
            try:
                return getattr(obj, key)
            except Exception as exc:
                if suppress_exc:
                    return exc
                raise ValueError('Could not resolve "{}" on {} object'.format(key, obj))


def resolve_obj_path(obj, path, suppress_exc=False):
    dot_pos = path.find('.')
    if dot_pos == -1:
        return _resolve_obj_key(obj, path, suppress_exc)
    else:
        key, path = path[:dot_pos], path[(dot_pos + 1):]
        return resolve_obj_path(_resolve_obj_key(obj, key, suppress_exc),
                                path, suppress_exc)


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
    return data


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
        attrs = ', '.join(u'{}={}'.format(k, repr(v) if full else repr_str_short(repr(v)))
                          for k, v in attrs.items())
        return '<{}({})>'.format(self.__class__.__name__, attrs)

    def to_dict(self, *args, exclude=[], required=True):
        if not args:
            args = self.__dict__.keys()
        return {key: self.__dict__[key] for key in args
                if not key.startswith('_') and key not in exclude and
                (required or key in self.__dict__)}

    def _pprint(self, *args, **kwargs):
        return pprint(self, *args, **kwargs)


class SlotsReprMixin(ReprMixin):
    def to_dict(self, *args, exclude=[], required=True):
        return {k: getattr(self, k) for k in (args or self.__slots__)
                if not k.startswith('_') and
                (hasattr(self, k) or (args and required and k in args)) and
                k not in exclude}


def maybe_encode(string, encoding='utf-8'):
    return isinstance(string, bytes) and string or str(string).encode(encoding)


def maybe_decode(string, encoding='utf-8'):
    return isinstance(string, str) and string.decode(encoding) or string


def datetime_from_utc_timestamp(timestamp):
    return datetime.utcfromtimestamp(float(timestamp)).replace(tzinfo=timezone.utc)


def utcnow():
    return datetime.now(tz=timezone.utc)


def pprint(obj, indent=2, colors=True):
    def default(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        raise TypeError('Type %s not serializable' % type(obj))

    rv = json.dumps(obj, default=default, indent=indent, ensure_ascii=False)

    if colors:
        try:
            from pygments import highlight
            from pygments.lexers import JsonLexer
            from pygments.formatters import TerminalFormatter
        except ImportError:
            pass
        else:
            rv = highlight(rv, JsonLexer(), TerminalFormatter())

    print(rv.strip(), end='')
