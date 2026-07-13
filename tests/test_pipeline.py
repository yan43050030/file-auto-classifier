# -*- coding: utf-8 -*-
"""端到端:模拟"多个单位反馈多个人的材料"场景。"""
import os
import sys
import zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fac.idcard import check_digit
from fac.roster import Roster
from fac.pipeline import JobOptions, run_job

ID_A = '11010119900307851' + check_digit('11010119900307851')
ID_B = '32010219851212001' + check_digit('32010219851212001')

ROSTER = f'张三,{ID_A}\n李四,{ID_B},李小四\n'


def run(opts):
    logs, result = [], {}
    run_job(opts,
            log=logs.append,
            progress=lambda *a: None,
            ask_password=lambda n, a: None,
            done_cb=result.update)
    return logs, result


def make_unit_zips(tmp_path):
    """公安局:按姓名命名;银行:按证号命名 → 同一人应归同一文件夹。"""
    src = tmp_path / '收件'
    src.mkdir()
    z1 = src / '公安局反馈.zip'
    with zipfile.ZipFile(z1, 'w') as z:
        z.writestr('张三_户籍.txt', 'a')
        z.writestr('李四_户籍.txt', 'b')
        z.writestr('无关文件.txt', 'c')
    z2 = src / '银行反馈.zip'
    with zipfile.ZipFile(z2, 'w') as z:
        z.writestr(f'{ID_A}_流水.txt', 'd')
        z.writestr('李小四_流水.txt', 'e')
    return src


def test_end_to_end_unit_subfolder(tmp_path):
    src = make_unit_zips(tmp_path)
    out = tmp_path / '结果'
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER),
                      unit_mode='subfolder')
    logs, result = run(opts)
    assert result['files'] == 5 and not result['cancelled']
    # 张三:姓名命中(公安局) + 证号命中(银行)归同一文件夹
    assert (out / f'张三_{ID_A}' / '公安局反馈' / '张三_户籍.txt').exists()
    assert (out / f'张三_{ID_A}' / '银行反馈' / f'{ID_A}_流水.txt').exists()
    # 李四:曾用名命中
    assert (out / f'李四_{ID_B}' / '银行反馈' / '李小四_流水.txt').exists()
    assert (out / '未分类' / '公安局反馈' / '无关文件.txt').exists()
    # 反馈核对表已生成
    assert result['reports'] and any(r.endswith('.csv') for r in result['reports'])
    csv_text = open(result['reports'][0], encoding='utf-8-sig').read()
    assert '公安局反馈' in csv_text and '银行反馈' in csv_text and f'张三_{ID_A}' in csv_text
    # 日志文件已写入
    assert any(f.startswith('分类日志') for f in os.listdir(out))
    # 临时目录已清理
    assert not any(f.startswith('.分类tmp') for f in os.listdir(out))


def test_unit_prefix_mode(tmp_path):
    src = make_unit_zips(tmp_path)
    out = tmp_path / '结果'
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER),
                      unit_mode='prefix')
    run(opts)
    assert (out / f'张三_{ID_A}' / '【公安局反馈】张三_户籍.txt').exists()


def test_unit_none_mode(tmp_path):
    src = make_unit_zips(tmp_path)
    out = tmp_path / '结果'
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER),
                      unit_mode='none')
    run(opts)
    assert (out / f'张三_{ID_A}' / '张三_户籍.txt').exists()


def test_auto_id_fallback(tmp_path):
    src = tmp_path / 'in'
    src.mkdir()
    with zipfile.ZipFile(src / 'u.zip', 'w') as z:
        z.writestr(f'{ID_B}_不在名单.txt', 'x')
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text('张三\n'),
                      auto_id=True, unit_mode='none')
    run(opts)
    assert (out / ID_B / f'{ID_B}_不在名单.txt').exists()


def test_dedup(tmp_path):
    src = tmp_path / 'in'
    src.mkdir()
    with zipfile.ZipFile(src / '单位A.zip', 'w') as z:
        z.writestr('张三_同一份材料.txt', 'IDENTICAL')
    with zipfile.ZipFile(src / '单位B.zip', 'w') as z:
        z.writestr('张三_同一份材料.txt', 'IDENTICAL')
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text('张三\n'),
                      unit_mode='subfolder', dedup=True)
    _logs, result = run(opts)
    assert result['dedup_skipped'] == 1
    total = sum(len(fs) for _r, _d, fs in os.walk(out / '张三'))
    assert total == 1


