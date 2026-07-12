# -*- coding: utf-8 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac.password import PasswordManager, parse_password_lines


def test_parse_formats():
    text = ('# 注释行\n'
            'plainpwd\n'
            '公安局反馈.zip: abc123\n'
            '税务=xyz\n'
            '银行反馈.rar  tail9\n')
    c = parse_password_lines(text)
    assert 'plainpwd' in c and 'abc123' in c and 'xyz' in c and 'tail9' in c
    assert not any(x.startswith('#') for x in c)


def test_verified_first():
    pm = PasswordManager(lambda n, a: None, seeds=['s1', 's2'])
    pm.add('winner')
    assert pm.candidates()[0] == 'winner'
    assert set(pm.candidates()) == {'winner', 's1', 's2'}
