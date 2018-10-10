from copy import deepcopy

from marshmallow import fields

from .utils import datetime_from_utc_timestamp, import_string, resolve_obj_path


class NestedField(fields.Nested):
    """
    Fix to fallback schema load to schema defaults
    instead of overriding unknown='raise'.
    While not merged https://github.com/marshmallow-code/marshmallow/pull/963
    """

    def __init__(self, nested, **kwargs):
        kwargs.setdefault('unknown', None)
        super().__init__(nested, **kwargs)


class DateTimeField(fields.DateTime):
    """
    Class extends marshmallow standart DateTime with "timestamp" format.
    Note that this is very naive implementation, more robust solution
    now in progress with marshmallow team.
    """
    # TODO: add ticket url

    DATEFORMAT_SERIALIZATION_FUNCS = \
        fields.DateTime.DATEFORMAT_SERIALIZATION_FUNCS.copy()
    DATEFORMAT_DESERIALIZATION_FUNCS = \
        fields.DateTime.DATEFORMAT_DESERIALIZATION_FUNCS.copy()

    DATEFORMAT_SERIALIZATION_FUNCS['timestamp'] = lambda x, localtime=None: x.timestamp()
    DATEFORMAT_DESERIALIZATION_FUNCS['timestamp'] = datetime_from_utc_timestamp

    def _deserialize(self, value, attr, data):
        if self.dateformat == 'timestamp' and value == 0 and self.allow_none:
            return None
        return super()._deserialize(value, attr, data)

    def _serialize(self, value, attr, obj):
        if self.dateformat == 'timestamp' and value == 0 and self.allow_none:
            return None
        return super()._serialize(value, attr, obj)


class SchemedEntityField(NestedField):
    def __init__(self, entity, **kwargs):
        self.entity = entity
        super().__init__(None, **kwargs)  # Allows lazy model import if entity is string

    @property
    def schema(self):
        if not self.nested:
            self.entity = self.resolve_entity(self.entity)

            # Well, actually in marshmallow this options also has no effect
            # if schema was already initialized, so it's schma __init__ code below
            self.nested = deepcopy(self.entity.schema)
            self.nested.many = self.many
            self.nested.only = self.only or self.nested.only
            self.nested.exclude = self.exclude or self.nested.exclude
            self.nested.many = self.many or self.nested.many
            self.nested.context = getattr(self.parent, 'context', {})
            self.nested.load_only = self._nested_normalized_option('load_only')
            self.nested.dump_only = self._nested_normalized_option('dump_only')
            self.nested._update_fields(self.many)
        return super().schema

    def resolve_entity(self, entity):
        if isinstance(entity, str):
            return import_string(entity)
        return entity

    def _deserialize(self, value, attr, data):
        data = super()._deserialize(value, attr, data)
        if self.many:
            return [self.entity(**data_) for data_ in data]
        return self.entity(**data)


class BindPropertyField(fields.Field):
    """
    This field binds property on bind_target, which is based on field value.
    """

    container = fields.Raw
    getter, setter = None, None

    def __init__(self, bind_attr, bind_target='parent.entity', container=None,
                 getter=None, setter=None, **kwargs):
        if container:
            self.container = container
        if isinstance(self.container, type):
            self.container = self.container()
        if getter:
            self.getter = getter
        if setter:
            self.setter = setter

        if not self.getter:
            raise ValueError('getter required')

        self.bind_attr = bind_attr
        self.bind_target = bind_target
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data):
        return self.container.deserialize(value)

    def _serialize(self, value, attr, obj):
        return self.container._serialize(value, attr, obj)

    def get(self, val):
        if not hasattr(self, '_get_rv') or val != self._get_val:
            self._get_rv = self.getter(val)
            self._get_val = val
        return self._get_rv

    def _add_to_schema(self, field_name, schema):
        super()._add_to_schema(field_name, schema)

        def getter(instance):
            return self.get(getattr(instance, field_name))

        target = resolve_obj_path(self, self.bind_target)
        prop = property(getter)
        setattr(target, self.bind_attr, prop)

        if self.setter:
            def setter(instance, val):
                return setattr(instance, field_name, self.setter(val))
            setattr(target, self.bind_attr, prop.setter(setter))
