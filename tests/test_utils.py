from requests_client.utils import maybe_attr_dict


def test_maybe_attr_dict():
    assert maybe_attr_dict({'x': 1}).x == 1
    assert maybe_attr_dict({'x': (2, {'y': 3})}).x[1].y == 3
