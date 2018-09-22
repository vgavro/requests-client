from .utils import ReprMixin
from .cursor_fetch import (  # noqa backward compatibility
    CursorFetchGenerator, CursorFetchGeneratorError
)


def _maybe_deserialize(data, key, model):
    if key in data and isinstance(data[key], dict):
        data[key] = model(**data[key])


def _maybe_deserialize_list(data, key, model):
    if key in data and len(data[key]) and isinstance(data[key][0], dict):
        data[key] = [model(**obj) for obj in data[key]]


def _maybe_to_dict(value):
    if callable(getattr(value, 'to_dict', None)):
        return value.to_dict()
    return value


class Entity(ReprMixin):
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __contains__(self, key):
        return hasattr(self, key)

    @property
    def meta(self):
        if not hasattr(self, '_meta'):
            self._meta = {}
        return self._meta

    @property
    def _fields(self):
        if hasattr(self, '__slots__'):
            return self.__slots__

    def update(self, other):
        if isinstance(other, dict):
            for k, v in other.items():
                if k != '_meta':
                    setattr(self, k, v)

        elif isinstance(other, Entity):
            if self.__class__ is not other.__class__:
                raise TypeError('Can\'t update {} with {}'
                                .format(self.__class__, other.__class__))

            for k in (self._fields or other.__dict__.keys()):
                if hasattr(other, k) and k != '_meta':
                    setattr(self, k, getattr(other, k))

        else:
            raise TypeError('Can\'t update {}: unknown type: {}'
                            .format(self.__class__, type(other)))

    def to_dict(self, *args, exclude=[], required=True):
        return {
            k: _maybe_to_dict(getattr(self, k))
            for k in (args or self._fields or self.__dict__.keys())
            if (not k.startswith('_') and k not in exclude and
                (args and required or hasattr(self, k)))
        }


class SlottedEntity(Entity):
    # "_entity" is used for full entity remote data in debug mode
    # to lookup fields not binded from schema
    __slots__ = ['_entity', '_meta']


class ClientEntity(Entity):
    def __init__(self, client=None, **kwargs):
        self._client = client
        super().__init__(**kwargs)

    @property
    def client(self):
        if not getattr(self, '_client', None):
            raise RuntimeError('Entity %s is not binded to client', self.__class__)
        return self._client

    @client.setter
    def client(self, client):
        self._client = client
