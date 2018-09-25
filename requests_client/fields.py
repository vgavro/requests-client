from marshmallow import fields, ValidationError
# from marshmallow.utils import is_collection

from .utils import datetime_from_utc_timestamp, import_string, resolve_obj_path


class DateTimeField(fields.DateTime):
    """
    Class extends marshmallow standart DateTime with "timestamp" format.
    """

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


class SchemedEntityField(fields.Nested):
    def __init__(self, entity, **kwargs):
        self.entity = entity
        super().__init__(None, **kwargs)  # Allows lazy model import if entity is string

    @property
    def schema(self):
        if not self.nested:
            self.entity = self.resolve_entity(self.entity)
            self.nested = self.entity.schema
        return super().schema

    def resolve_entity(self, entity):
        if isinstance(entity, str):
            return import_string(entity)
        return entity

    def _load(self, value, data):
        # For some reason schema always created in Nested field, and many is passed to __init__
        # instead of load, so just override it with many=self.many.
        try:
            return self.schema.load(value, many=self.many, unknown=self.unknown)
        except ValidationError as exc:
            raise ValidationError(exc.messages, data=data, valid_data=exc.valid_data)

    def _deserialize(self, value, attr, data):
        data = super()._deserialize(value, attr, data)
        if self.many:
            return [self.entity(**data_) for data_ in data]
        return self.entity(**data)


class BindPropertyField(fields.Field):
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
        property_ = property(getter)
        setattr(target, self.bind_attr, property_)

        if self.setter:
            def setter(instance, val):
                return setattr(instance, field_name, self.setter(val))
            setattr(target, self.bind_attr, property_.setter(setter))
