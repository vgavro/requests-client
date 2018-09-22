try:
    from gevent import sleep
except ImportError:
    from time import sleep


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
