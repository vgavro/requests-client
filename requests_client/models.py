from collections import OrderedDict
from copy import deepcopy

from marshmallow import Schema

from .utils import ReprMixin, class_or_instance_property
from .schemas import get_declared_fields
from .cursor_fetch import (  # noqa backward compatibility
    CursorFetchGenerator, CursorFetchGeneratorError
)


def _maybe_deserialize(data, key, model):
    # TODO: left for compatibility, maybe it should be removed,
    # but useful for plain Entity (not SchemedEntity)
    if key in data and isinstance(data[key], dict):
        data[key] = model(**data[key])


def _maybe_deserialize_list(data, key, model):
    if key in data and len(data[key]) and isinstance(data[key][0], dict):
        data[key] = [model(**obj) for obj in data[key]]


def _maybe_to_dict(value):
    if callable(getattr(value, 'to_dict', None)):
        return value.to_dict()
    return value


# "_entity" is used for full entity remote data in debug mode
# to lookup fields not binded from schema
DEFAULT_SLOTS = ['_entity', '_meta']


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


class SchemedEntityMeta(type):
    def __new__(metacls, cls, bases, classdict):

        # TODO: allow SchemedEntity to have dynamic slots
        # based on fields. Note that __slots__ should be defined
        # before super().__new__

        # if classdict['__slots__'] is True:
        #     classdict['__slots__'] = tuple(declared_fields)
        # elif classdict['__slots__'] is False:
        #     del new_cls.__slots__  # default

        new_cls = super().__new__(metacls, cls, bases, classdict)

        if isinstance(new_cls.schema, type):
            new_cls.schema = deepcopy(new_cls.schema())
        new_cls.schema = deepcopy(new_cls.schema)
        new_cls.schema.entity = new_cls  # TODO: weakref?

        fields = OrderedDict(get_declared_fields(new_cls))
        fields.update(new_cls.schema.declared_fields)
        fields = deepcopy(fields)
        for field in fields.values():
            # For some reason it's not rebinded on _add_to_schema
            # if was already binded before copy
            field.parent = None
            field.name = None

        new_cls.schema.declared_fields = fields
        new_cls.schema._update_fields()

        for field in new_cls.schema.fields.values():
            assert field.parent

        for field_name in new_cls.schema.fields:
            # For entity.field is None and not 'field' in entity
            setattr(new_cls, field_name, None)

        return new_cls


class SchemedEntity(Entity, metaclass=SchemedEntityMeta):
    schema = Schema()
    # __slots__ = False

    @property
    def _fields(self):
        return self.schema.fields

    def dump(self, many=False, **kwargs):
        assert not many
        return self.schema.dump(self, **kwargs)

    @classmethod
    def load(cls, data, many=False, **kwargs):
        if not many:
            return cls(**cls.schema.load(data, **kwargs))
        else:
            return tuple(cls(**item) for item
                         in cls.schema.load(data, many=many, **kwargs))

    @classmethod
    def __deepcopy__(cls, memo):
        rv = deepcopy(cls)
        rv.schema.entity = rv
        return rv

    def to_dict(self, *args, **kwargs):
        # TODO: Obviously this should use dump in some way
        return super().to_dict(*args, **kwargs)


class ClientEntityMixin:
    _client = None  # TODO: weakref on bind?

    @class_or_instance_property
    def client(cls_or_self):
        if not cls_or_self._client:
            raise RuntimeError('Entity %s is not binded to client' % cls_or_self)
        return cls_or_self._client
