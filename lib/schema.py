from marshmallow import Schema, fields, pprint

class ComposableDict(fields.Dict):
    def __init__(self, inner, *args, **kwargs):
        self.inner = inner
        super().__init__(*args, **kwargs)

    def _serialize(self, value, attr, obj):
        return {
            key: self.inner._serialize(val, key, value)
            for key, val in value.items()
        }

class HAProxySchema(Schema):
    global_params = fields.List(fields.String())
    default_params = fields.List(fields.String())

class ServiceSchema(Schema):
    port = fields.

class BaseSchema(Schema):
    haproxy = fields.Nested(HAProxySchema)
    services = fields.ComposableDict(fields.Nested(ServiceSchema))
