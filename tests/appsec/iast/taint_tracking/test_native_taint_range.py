# -*- coding: utf-8 -*-
from ast import literal_eval
import random
import sys

import pytest

from ddtrace.appsec._iast import oce


try:
    from ddtrace.appsec._iast._taint_tracking import OriginType
    from ddtrace.appsec._iast._taint_tracking import Source
    from ddtrace.appsec._iast._taint_tracking import TaintRange
    from ddtrace.appsec._iast._taint_tracking import are_all_text_all_ranges
    from ddtrace.appsec._iast._taint_tracking import create_context
    from ddtrace.appsec._iast._taint_tracking import debug_taint_map
    from ddtrace.appsec._iast._taint_tracking import get_range_by_hash
    from ddtrace.appsec._iast._taint_tracking import get_ranges
    from ddtrace.appsec._iast._taint_tracking import is_notinterned_notfasttainted_unicode
    from ddtrace.appsec._iast._taint_tracking import num_objects_tainted
    from ddtrace.appsec._iast._taint_tracking import reset_context
    from ddtrace.appsec._iast._taint_tracking import set_fast_tainted_if_notinterned_unicode
    from ddtrace.appsec._iast._taint_tracking import set_ranges
    from ddtrace.appsec._iast._taint_tracking import shift_taint_range
    from ddtrace.appsec._iast._taint_tracking import shift_taint_ranges
    from ddtrace.appsec._iast._taint_tracking import taint_pyobject
    from ddtrace.appsec._iast._taint_tracking.aspects import add_aspect
    from ddtrace.appsec._iast._taint_tracking.aspects import bytearray_extend_aspect as extend_aspect
    from ddtrace.appsec._iast._taint_tracking.aspects import format_aspect
    from ddtrace.appsec._iast._taint_tracking.aspects import join_aspect
except (ImportError, AttributeError):
    pytest.skip("IAST not supported for this Python version", allow_module_level=True)


def setup():
    oce._enabled = True


def test_source_origin_refcount():
    s1 = Source(name="name", value="val", origin=OriginType.COOKIE)
    assert sys.getrefcount(s1) - 1 == 1  # getrefcount takes 1 while counting
    s2 = s1
    assert sys.getrefcount(s1) - 1 == 2
    s3 = s1
    assert sys.getrefcount(s1) - 1 == 3
    del s2
    assert sys.getrefcount(s1) - 1 == 2
    # TaintRange does not increase refcount but should keep it alive
    tr_sub = TaintRange(0, 1, s1)
    assert sys.getrefcount(s1) - 1 == 2
    del s1
    assert sys.getrefcount(s3) - 1 == 1
    assert sys.getrefcount(tr_sub.source) - 1 == 1
    del s3
    assert sys.getrefcount(tr_sub.source) - 1 == 1
    _ = TaintRange(1, 2, tr_sub.source)
    assert sys.getrefcount(tr_sub.source) - 1 == 1


_SOURCE1 = Source(name="name", value="value", origin=OriginType.COOKIE)
_SOURCE2 = Source(name="name2", value="value2", origin=OriginType.BODY)

_RANGE1 = TaintRange(0, 2, _SOURCE1)
_RANGE2 = TaintRange(1, 3, _SOURCE2)