def test_preview_cancel_leaves_output_clean(tmp_path):
    src = make_unit_zips(tmp_path)
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER),
                      preview=True)
    seen = {}

    def confirm(plan):
        seen['n'] = len(plan)
        return False    # 用户点了取消

    logs, result = [], {}
    run_job(opts, log=logs.append, progress=lambda *a: None,
            ask_password=lambda n, a: None,
            confirm_cb=confirm, done_cb=result.update)
    assert seen['n'] == 5
    assert result['cancelled']
    # 除日志外,输出目录不应有归档结果
    entries = [f for f in os.listdir(out) if not f.startswith('分类日志')]
    assert entries == []


def test_content_match_xlsx(tmp_path):
    openpyxl = pytest.importorskip('openpyxl')
    src = tmp_path / 'in'
    src.mkdir()
    wb = openpyxl.Workbook()
    wb.active.append(['查询对象', '张三', ID_A])
    xf = tmp_path / '回执001.xlsx'
    wb.save(xf)
    with zipfile.ZipFile(src / '某单位.zip', 'w') as z:
        z.write(xf, '回执001.xlsx')
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER),
                      unit_mode='none', content_match=True)
    run(opts)
    assert (out / f'张三_{ID_A}' / '回执001.xlsx').exists()
    assert not (out / '未分类').exists()


def test_split_excel(tmp_path):
    openpyxl = pytest.importorskip('openpyxl')
    src = tmp_path / 'in'
    src.mkdir()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['姓名', '账号', '余额'])
    ws.append(['张三', '6222001', 100])
    ws.append(['李四', '6222002', 200])
    ws.append(['张三', '6222003', 300])
    xf = tmp_path / '开户情况.xlsx'
    wb.save(xf)
    with zipfile.ZipFile(src / '银行.zip', 'w') as z:
        z.write(xf, '开户情况.xlsx')
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER),
                      unit_mode='none', content_match=True, split_excel=True)
    run(opts)
    z_files = list((out / f'张三_{ID_A}').glob('*.xlsx'))
    l_files = list((out / f'李四_{ID_B}').glob('*.xlsx'))
    assert len(z_files) == 1 and len(l_files) == 1
    # 张三的拆分文件应包含表头 + 2 行数据
    wb2 = openpyxl.load_workbook(z_files[0])
    rows = list(wb2.active.iter_rows(values_only=True))
    assert len(rows) == 3 and rows[0][0] == '姓名'
    assert all(r[0] == '张三' for r in rows[1:])
    # 原表保留在「原始反馈」
    assert list((out / '原始反馈').rglob('开户情况.xlsx'))


def test_failed_archive_stashed(tmp_path):
    src = tmp_path / 'in'
    src.mkdir()
    (src / '坏包.zip').write_bytes(b'garbage')
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text('张三\n'))
    _logs, result = run(opts)
    assert result['failed'] == 1
    assert (out / '解压失败' / '坏包.zip').exists()


def test_copy_to_each(tmp_path):
    src = tmp_path / 'in'
    src.mkdir()
    with zipfile.ZipFile(src / 'u.zip', 'w') as z:
        z.writestr('张三与李四对比.txt', 'x')
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER),
                      unit_mode='none', copy_to_each=True)
    run(opts)
    assert (out / f'张三_{ID_A}' / '张三与李四对比.txt').exists()
    assert (out / f'李四_{ID_B}' / '张三与李四对比.txt').exists()


def test_cancel_event(tmp_path):
    import threading
    src = make_unit_zips(tmp_path)
    out = tmp_path / 'out'
    ev = threading.Event()
    ev.set()      # 一开始就已取消
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER))
    logs, result = [], {}
    run_job(opts, log=logs.append, progress=lambda *a: None,
            ask_password=lambda n, a: None,
            cancel_event=ev, done_cb=result.update)
    assert result['cancelled']
