import copy

import marshmallow as ma
from marshmallow.base import FieldABC
from marshmallow.schema import _get_fields, _get_fields_by_mro
from marshmallow.utils import EXCLUDE

from .utils import maybe_attr_dict, pprint


def __obj_fields_iterator(obj):
    for attr_name in dir(obj):
        try:
            attr = getattr(obj, attr_name)
        except Exception:
            continue
        if isinstance(attr, FieldABC):
            yield attr_name, attr


def get_declared_fields(cls, base=FieldABC):
    return (
        _get_fields(dict(__obj_fields_iterator(cls)), base) +
        _get_fields_by_mro(cls, base)
    )


class ResponseSchema(ma.Schema):
    data_path = None

    def __init__(self, **kwargs):
        if 'unknown' not in kwargs:
            kwargs['unknown'] = EXCLUDE

        if hasattr(self.Meta, 'model') and getattr(self.Meta, 'model_fields', True):
            # Rebind fields from model, if any
            model_fields = get_declared_fields(self.Meta.model)
            if model_fields:
                self._declared_fields = copy.deepcopy(self._declared_fields)
                self._declared_fields.update(model_fields)

        super().__init__(**kwargs)

    @ma.pre_load()
    def __pre_load(self, data):
        if getattr(self.Meta, 'pdb', False):
            data = maybe_attr_dict(data)
            if callable(self.Meta.pdb):
                if self.Meta.pdb(data):
                    pprint(data)
                    import pdb
                    pdb.set_trace()
            else:
                pprint(data)
                import pdb
                pdb.set_trace()
        return data

    def create_model(self, data):
        rv = self.Meta.model(**data)
        if hasattr(rv, '_client'):
            rv._client = self.context['client']
        return rv

    @ma.post_load(pass_many=True, pass_original=True)
    def __post_load(self, data, many, original_data):
        if hasattr(self.Meta, 'model'):
            if self.context['debug_level'] >= 5:
                if many:
                    assert len(data) == len(original_data)
                    for i in range(len(data)):
                        data[i]['_entity'] = original_data[i]
                else:
                    assert isinstance(original_data, dict)
                    data['_entity'] = original_data
            if many:
                return tuple(self.create_model(d) for d in data)
            else:
                return self.create_model(data)
        return maybe_attr_dict(data)


def _replace_keys(data, pairs):
    for from_key, to_key in pairs:
        if from_key in data:
            data[to_key] = data.pop(from_key)
    return data


class LoadKeySchemaMixin:
    """
    Processing field "load_key" extra parameter.
    Works for fields like "data_key", but for deserialization only.
    Consider this as bringing back "load_from" parameter, removed since 3.0.0b8
    """
    @ma.pre_load(pass_many=True)
    def __pre_load(self, data, many):
        pairs = tuple(
            (field.metadata['load_key'], field.data_key or field_name)
            for field_name, field in self.fields.items() if 'load_key' in field.metadata
        )
        return [_replace_keys(v, pairs) for v in data] if many else _replace_keys(data, pairs)


class DumpKeySchemaMixin:
    """
    Processing field "dump_key" extra parameter.
    Works for fields like "data_key", but for serialization only.
    Consider this as bringing back "dump_to" parameter, removed since 3.0.0b8
    """
    @ma.post_dump(pass_many=True)
    def __post_dump(self, data, many):
        pairs = tuple(
            (field.data_key or field_name, field.metadata['dump_key'])
            for field_name, field in self.fields.items() if 'dump_key' in field.metadata
        )
        return [_replace_keys(v, pairs) for v in data] if many else _replace_keys(data, pairs)


def maybe_create_response_schema(schema, inherit=None):
    inherit = inherit or (ResponseSchema,)

    if isinstance(schema, type):
        return schema()
    elif isinstance(schema, dict):
        return type('_Schema', inherit, schema)()
    return schema
