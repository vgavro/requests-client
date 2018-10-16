from copy import deepcopy
from datetime import timezone

from marshmallow import fields

from .utils import import_string, resolve_obj_path, from_timestamp, to_timestamp


class DateTimeField(fields.DateTime):
    # TODO: refactor it to be consistent with new marshmallow api or remove if
    # merge request will be accepted
    """
    While https://github.com/marshmallow-code/marshmallow/pull/1003 is not merged
    (if it will be merged at all?)
    """

    SERIALIZATION_FUNCS = {
        **fields.DateTime.SERIALIZATION_FUNCS.copy(),
        'timestamp': to_timestamp,
        'timestamp_ms': lambda v, localtime: to_timestamp(v) * 1000
    }

    DESERIALIZATION_FUNCS = {
        **fields.DateTime.DESERIALIZATION_FUNCS.copy(),
        'timestamp': from_timestamp,
        'timestamp_ms': lambda v: from_timestamp(float(v) / 1000),
    }

    def __init__(self, format=None, timezone=None, timezone_naive=False, **kwargs):
        super().__init__(**kwargs)
        # Allow format to be None. It may be set later in the ``_serialize``
        # or ``_deserialize`` methods This allows a Schema to dynamically set the
        # format, e.g. from a Meta option
        self.format = format
        self.timezone = timezone  # TODO: add str conversion if isinstance(timezone, basestring)
        self.timezone_naive = timezone_naive

    def _serialize(self, value, attr, obj):
        if value is None:
            return None
        if self.timezone:
            if value.tzinfo is None:
                value = value.replace(tzinfo=self.timezone)
            if self.format in ('timestamp', 'timestamp_ms'):
                # We're replacing to UTC to prevent to_timestamp from utc_offset conversion
                # in case timezone is not UTC
                value = value.astimezone(self.timezone).replace(tzinfo=timezone.utc)
        return super()._serialize(value, attr, obj)

    def _deserialize(self, value, attr, data):
        if not value and value != 0:  # Falsy values, e.g. '', None, [] are not valid
            self.fail('invalid', obj_type=self.OBJ_TYPE)
        dt = super()._deserialize(value, attr, data)

        if self.timezone and (dt.tzinfo is None or self.format in ('timestamp', 'timestamp_ms')):
            dt = dt.replace(tzinfo=self.timezone)
        if self.timezone_naive:
            if self.timezone and value.tzinfo is not None:
                return dt.astimezone(self.timezone).replace(tzinfo=None)
            return dt.replace(tzinfo=None)
        return dt


class TimestampField(DateTimeField):
    def __init__(self, format='timestamp', **kwargs):
        if format not in ('timestamp', 'timestamp_ms'):
            raise ValueError('Unexpected timestamp format: %s' % format)
        self.zero_as_none = kwargs.pop('zero_as_none', False)
        super().__init__(format, **kwargs)

    def _serialize(self, value, attr, obj):
        if self.zero_as_none and value is None:
            return 0
        return super()._serialize(value, attr, obj)

    def _deserialize(self, value, attr, data):
        if self.zero_as_none and value == 0:
            return None
        return super()._deserialize(value, attr, data)


class SchemedEntityField(fields.Nested):
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
            self.nested.fields = self.nested._init_fields()
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

    def _bind_to_schema(self, field_name, schema):
        super()._bind_to_schema(field_name, schema)

        def getter(instance):
            return self.get(getattr(instance, field_name))

        target = resolve_obj_path(self, self.bind_target)
        prop = property(getter)
        setattr(target, self.bind_attr, prop)

        if self.setter:
            def setter(instance, val):
                return setattr(instance, field_name, self.setter(val))
            setattr(target, self.bind_attr, prop.setter(setter))
