import logging
from functools import wraps
from urllib.parse import urlparse

from requests import Session, Response
from marshmallow import ValidationError
import colorama

from .storage import FileStorage
from .utils import EntityLoggerAdapter, resolve_obj_path, maybe_attr_dict, utcnow, pprint
from .schemas import maybe_create_response_schema
from . import exceptions
from .exceptions import Retry, ClientError, RatelimitError, TemporaryError, AuthRequired

try:
    from gevent import sleep
except ImportError:
    from time import sleep


logger = logging.getLogger(__name__)


JSON_CONTENT_TYPES = ['application/json', 'application/hal+json']


def check_http_status(status, expected):
    if isinstance(expected, (tuple, list)):
        return any(check_http_status(status, status_) for status_ in expected)
    if not isinstance(expected, int):
        raise ValueError('Wrong expected http status: %s' % expected)
    if expected < 10:
        # 2 means any 2xx status code
        return 0 <= status - (expected * 100) < 100
    return status == expected


def _color_em(text, style=colorama.Style.BRIGHT, fore=colorama.Fore.WHITE, back=colorama.Back.BLUE):
    return colorama.Style.RESET_ALL + style + fore + back + text + colorama.Style.RESET_ALL


class BaseClientMeta(type):
    def __new__(metacls, cls, bases, classdict):
        client_cls = super().__new__(metacls, cls, bases, classdict)

        for name, exc_cls in exceptions.__dict__.items():
            if isinstance(exc_cls, type) and issubclass(exc_cls, ClientError):
                setattr(client_cls, name, type(name, (client_cls.ClientErrorMixin, exc_cls), {}))
        return client_cls


