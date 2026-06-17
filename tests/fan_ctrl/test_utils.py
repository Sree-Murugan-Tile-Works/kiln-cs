import pytest
from utils import AttrDict


def test_attribute_read():
    d = AttrDict({"x": 1, "y": 2})
    assert d.x == 1
    assert d.y == 2


def test_attribute_write():
    d = AttrDict()
    d.foo = "bar"
    assert d["foo"] == "bar"


def test_missing_attribute_raises():
    d = AttrDict()
    with pytest.raises(AttributeError):
        _ = d.missing


def test_delete_attribute():
    d = AttrDict({"k": 99})
    del d.k
    assert "k" not in d


def test_delete_missing_raises():
    d = AttrDict()
    with pytest.raises(AttributeError):
        del d.nonexistent


def test_internal_data_attr_not_broken():
    # 'data' is UserDict's internal dict — must not be stored in self.data['data']
    d = AttrDict({"data": "payload"})
    assert d["data"] == "payload"
    assert isinstance(d.data, dict)  # UserDict.data is the backing dict


def test_dict_and_attr_access_are_equivalent():
    d = AttrDict({"a": 10})
    assert d["a"] == d.a
