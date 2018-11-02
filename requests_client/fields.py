from copy import deepcopy

from marshmallow import fields
from dateutil.tz import UTC

from .utils import import_string, resolve_obj_path, from_timestamp, to_timestamp, get_tz


class Timestamp(fields.Field):
    # NOTE: remove this as soon as this will be merged
    # https://github.com/marshmallow-code/marshmallow/pull/1009
    """Timestamp field, converts to datetime.

    :param timezone: Timezone of timestamp (defaults to UTC).
        Timezone-aware datetimes will be converted to this before serialization,
        timezone-naive datetimes will be serialized as is (in timestamp timezone).
    :param bool ms: Milliseconds instead of seconds, defaults to `False`. For javascript
        compatibility.
    :param bool naive: Should deserialize to timezone-naive or timezone-aware datetime.
        Defaults to `False`, so all datetimes will be timezone-aware with `timezone`.
    :param bool as_int: If `True`, timestamp will be serialized to int instead of float,
        so datetime microseconds precision can be lost. Note that this affects milliseconds also,
        because 1 millisecond is 1000 microseconds.  Defaults to `False`.
    :param kwargs: The same keyword arguments that :class:`Field` receives.
    """
    def __init__(self, timezone=UTC, ms=False, naive=False, as_int=False, **kwargs):
        self.timezone = get_tz(timezone)
        self.ms = ms
        self.naive = naive
        self.as_int = as_int
        super(Timestamp, self).__init__(**kwargs)

    def _serialize(self, value, attr, obj):
        if value is None:
            return None
        value = to_timestamp(value, self.timezone, self.ms)
        return int(value) if self.as_int else value

    def _deserialize(self, value, attr, data):
        try:
            return from_timestamp(value, None if self.naive else self.timezone, self.ms)
        except (ValueError, OverflowError, OSError):
            # Timestamp exceeds limits, ValueError needed for Python < 3.3
            self.fail('invalid')


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