class BaseClient(metaclass=BaseClientMeta):
    """
    Abstract class for requests client.
    """

    class ClientErrorMixin:
        pass

    base_url = None  # Set this constant in childs
    allow_redirects = False
    auth_ident = None

    storage_cls = FileStorage  # For production usage this should be Redis
    storage_uri = './tmp'
    _state_attributes = None  # implement for each client type

    debug_level = 4  # 1-5 for vebosity level, warnings and more data collecting

    session_cls = Session
    timeout = 30  # http://docs.python-requests.org/en/master/user/quickstart/#timeouts
    request_wait_seconds = 0  # minimum delay between old *sent* time between sending new request
    request_wait_with_response_time = False
    request_warn_elapsed_seconds = 5  # warn if request took more than "x" seconds
    ratelimit_retries = 0  # retry of same request before exception. 0 is "no retry"
    ratelimit_wait_seconds = 0  # sleep before next retry
    temporary_error_retries = 1  # retry of same request before exception. 0 is "no retry"
    temporary_error_wait_seconds = 0  # sleep before next retry

    calls_count = 0  # total responses count after client was initialized
    calls_elapsed_seconds = 0  # total seconds waited for responses
    first_call_time = None  # datetime of first call (before sending request) (utc)
    last_call_time = None  # datetime of last call (before sending request) (utc)
    auto_authenticate = True
    is_authenticated = False

    def __init__(self, auth_ident=None, debug_level=None,
                 session={}, load_state=True, logger=None, timeout=True,
                 request_wait_seconds=None, request_wait_with_response_time=None,
                 request_warn_elapsed_seconds=None,
                 ratelimit_retries=None, ratelimit_wait_seconds=None,
                 temporary_error_retries=None, temporary_error_wait_seconds=None,
                 storage_cls=None, storage_uri=None,
                 state_storage=None, proxy_url=None, ssl_verify=True,
                 auto_authenticate=None):

        if auth_ident:
            self.auth_ident = auth_ident
        self.debug_level = debug_level or self.debug_level
        self.session = isinstance(session, dict) and self.session_cls(**session) or session

        # NOTE - it's not best decision to rely on username for logging,
        # but it's more obvious than account_id for now.
        # Maybe it would be changed using project-wide new logging architecture
        self.logger = logger or EntityLoggerAdapter(globals()['logger'],
                                                    self.auth_name or self.auth_ident)
        if self.debug_level >= 4:
            params = ', '.join(['{}={:.16}'.format(k, str(v)) for k, v in locals().items()
                                if v is not None and k != 'self'])
            self.logger.debug('Initialized <%s(%s) at %s>', self.__class__.__name__,
                              params, hex(id(self)))
        self.timeout = self.timeout if timeout is True else timeout
        self.request_wait_seconds = request_wait_seconds or self.request_wait_seconds
        self.request_wait_with_response_time = (request_wait_with_response_time or
                                                self.request_wait_with_response_time)
        self.request_warn_elapsed_seconds = (request_warn_elapsed_seconds or
                                             self.request_warn_elapsed_seconds)
        self.ratelimit_retries = ratelimit_retries or self.ratelimit_retries
        self.ratelimit_wait_seconds = ratelimit_wait_seconds or self.ratelimit_wait_seconds
        self.temporary_error_retries = temporary_error_retries or self.temporary_error_retries
        self.temporary_error_wait_seconds = (temporary_error_wait_seconds or
                                             self.temporary_error_wait_seconds)

        self.storage_cls = storage_cls or self.storage_cls
        self.storage_uri = storage_uri or self.storage_uri
        self.state_storage = (state_storage if state_storage is not None else
                              self.storage_factory('state', storage_cls, storage_uri))

        self.proxy = proxy_url and {'http': proxy_url, 'https': proxy_url} or None
        self.ssl_verify = ssl_verify
        self.auto_authenticate = (auto_authenticate if auto_authenticate is not None
                                  else self.auto_authenticate)

        if load_state and self._state_attributes:
            if not self.load_state(load_state is not True and load_state or None):
                self.init_state()
        else:
            self.init_state()

    @property
    def auth_ident(self):
        raise NotImplementedError()

    @property
    def auth_name(self):
        return self.auth_ident

    @property
    def auth_repr(self):
        if self.auth_name and self.auth_name != self.auth_ident:
            return '{} {}'.format(self.auth_ident, self.auth_name)
        return str(self.auth_ident)

    @property
    def cookies(self):
        return self.session.cookies

    @cookies.setter
    def cookies(self, cookies):
        self.session.cookies = cookies

    def load_state(self, state=None):
        if not state:
            if self.auth_ident:
                if not self.state_storage:
                    raise ValueError('No state or state_storage to load')
                state = self.state_storage.get(self.auth_ident)

            if not state:
                if self.debug_level >= 2:
                    self.logger.debug('State not found: %s', self.auth_repr)
                return False

        for key, value in state.items():
            setattr(self, key, value)

        if 'is_authenticated' not in state and not getattr(self, 'is_authenticated'):
            self.is_authenticated = True

        self.logger.debug('State loaded: %s auth=%s', self.auth_repr,
                          self.is_authenticated)
        return True

    def init_state(self):
        if getattr(self, 'is_authenticated', None) is not False:
            self.is_authenticated = False  # TODO Do we need it here?

    def get_state(self):
        return {key: getattr(self, key) for key in self._state_attributes}

    def save_state(self):
        assert self.auth_ident, 'Could not save state without auth_ident'

        if self.state_storage:
            self.state_storage.set(self.auth_ident, self.get_state())
        else:
            raise AssertionError('State not saved: no state_storage: {}'
                                 .format(self.auth_repr))
        self.logger.info('State saved: %s', self.auth_repr)

    def authenticate(self):
        raise NotImplementedError()

    def _set_authenticated(self, auth_ident=None, mode_name='default', data=None):
        if auth_ident:
            self.auth_ident = auth_ident
        if not self.is_authenticated:
            self.is_authenticated = True
        self.logger.info('Authenticated %s %s: %s', self.auth_ident, mode_name, data or {})
        if self.state_storage:
            self.save_state()

    def auth_required_processor(self, exc):
        # returns True if auth problem resolved, False otherwise
        # By default we're just reauthenticating,
        # if there will be error it will raised upfront
        self.authenticate()
        return self.is_authenticated

    def error_processor(self, exc, error_processors=[]):
        [p(exc) for p in error_processors]

    def sleep(self, seconds, log_reason=None):
        if seconds < 0:
            raise ValueError('Can\'t sleep in backward time: {}'.format(seconds))
        elif not seconds:
            return
        if self.debug_level >= 4:
            self.logger.debug('Sleeping %s seconds. Reason: %s', seconds, log_reason)
        sleep(seconds)

    def download(self, url, output_path=None, chunk_size=1024):
        # https://stackoverflow.com/a/16696317/450103
        output_path = output_path or url.split('/')[-1]

        with self.session.get(url, stream=True) as resp:
            if resp.status_code != 200:
                raise self.HTTPError(resp, None, 200)
            with open(output_path, 'wb') as fh:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:  # filter out keep-alive new chunks
                        fh.write(chunk)
        return output_path

    def request(self, *args, **kwargs):
        """
        Wrapper method around `request` for exception processing, raised by ancestors.
        """

        ratelimit_retries, temporary_error_retries, ident_retries = 0, 0, {}

        while True:
            try:
                try:
                    return self._request(*args, **kwargs)
                except Exception as exc:
                    self.error_processor(exc)
                    raise

            except Retry as exc:
                ident_retries.setdefault(exc.retry_ident, 0)
                ident_retries[exc.retry_ident] += 1
                if ident_retries[exc.retry_ident] <= exc.retry_count:
                    self.logger.warning('Retry(%s) after calls(%s/%s) since(%s) on: %s',
                                        ident_retries[exc.retry_ident], self.calls_count,
                                        self.calls_elapsed_seconds, self.first_call_time,
                                        exc.retry_ident)
                    if exc.wait_seconds:
                        self.sleep(exc.wait_seconds,
                            log_reason='retry request: {}'.format(exc.retry_ident))
                else:
                    raise self.RetryExceeded(exc.result,
                        retry_ident=exc.retry_ident, retry_count=exc.retry_count)

            except RatelimitError as exc:
                ratelimit_retries += 1
                if ratelimit_retries <= self.ratelimit_retries:
                    self.logger.warning('Retry(%s) after calls(%s/%s) since(%s) on error: %r',
                                        ratelimit_retries, self.calls_count,
                                        self.calls_elapsed_seconds, self.first_call_time, exc)
                    self.sleep(exc.wait_seconds is not None and exc.wait_seconds or
                               self.ratelimit_wait_seconds,
                               log_reason='ratelimit wait')
                else:
                    if ratelimit_retries - 1:
                        raise self.RetryExceeded(exc, retry_count=ratelimit_retries - 1)
                    raise

            except TemporaryError as exc:
                temporary_error_retries += 1
                if temporary_error_retries <= self.temporary_error_retries:
                    self.logger.debug('Retry(%s) after calls(%s/%s) since(%s) on error: %r',
                                      temporary_error_retries, self.calls_count,
                                      self.calls_elapsed_seconds, self.first_call_time, exc)
                    self.sleep(exc.wait_seconds is not None and exc.wait_seconds or
                               self.temporary_error_wait_seconds,
                               log_reason='temporary error wait')
                else:
                    if temporary_error_retries - 1:
                        raise self.RetryExceeded(exc, retry_count=temporary_error_retries - 1)
                    raise

    def _request(self, *args, **kwargs):
        """
        Implement this method in ancestors, and call _send_request from it.
        raise TemporaryError and RatelimitError for proper response wrapping.
        """
        raise NotImplementedError()

    def _send_request(self, method, url, params=None, data=None, headers=None, json=None,
                      http_status=2, parse_json=False, error_processors=[],
                      allow_redirects=None):
        """
        Real request sending. Sleeping some time if need,
        setting calls first/last time and count, measuring request time,
        checking status, parsing json, running error_processors
        (for exception raise to be processed in self.request),
        """
        now = utcnow()
        if self.last_call_time:
            if self.request_wait_seconds:
                delta = (now - self.last_call_time).total_seconds()
                if delta < self.request_wait_seconds:
                    self.sleep(self.request_wait_seconds - delta,
                               log_reason='request wait')
        else:
            self.first_call_time = now
        self.last_call_time = utcnow()

        base_url = ''
        if not urlparse(url).scheme:
            base_url = self.base_url or ''
        if allow_redirects is None:
            allow_redirects = self.allow_redirects

        if self.debug_level >= 5:
            self.logger.debug(
                _color_em('REQUEST %s' % method) + ' ' + base_url + url + (' params=%s' % params) +
                '\n' + _color_em('REQUEST HEADERS:', back=colorama.Back.BLUE) + '\n' +
                pprint(headers, print_=False) +
                (('\n' + _color_em('REQUEST BODY:', back=colorama.Back.BLUE) + '\n' +
                pprint(data or json, print_=False)) if (data or json) else '')
            )

        try:
            kwargs = dict(params=params, data=data, json=json, headers=headers,
                          allow_redirects=allow_redirects, proxies=self.proxy,
                          verify=self.ssl_verify)
            if self.timeout is not None:
                # Allow session (ConfigurableSession for example) to handle timeout
                kwargs['timeout'] = self.timeout
            response = self.session.request(method, base_url + url, **kwargs)
        except Exception as exc:
            self.error_processor(exc, error_processors)
            raise
        finally:
            if self.request_wait_with_response_time:
                self.last_call_time = utcnow()

        if self.debug_level >= 5:
            self.logger.debug(
                _color_em('RESPONSE %s' % response.request.method, back=colorama.Back.GREEN) +
                colorama.Style.RESET_ALL + colorama.Style.BRIGHT + (' %s ' % response.status_code) +
                colorama.Style.RESET_ALL + response.url +
                '\n' + _color_em('RESPONSE HEADERS:', back=colorama.Back.GREEN) + '\n' +
                pprint(response.headers, print_=False) +
                '\n' + _color_em('RESPONSE BODY:', back=colorama.Back.GREEN) + '\n' +
                pprint(response.text, print_=False)
            )

        elapsed_seconds = response.elapsed.total_seconds()
        if elapsed_seconds > self.request_warn_elapsed_seconds:
            self.logger.warn('Request %s %s took %s seconds after calls(%s/%s) since(%s)',
                             response.request.method, response.request.url,
                             elapsed_seconds, self.calls_count, self.calls_elapsed_seconds,
                             self.first_call_time)
        self.calls_elapsed_seconds += elapsed_seconds
        self.calls_count += 1
        self.last_response = response  # NOTE: only for debug purposes!

        if (http_status and not check_http_status(response.status_code, http_status)):
            self.set_response_json_data(response, parse_json, raise_=False)
            exc = self.HTTPError(response, expected_status=http_status)
            self.error_processor(exc, error_processors)
            raise exc

        try:
            self.set_response_json_data(response, parse_json, raise_=True)
        except Exception as exc:
            exc = self.ClientError(response, 'JSON error: {}'.format(repr(exc)), exc)
            self.error_processor(exc, error_processors)
            raise exc

        return response

    def get(self, *args, **kwargs):
        return self.request('GET', *args, **kwargs)

    def post(self, *args, **kwargs):
        return self.request('POST', *args, **kwargs)

    def set_response_json_data(self, resp, data_path=None, data_attr='data', raise_=False):
        if (
            data_path or
            resp.headers.get('Content-Type', '').lower().split(';')[0] in JSON_CONTENT_TYPES
        ):
            try:
                data = maybe_attr_dict(resp.json())
                setattr(resp, data_attr, data)
                if isinstance(data_path, str):
                    try:
                        data = resolve_obj_path(data, data_path)
                        setattr(resp, data_attr, data)
                    except Exception as exc:
                        raise self.ClientError(resp, 'Could not resolve path %s: %r' %
                                               (data_path, exc))
            except Exception:
                if raise_:
                    raise

    def apply_response_schema(self, resp, schema, inherit=None, data_attr='data',
                              data_path=None, target_attr='data', **kwargs):
        data = getattr(resp, data_attr)
        data_path = data_path or getattr(schema, 'data_path', None)

        if data_path:
            try:
                data = resolve_obj_path(data, data_path)
            except Exception as exc:
                raise self.ClientError(resp, 'Could not resolve path %s: %r' % (data_path, exc))

        schema = maybe_create_response_schema(schema, inherit)
        schema.context['client'] = self
        schema.context['debug_level'] = self.debug_level
        schema.context['logger'] = self.logger
        schema.context['response'] = resp

        try:
            setattr(resp, target_attr, schema.load(data, **kwargs))
        except ValidationError as exc:
            setattr(resp, '{}_errors'.format(target_attr), exc.messages)
            raise self.ResponseValidationError(resp, schema=schema, errors=exc.messages)

    @classmethod
    def storage_factory(cls, prefix, storage_cls=None, storage_uri=None):
        """
        A little magic here, it's better to cache storage instances using class name and url,
        but we don't need it anyway.
        """

        key_prefix = '{}_{}_'.format(cls.__name__.upper(), prefix.upper())
        attr = '_{}_storage'.format(prefix)
        if not storage_cls and not storage_uri:
            if not hasattr(cls, attr):
                setattr(cls, attr, cls.storage_cls(cls.storage_uri, key_prefix))
            return getattr(cls, attr)
        return (storage_cls or cls.storage_cls)(storage_uri or cls.storage_uri, key_prefix)


