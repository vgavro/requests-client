import marshmallow as ma
from marshmallow.utils import EXCLUDE

from .models import ClientEntity
from .utils import maybe_attr_dict, datetime_from_utc_timestamp, pprint


class ResponseSchema(ma.Schema):
    data_path = None

    def __init__(self, **kwargs):
        if 'unknown' not in kwargs:
            kwargs['unknown'] = EXCLUDE
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
        if isinstance(self.Meta.model, ClientEntity):
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


class DateTime(ma.fields.DateTime):
    """
    Class extends marshmallow standart DateTime with "timestamp" format.
    """

    DATEFORMAT_SERIALIZATION_FUNCS = \
        ma.fields.DateTime.DATEFORMAT_SERIALIZATION_FUNCS.copy()
    DATEFORMAT_DESERIALIZATION_FUNCS = \
        ma.fields.DateTime.DATEFORMAT_DESERIALIZATION_FUNCS.copy()

    DATEFORMAT_SERIALIZATION_FUNCS['timestamp'] = lambda x: x.timestamp()
    DATEFORMAT_DESERIALIZATION_FUNCS['timestamp'] = datetime_from_utc_timestamp


def maybe_create_response_schema(schema, inherit=None):
    inherit = inherit or (ResponseSchema,)

    if isinstance(schema, type):
        return schema()
    elif isinstance(schema, dict):
        return type('_Schema', inherit, schema)()
    else:
        return schema