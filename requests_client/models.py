import logging

from .utils import SlotsReprMixin, pprint

try:
    from gevent import sleep
except ImportError:
    from time import sleep

logger = logging.getLogger(__name__)


def _maybe_deserialize(data, key, model):
    if key in data and isinstance(data[key], dict):
        data[key] = model(**data[key])


def _maybe_deserialize_list(data, key, model):
    if key in data and len(data[key]) and isinstance(data[key][0], dict):
        data[key] = [model(**obj) for obj in data[key]]


class Entity(SlotsReprMixin):
    __slots__ = ['_entity', '_meta']

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __contains__(self, key):
        return hasattr(self, key)

    def update(self, other):
        if isinstance(other, Entity):
            assert self.__class__ == other.__class__
            for k in self.__slots__:
                if hasattr(other, k):
                    setattr(self, k, getattr(other, k))
        elif isinstance(other, dict):
            for k, v in other.items():
                setattr(self, k, v)
        else:
            raise ValueError('{}.update failed: unknown type: {}'
                             .format(self.__class__.__name__, type(other)))

    def _pprint_entity(self):
        if hasattr(self, '_entity'):
            pprint(self._entity)

    @property
    def meta(self):
        if not hasattr(self, '_meta'):
            self._meta = {}
        return self._meta


class CursorFetchGeneratorError(Exception):
    pass


class CursorFetchGenerator:
    def __init__(self, cursor=None, has_more=None, fetch_callback=None, reverse_iterable=True,
                 initial=[], max_count=None, max_count_to_stop_fetch=None,
                 max_fetch_count=None, fetch_wait_seconds=0,
                 empty_fetch_retries=0, empty_fetch_wait_seconds=0, logger=None):

        self.cursor = cursor
        self._has_more = has_more
        self._fetch_callback = fetch_callback
        self.reverse_iterable = reverse_iterable
        if reverse_iterable:
            self._iterable = list(reversed(initial))
        else:
            self._iterable = list(initial)
        self.media_ids_last_resp = []
        self.max_count = (max_count is None) and float('inf') or max_count
        self.max_count_to_stop_fetch = ((max_count_to_stop_fetch is None) and
                                        float('inf') or max_count_to_stop_fetch)
        self.max_fetch_count = ((max_fetch_count is None) and float('inf') or
                                max_fetch_count)

        self.fetch_wait_seconds = fetch_wait_seconds
        self.empty_fetch_retries = empty_fetch_retries
        self.empty_fetch_wait_seconds = empty_fetch_wait_seconds
        self.logger = logger

        self._stop_on_next_fetch = False
        self.fetch_count = 0
        self.count = 0

    @property
    def has_more(self):
        if self._has_more is not None:
            return self._has_more
        if self.fetch_count:
            return bool(self.cursor)

    @has_more.setter
    def has_more(self, value):
        self._has_more = value

    def stop_on_next_fetch(self):
        self._stop_on_next_fetch = True

    def _fetch(self):
        if self._fetch_callback:
            return self._fetch_callback(self)
        raise NotImplementedError()

    def _fetch_next(self):
        if (self.max_fetch_count == 0 or self._stop_on_next_fetch or
           self.has_more is False):
            raise StopIteration()

        if self.fetch_count and self.fetch_wait_seconds:
            sleep(self.fetch_wait_seconds)
        self.fetch_count += 1
        if self.fetch_count >= self.max_fetch_count:
            self._stop_on_next_fetch = True

        result = self._fetch()
        if result is not None:
            if self.reverse_iterable:
                self._iterable = list(reversed(result))
            else:
                self._iterable = list(result)
        if self.logger:
            self.logger.debug('Fetched %d items count=%d fetch_count=%d',
                              len(self._iterable), self.count, self.fetch_count)

    def __iter__(self):
        return self

    # Python 3 compatibility
    def __next__(self):
        return self.next()

    def _next(self):
        if self.count >= self.max_count:
            raise StopIteration()
        self.count += 1
        if (self.count == self.max_count or
                self.count >= self.max_count_to_stop_fetch):
            self._stop_on_next_fetch = True
        return self._iterable.pop()

    def next(self):
        if self._iterable:
            return self._next()

        self._fetch_next()

        if not self._iterable and self.has_more:
            for i in range(self.empty_fetch_retries):
                if self.logger:
                    self.logger.debug('Retrying(%s) fetch on empty list', i + 1)
                if self.empty_fetch_wait_seconds:
                    sleep(self.empty_fetch_wait_seconds)
                self._fetch_next()
                if self._iterable:
                    break
            else:
                msg = 'Cursor has more, but empty list returned'
                if self.empty_fetch_retries:
                    msg += ('(after {} retries with {} sleep)'
                            .format(self.empty_fetch_retries, self.empty_fetch_wait_seconds))
                raise CursorFetchGeneratorError(msg)

        if not self._iterable:
            raise StopIteration()
        return self._next()
