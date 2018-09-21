import os
import pickle

try:
    import redis
except ImportError:
    redis = None


class BaseStorage(object):
    """
    Class to store client state.
    storage_type "state" - maps account_id to client state
    storage_type "account_id" - maps username to account_id
    """
    def __init__(self, uri, storage_type):
        self.uri, self.storage_type = uri, storage_type

    def _build_key(self, key):
        return '{}{}'.format(self.storage_type, key)

    def get(self, key):
        raise NotImplementedError()

    def set(self, key, value):
        raise NotImplementedError()


class FileStorage(BaseStorage):
    def build_filename(self, key):
        return os.path.join(self.uri, self._build_key(key))

    def get(self, key):
        filename = self.build_filename(key)
        if os.path.exists(filename):
            with open(filename, 'rb') as fh:
                return pickle.load(fh)
        return None

    def set(self, key, value):
        if not os.path.isdir(self.uri):
            os.makedirs(self.uri)

        with open(self.build_filename(key), 'wb') as fh:
            pickle.dump(value, fh)


class RedisStorage(BaseStorage):
    _redis_map = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert redis, '"redis" module not found'
        if self.uri not in self._redis_map:
            self._redis_map[self.uri] = redis.StrictRedis.from_url(self.uri)
        self._redis = self._redis_map[self.uri]

    def get(self, key):
        value = self._redis.get(self._build_key(key))
        if value is not None:
            return pickle.loads(value)
        return None

    def set(self, key, value):
        self._redis.set(self._build_key(key), pickle.dumps(value))
