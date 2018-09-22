from .utils import resolve_obj_path, repr_response
from requests import Response


class Retry(Exception):
    """
    Raise this exception if you want to retry request, but not raise TemporaryError
    on retries exceeded.
    """
    def __init__(self, result, retry_ident='default', retry_count=1, wait_seconds=0):
        self.result = result
        self.retry_ident = retry_ident
        self.retry_count = retry_count
        self.wait_seconds = wait_seconds
        super().__init__(result, retry_ident, retry_count, wait_seconds)


class ClientError(Exception):
    msg = None

    def __init__(self, resp, msg=None, *args, **kwargs):
        if isinstance(resp, ClientError):
            resp = resp.resp
        self.resp = resp
        if msg:
            self.msg = msg
        super().__init__(resp, msg, *args, **kwargs)

    @property
    def response(self):
        # TODO: refactor all code, leave "resp" only
        return self.resp

    def __str__(self, full=False):
        if self.resp is None:  # response will be false if it's status code is not ok
            resp_repr = '[no response]'
        else:
            resp_repr = repr_response(self.resp, full)
        msg = self.get_message(full)
        return '{}: {}'.format(msg, resp_repr) if msg else resp_repr

    def __repr__(self, full=False):
        return '<{}: {}>'.format(self.__class__.__name__, self.__str__(full=full))

    def get_message(self, full=False):
        return self.msg

    @property
    def data(self):
        if self.resp is not None:
            return getattr(self.resp, 'data', None)
        return None

    def get_data(self, path):
        if self.data:
            try:
                return resolve_obj_path(self.data, path)
            except Exception:
                pass


class RetryExceeded(ClientError):
    def __init__(self, result, msg=None, retry_ident=None, retry_count=None):

        if isinstance(result, ClientError):
            resp = result.resp
            msg = msg or result.msg
            reason = result.__class__.__name__
        elif isinstance(result, Response):
            resp = result
            reason = None
        else:
            resp = None
            reason = repr(result)

        self.result = result
        self.retry_ident = retry_ident
        self.retry_count = retry_count
        self.reason = retry_ident != 'default' and retry_ident or reason or 'default'

        super().__init__(resp, msg, retry_ident, retry_count)

    def get_message(self, full=False):
        msg ='Retries({}) on "{}" exceeded'.format(self.retry_count, self.reason)
        return self.msg and '{}: {}'.format(msg, self.msg) or msg


class HTTPError(ClientError):
    def __init__(self, resp, msg=None, expected_status=None):
        self.expected_status = expected_status
        self.status = resp.status_code
        super().__init__(resp, msg, expected_status)

    def get_message(self, full=False):
        msg = '{} {} (!={})'.format(self.resp.status_code, self.resp.reason,
                                    self.expected_status)
        return self.msg and '{}: {}'.format(msg, self.msg) or msg


class TemporaryError(ClientError):
    def __init__(self, resp=None, msg=None, wait_seconds=None, original_exc=None):
        self.wait_seconds = wait_seconds
        self.original_exc = original_exc
        if resp is None and isinstance(original_exc, ClientError):
            resp = original_exc.resp
        super().__init__(resp, msg, wait_seconds, original_exc)


class RatelimitError(TemporaryError):
    pass


class AuthError(ClientError):
    """
    This is critical to client exceptions.
    Ident is account username.
    """
    def __init__(self, resp, msg=None, ident=None, *args, **kwargs):
        self.ident = ident
        super().__init__(resp, msg, ident, *args, **kwargs)

    def get_message(self, full=False):
        return '{}: {}'.format(self.ident, self.msg)


class AuthRequired(AuthError):
    pass


class EntityError(ClientError):
    def __init__(self, response, msg, entity_type, entity_id):
        if isinstance(entity_type, str):
            self.entity_type = entity_type
        else:
            self.entity_type = entity_type.__name__
        self.entity_id = entity_id
        super().__init__(response, msg, entity_type, entity_id)


class EntityNotFound(EntityError):
    def get_message(self, full=False):
        msg_ = '{}({}) not found'.format(self.entity_type, self.entity_id)
        return self.msg and '{}: {}'.format(msg_, self.msg) or msg_


class EntityForbidden(EntityError):
    def get_message(self, full=False):
        msg_ = '{}({}) forbidden'.format(self.entity_type, self.entity_id)
        return self.msg and '{}: {}'.format(msg_, self.msg) or msg_


class ResponseValidationError(ClientError):
    def __init__(self, response, msg=None, schema=None, errors=None):
        self.schema = schema
        self.errors = errors
        super().__init__(response, msg)

    def get_message(self, full=False):
        errors = str(self.errors)
        if not full and len(errors) > 64:
            errors = '{}..{}b'.format(errors[:64], len(errors))
        return self.msg and (self.msg + ': ' + errors) or errors