def test_unicode_fast_tainting():
    for i in range(5000):
        s = "somestr" * random.randint(4 * i + 7, 4 * i + 9)
        s_check = "somestr" * (4 * i + 10)
        # Check that s is not interned since fast tainting only works on non-interned strings
        assert s is not s_check
        assert is_notinterned_notfasttainted_unicode(s), "%s,%s" % (i, len(s) // 7)

        set_fast_tainted_if_notinterned_unicode(s)
        assert not is_notinterned_notfasttainted_unicode(s)

        b = b"foobar" * 4000
        assert not is_notinterned_notfasttainted_unicode(b)
        set_fast_tainted_if_notinterned_unicode(b)
        assert not is_notinterned_notfasttainted_unicode(b)

        ba = bytearray(b"sfdsdfsdf" * 4000)
        assert not is_notinterned_notfasttainted_unicode(ba)
        set_fast_tainted_if_notinterned_unicode(ba)
        assert not is_notinterned_notfasttainted_unicode(ba)

        c = 12345
        assert not is_notinterned_notfasttainted_unicode(c)
        set_fast_tainted_if_notinterned_unicode(c)
        assert not is_notinterned_notfasttainted_unicode(c)


def test_collisions_str():
    not_tainted = []
    tainted = []
    mixed_tainted_ids = []
    mixed_nottainted = []
    mixed_tainted_and_nottainted = []

    # Generate untainted strings
    for i in range(10):
        not_tainted.append("N%04d" % i)

    # Generate tainted strings
    for i in range(10000):
        t = taint_pyobject(
            "T%04d" % i, source_name="request_body", source_value="hello", source_origin=OriginType.PARAMETER
        )
        tainted.append(t)

    for t in tainted:
        assert len(get_ranges(t)) > 0

    for n in not_tainted:
        assert get_ranges(n) == []

    # Do join and format operations mixing tainted and untainted strings, store in mixed_tainted_and_nottainted
    for _ in range(10000):
        n1 = add_aspect(add_aspect("_", random.choice(not_tainted)), "{}_")

        t2 = random.choice(tainted)

        n3 = random.choice(not_tainted)

        t4 = random.choice(tainted)
        mixed_tainted_ids.append(id(t4))

        t5 = format_aspect(n1.format, n1, t4)
        mixed_tainted_ids.append(id(t5))

        t6 = join_aspect(t5.join, t5, [t2, n3])
        mixed_tainted_ids.append(id(t6))

    for t in mixed_tainted_and_nottainted:
        assert len(get_ranges(t)) == 2

    # Do join and format operations with only untainted strings, store in mixed_nottainted
    for i in range(10):
        n1 = add_aspect("===", not_tainted[i])

        n2 = random.choice(not_tainted)

        n3 = random.choice(not_tainted)

        n4 = random.choice(not_tainted)

        n5 = format_aspect(n1.format, n1, [n4])

        n6 = join_aspect(n5.join, n5, [n2, n3])

        mixed_nottainted.append(n6)

    for n in mixed_nottainted:
        assert len(get_ranges(n)) == 0, f"id {id(n)} in {(id(n) in mixed_tainted_ids)}"

    taint_map = literal_eval(debug_taint_map())
    assert taint_map != []
    for i in taint_map:
        assert abs(i["Value"]["Hash"]) > 1000


def test_collisions_bytes():
    not_tainted = []
    tainted = []
    mixed_tainted_ids = []
    mixed_nottainted = []
    mixed_tainted_and_nottainted = []

    # Generate untainted strings
    for i in range(10):
        not_tainted.append(b"N%04d" % i)

    # Generate tainted strings
    for i in range(10000):
        t = taint_pyobject(
            b"T%04d" % i, source_name="request_body", source_value="hello", source_origin=OriginType.PARAMETER
        )
        tainted.append(t)

    for t in tainted:
        assert len(get_ranges(t)) > 0

    for n in not_tainted:
        assert get_ranges(n) == []

    # Do join operations mixing tainted and untainted bytes, store in mixed_tainted_and_nottainted
    for _ in range(10000):
        n1 = add_aspect(add_aspect(b"_", random.choice(not_tainted)), b"{}_")

        t2 = random.choice(tainted)

        n3 = random.choice(not_tainted)

        t4 = random.choice(tainted)
        mixed_tainted_ids.append(id(t4))

        t5 = join_aspect(n1.join, t2, [n1, t4])
        mixed_tainted_ids.append(id(t5))

        t6 = join_aspect(t5.join, t5, [t2, n3])
        mixed_tainted_ids.append(id(t6))

    for t in mixed_tainted_and_nottainted:
        assert len(get_ranges(t)) == 2

    # Do join operations with only untainted bytes, store in mixed_nottainted
    for i in range(10):
        n1 = add_aspect(b"===", not_tainted[i])

        n2 = random.choice(not_tainted)

        n3 = random.choice(not_tainted)

        n4 = random.choice(not_tainted)

        n5 = join_aspect(n1.join, n1, [n2, n4])

        n6 = join_aspect(n5.join, n5, [n2, n3])

        mixed_nottainted.append(n6)

    for n in mixed_nottainted:
        assert len(get_ranges(n)) == 0, f"id {id(n)} in {(id(n) in mixed_tainted_ids)}"

    taint_map = literal_eval(debug_taint_map())
    assert taint_map != []
    for i in taint_map:
        assert abs(i["Value"]["Hash"]) > 1000


def test_collisions_bytearray():
    not_tainted = []
    tainted = []
    mixed_tainted_ids = []
    mixed_nottainted = []
    mixed_tainted_and_nottainted = []

    # Generate untainted strings
    for i in range(10):
        not_tainted.append(b"N%04d" % i)

    # Generate tainted strings
    for i in range(10000):
        t = taint_pyobject(
            b"T%04d" % i,
            source_name="request_body",
            source_value="hello",
            source_origin=OriginType.PARAMETER,
        )
        tainted.append(t)

    for t in tainted:
        assert len(get_ranges(t)) > 0

    for n in not_tainted:
        assert get_ranges(n) == []

    # Do extend operations mixing tainted and untainted bytearrays, store in mixed_tainted_and_nottainted
    for _ in range(10000):
        n1 = bytearray(add_aspect(b"_", random.choice(not_tainted)))
        extend_aspect(bytearray(b"").extend, n1, b"{}_")

        n3 = random.choice(not_tainted)

        t4 = random.choice(tainted)

        t5 = bytearray(add_aspect(b"_", random.choice(not_tainted)))
        extend_aspect(bytearray(b"").extend, t5, t4)
        mixed_tainted_ids.append(id(t5))

        t6 = bytearray(add_aspect(b"_", random.choice(not_tainted)))
        extend_aspect(bytearray(b"").extend, t6, n3)
        mixed_tainted_ids.append(id(t6))

    for t in mixed_tainted_and_nottainted:
        assert len(get_ranges(t)) == 2

    # Do extend operations with only untainted bytearrays, store in mixed_nottainted
    for i in range(10):
        n1 = bytearray(not_tainted[i])
        extend_aspect(bytearray(b"").extend, n1, b"===")
        mixed_nottainted.append(n1)

        n2 = random.choice(not_tainted)

        n4 = bytearray(random.choice(not_tainted))

        n5 = bytearray(not_tainted[i])
        extend_aspect(bytearray(b"").extend, n5, n4)
        mixed_nottainted.append(n5)

        n6 = bytearray(not_tainted[i])
        extend_aspect(bytearray(b"").extend, n6, n2)

        mixed_nottainted.append(n6)

    for n in mixed_nottainted:
        assert len(get_ranges(n)) == 0, f"id {id(n)} in {(id(n) in mixed_tainted_ids)}"

    taint_map = literal_eval(debug_taint_map())
    assert taint_map != []
    for i in taint_map:
        assert abs(i["Value"]["Hash"]) > 1000


def test_set_get_ranges_str():
    s1 = "abcde😁"
    s2 = "defg"
    set_ranges(s1, [_RANGE1, _RANGE2])
    assert get_ranges(s1) == [_RANGE1, _RANGE2]
    assert not get_ranges(s2)


def test_set_get_ranges_other():
    s1 = 12345
    s2 = None
    set_ranges(s1, [_RANGE1, _RANGE2])
    set_ranges(s2, [_RANGE1, _RANGE2])
    assert not get_ranges(s1)
    assert not get_ranges(s2)


def test_set_get_ranges_bytes():
    b1 = b"ABCDE"
    b2 = b"DEFG"
    set_ranges(b1, [_RANGE2, _RANGE1])
    assert get_ranges(b1) == [_RANGE2, _RANGE1]
    assert not get_ranges(b2) == [_RANGE2, _RANGE1]


def test_set_get_ranges_bytearray():
    b1 = bytearray(b"abcdef")
    b2 = bytearray(b"abcdef")
    set_ranges(b1, [_RANGE1, _RANGE2])
    assert get_ranges(b1) == [_RANGE1, _RANGE2]
    assert not get_ranges(b2) == [_RANGE1, _RANGE2]


def test_shift_taint_ranges():
    r1 = TaintRange(0, 2, _SOURCE1)
    r1_shifted = shift_taint_range(r1, 2)
    assert r1_shifted == TaintRange(2, 2, _SOURCE1)
    assert r1_shifted != r1

    r2 = TaintRange(1, 3, _SOURCE1)
    r3 = TaintRange(4, 6, _SOURCE2)
    r2_shifted, r3_shifted = shift_taint_ranges([r2, r3], 2)
    assert r2_shifted == TaintRange(3, 3, _SOURCE1)
    assert r3_shifted == TaintRange(6, 6, _SOURCE1)


def test_are_all_text_all_ranges():
    s1 = "abcdef"
    s2 = "ghijk"
    s3 = "xyzv"
    num = 123456
    source3 = Source(name="name3", value="value3", origin=OriginType.COOKIE)
    source4 = Source(name="name4", value="value4", origin=OriginType.COOKIE)
    range3 = TaintRange(2, 3, source3)
    range4 = TaintRange(4, 5, source4)
    set_ranges(s1, [_RANGE1, _RANGE2])
    set_ranges(s2, [range3, _RANGE2])
    set_ranges(s3, [range4, _RANGE1])
    all_ranges, candidate_ranges = are_all_text_all_ranges(s1, (s2, s3, num))
    # Ranges are inserted at the start except the candidate ones that are appended
    assert all_ranges == [range3, _RANGE2, range4, _RANGE1, _RANGE1, _RANGE2]
    assert candidate_ranges == [_RANGE1, _RANGE2]


def test_get_range_by_hash():
    hash_r1 = hash(_RANGE1)
    assert hash_r1 == _RANGE1.__hash__()
    hash_r2_call = hash(_RANGE2)
    hash_r2_method = _RANGE2.__hash__()
    assert hash_r2_call == hash_r2_method
    assert hash_r1 != hash_r2_call
    assert get_range_by_hash(hash_r1, [_RANGE1, _RANGE2]) == _RANGE1
    assert get_range_by_hash(hash_r2_call, [_RANGE1, _RANGE2]) == _RANGE2


def test_num_objects_tainted():
    reset_context()
    create_context()
    a_1 = "abc123_len1"
    a_2 = "def456__len2"
    a_3 = "ghi789___len3"
    assert num_objects_tainted() == 0
    a_1 = taint_pyobject(
        a_1,
        source_name="test_num_objects_tainted",
        source_value=a_1,
        source_origin=OriginType.PARAMETER,
    )
    a_2 = taint_pyobject(
        a_2,
        source_name="test_num_objects_tainted",
        source_value=a_2,
        source_origin=OriginType.PARAMETER,
    )
    a_3 = taint_pyobject(
        a_3,
        source_name="test_num_objects_tainted",
        source_value=a_3,
        source_origin=OriginType.PARAMETER,
    )
    assert num_objects_tainted() == 3


def test_reset_objects():
    reset_context()
    create_context()

    a_1 = "abc123"
    a_2 = "def456"
    assert num_objects_tainted() == 0
    a_1 = taint_pyobject(
        a_1,
        source_name="test_num_objects_tainted",
        source_value=a_1,
        source_origin=OriginType.PARAMETER,
    )
    assert num_objects_tainted() == 1

    reset_context()
    create_context()

    a_2 = taint_pyobject(
        a_2,
        source_name="test_num_objects_tainted",
        source_value=a_2,
        source_origin=OriginType.PARAMETER,
    )
    assert num_objects_tainted() == 1

    reset_context()
    create_context()

    assert num_objects_tainted() == 0