def auth_required(func):
    @wraps(func)
    def wrapper(client, *args, **kwargs):
        if client.auto_authenticate and not client.is_authenticated:
            client.authenticate()
            return func(client, *args, **kwargs)
        else:
            try:
                return func(client, *args, **kwargs)
            except AuthRequired as exc:
                if client.auto_authenticate and client.auth_required_processor(exc):
                    return func(client, *args, **kwargs)
                client.is_authenticated = False
                raise
    return wrapper


def response_schema(schema, inherit=None, data_attr='data', data_path=None, **schema_kwargs):
    def decorator(func):
        @wraps(func)
        def wrapper(client, *args, **kwargs):
            resp = func(client, *args, **kwargs)
            if isinstance(resp, Response):
                client.apply_response_schema(resp, schema, inherit,
                                             data_attr, data_path, **schema_kwargs)
                return resp
            return resp
        return wrapper
    return decorator


def _match_attrs(obj, attrs):
    return all(resolve_obj_path(obj, attr, suppress_exc=True) == value
               for attr, value in attrs.items())


def _create_temporary_error_decorator(temporary_error_type):
    def temporary_error_decorator(exc_cls, exc_attrs={}, callback=None, wait_seconds=None):
        def create_error_processor(new_exc_cls):
            def error_processor(exc):
                if isinstance(exc, exc_cls):
                    if _match_attrs(exc, exc_attrs) and (not callback or callback(exc)):
                        raise new_exc_cls(exc.resp, 'Temporary error', wait_seconds=wait_seconds,
                                          original_exc=exc)
            return error_processor

        def decorator(func):
            @wraps(func)
            def wrapper(client, *args, **kwargs):
                error_processor = create_error_processor(getattr(client, temporary_error_type))
                if 'error_processors' in kwargs:
                    kwargs['error_processors'].append(error_processor)
                else:
                    kwargs['error_processors'] = [error_processor]
                return func(client, *args, **kwargs)
            return wrapper
        return decorator
    return temporary_error_decorator


ratelimit_error = _create_temporary_error_decorator('RatelimitError')
temporary_error = _create_temporary_error_decorator('TemporaryError')


def reraise(exc_cls, exc_attrs, callback):
    def decorator(func):
        @wraps(func)
        def wrapper(client, *args, **kwargs):
            try:
                return func(client, *args, **kwargs)
            except exc_cls as exc:
                if _match_attrs(exc, exc_attrs):
                    new_exc = callback(exc, *args, **kwargs)
                    if new_exc:
                        raise new_exc
                raise
        return wrapper
    return decorator
