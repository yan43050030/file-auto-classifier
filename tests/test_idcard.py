# -*- coding: utf-8 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac.idcard import (check_digit, valid_id18, valid_id15,
                        id15_to_18, find_ids)


def make_valid_18(d17='11010119900307851'):
    return d17 + check_digit(d17)


def test_valid_18():
    v = make_valid_18()
    assert valid_id18(v)


def test_wrong_check_digit_rejected():
    v = make_valid_18()
    wrong = '0' if v[-1] != '0' else '1'
    assert not valid_id18(v[:-1] + wrong)


def test_random_18_digits_rejected():
    # 旧版会把任意 18 位数字当身份证;新版必须拒绝
    assert not valid_id18('123456789012345678')


def test_bad_province_rejected():
    d17 = '99010119900307851'
    assert not valid_id18(d17 + check_digit(d17))


def test_bad_date_rejected():
    d17 = '11010119901347851'   # 13 月
    assert not valid_id18(d17 + check_digit(d17))


def test_valid_15():
    assert valid_id15('110101900307851')
    assert not valid_id15('990101900307851')


def test_15_to_18_roundtrip():
    v18 = id15_to_18('110101900307851')
    assert len(v18) == 18 and valid_id18(v18)
    assert v18.startswith('11010119900307851')


def test_find_ids_in_filename():
    v = make_valid_18()
    ids = find_ids(f'张三_{v}_报告.pdf')
    assert ids == [v]
    # 混入无效号不应被找出来
    assert find_ids('订单123456789012345678.txt') == []


def test_find_ids_x_suffix():
    d17 = '11010119900307853'
    v = d17 + check_digit(d17)
    if v.endswith('X'):
        assert find_ids(f'a{v.lower()}b.txt') == [v]
    else:  # 构造一个以 X 结尾的
        for i in range(10):
            d17 = f'1101011990030785{i}'
            v = d17 + check_digit(d17)
            if v.endswith('X'):
                assert find_ids(f'{v.lower()}.txt') == [v]
                return
