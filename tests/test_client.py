import os

import pytest
import requests_mock

from requests_client.client import BaseClient, ratelimit_error, temporary_error
from requests_client.exceptions import (ClientError, HTTPError, RatelimitError,
                                        TemporaryError, RetryExceeded)


class Client(BaseClient):
    base_url = 'mock://test/'
    auth_ident = None

    _request = BaseClient._send_request


@pytest.fixture
def req_mocker():
    with requests_mock.Mocker() as mocker:
        yield mocker


def test_request(req_mocker):
    client = Client()

    req_mocker.get('mock://test/path', text='{"hello": "world"}')
    r1 = client.get('path', parse_json=True)
    assert r1.data.hello == 'world'

    req_mocker.post('mock://test/path', text='{"hello": "world"}')
    r2 = client.post('path', parse_json=True)
    assert r2.data.hello == 'world'

    assert client.first_call_time
    assert client.last_call_time
    if os.name == 'nt':
        # In some times in Windows 10 we get same last_call_time as first_call_time
        assert client.last_call_time >= client.first_call_time
    else:
        assert client.last_call_time > client.first_call_time
    assert client.calls_count == 2
    assert client.calls_elapsed_seconds == sum([r.elapsed.total_seconds()
                                                for r in [r1, r2]])
    assert client.last_response == r2


def test_json_decode_error(req_mocker):
    client = Client()

    req_mocker.get('mock://test/path', text='unparsable')
    with pytest.raises(ClientError) as exc:
        client.get('path', parse_json=True)
    assert 'JSONDecodeError' in repr(exc.value)


def test_http_status_error(req_mocker):
    client = Client()

    req_mocker.get('mock://test/path', status_code=400, text='{"hello": "world"}')
    with pytest.raises(HTTPError) as exc:
        r = client.get('path', parse_json=True)
    assert exc.value.status == 400
    assert exc.value.response.status_code == 400
    # test json is parsed on response
    assert exc.value.response.data.hello == 'world'

    req_mocker.get('mock://test/path', status_code=200, text='unparsable')
    with pytest.raises(HTTPError) as exc:
        r = client.get('path', parse_json=True, http_status=400)
    assert exc.value.status == 200
    # json can't be parsed, but we have HTTPError instead of json decode error
    assert not hasattr(exc.value.response, 'data')

    # Test no exception raised
    req_mocker.get('mock://test/path', status_code=400, text='{"hello": "world"}')
    r = client.get('path', http_status=[200, 400])
    assert r.status_code == 400
    req_mocker.get('mock://test/path', status_code=200, text='{"hello": "world"}')
    r = client.get('path', http_status=[200, 400])
    assert r.status_code == 200


@pytest.mark.parametrize('error_type', [RatelimitError, TemporaryError])
def test_temporary_error(error_type, req_mocker):
    if error_type == RatelimitError:
        temporary_error_decorator = ratelimit_error
        client_kwargs = dict(ratelimit_wait_seconds=0.5, ratelimit_retries=2)
    else:
        temporary_error_decorator = temporary_error
        client_kwargs = dict(temporary_error_wait_seconds=0.5, temporary_error_retries=2)

    class _Client(Client):
        @temporary_error_decorator(HTTPError, {'status': 400, 'response.data.match1': True})
        @temporary_error_decorator(HTTPError, {'status': 400, 'response.data.match2': 'true'})
        @temporary_error_decorator(HTTPError, {'status': 400, 'response.data.match3': True},
                                   wait_seconds=1.5)
        def test(self, **kwargs):
            self.get('path', parse_json=True, **kwargs)

        _sleeped = 0

        def sleep(self, seconds, *args, **kwargs):
            self._sleeped += seconds

    client = _Client(**client_kwargs)

    with pytest.raises(HTTPError):  # doesn't match
        req_mocker.get('mock://test/path', status_code=401)
        client.test()
        assert client._sleeped == 0

    with pytest.raises(HTTPError):  # doesn't match
        req_mocker.get('mock://test/path', status_code=400, json={'match1': False})
        client.test()
        assert client._sleeped == 0

    with pytest.raises(RetryExceeded):  # match
        req_mocker.get('mock://test/path', status_code=400, json={'match1': True})
        client.test()
        assert client._sleeped == 1

    with pytest.raises(RetryExceeded):  # match
        req_mocker.get('mock://test/path', status_code=400, json={'match2': 'true'})
        client.test()
        assert client._sleeped == 2

    with pytest.raises(RetryExceeded):
        req_mocker.get('mock://test/path', status_code=400, json={'match3': True})
        client.test()
        assert client._sleeped == 5
