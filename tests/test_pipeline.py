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


def test_content_match_doc_legacy(tmp_path):
    # 文件名无信息的旧版 .doc,靠内容里的姓名归档
    src = tmp_path / 'in'
    src.mkdir()
    payload = b'\x00junk' + '张三户籍情况'.encode('utf-16-le') + b'\x00'
    with zipfile.ZipFile(src / '某单位.zip', 'w') as z:
        z.writestr('回执007.doc', payload)
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER),
                      unit_mode='none', content_match=True)
    run(opts)
    assert (out / f'张三_{ID_A}' / '回执007.doc').exists()


def test_content_id_fallback(tmp_path):
    # 文件名无信息、人也不在名单,靠内容里的身份证号归档
    src = tmp_path / 'in'
    src.mkdir()
    with zipfile.ZipFile(src / 'u.zip', 'w') as z:
        z.writestr('data001.txt', f'查询对象证件号 {ID_B} 无违法记录')
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text('张三\n'),
                      unit_mode='none', content_match=True, auto_id=True)
    _logs, result = run(opts)
    assert (out / ID_B / 'data001.txt').exists()


def test_preview_manual_reassign(tmp_path):
    # 预览确认回调中修改 targets(模拟界面手改),执行结果应跟随新目标
    src = tmp_path / 'in'
    src.mkdir()
    with zipfile.ZipFile(src / 'u.zip', 'w') as z:
        z.writestr('无关文件.txt', 'x')
    out = tmp_path / 'out'
    opts = JobOptions([str(src)], str(out), Roster.from_text(ROSTER),
                      unit_mode='none', preview=True)

    def confirm(plan):
        for item in plan:
            if item.targets == ['未分类']:
                item.targets = [f'张三_{ID_A}']   # 人工改归张三
                item.via += '·手改'
        return True

    logs, result = [], {}
    run_job(opts, log=logs.append, progress=lambda *a: None,
            ask_password=lambda n, a: None,
            confirm_cb=confirm, done_cb=result.update)
    assert (out / f'张三_{ID_A}' / '无关文件.txt').exists()
    assert not (out / '未分类').exists()


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


def test_txt_files_always_classified_and_pw_file_excluded(tmp_path):
    """txt 往往就是反馈材料:无论是否当候选密码本,都要照常分类;
    只有专门指定的密码本文件不归档。"""
    for auto in (False, True):
        src = tmp_path / f'in{auto}'; src.mkdir()
        (src / '张三_出入境记录.txt').write_text('张三 2023 出境', encoding='utf-8')
        pw = src / '密码.txt'; pw.write_text('abc123\n', encoding='utf-8')
        out = tmp_path / f'out{auto}'
        run(JobOptions([str(src)], str(out), Roster.from_text('张三'),
                       auto_pw_txt=auto, pw_files=[str(pw)], intelligent=False))
        assert list(out.rglob('*张三_出入境记录.txt')), auto
        assert not list(out.rglob('密码.txt')), auto


def test_auto_pw_txt_default_off():
    assert JobOptions([], '.', Roster([])).auto_pw_txt is False


def test_file_without_name_uses_folder_or_archive_name(tmp_path):
    """只写「工商银行.xlsx」的文件:看所在文件夹 / 压缩包名找人;名字有多个人时不猜。"""
    src = tmp_path / 'in'; src.mkdir()
    with zipfile.ZipFile(src / '张三.zip', 'w') as z:          # 压缩包按人命名
        z.writestr('工商银行.xlsx', 'a')
    with zipfile.ZipFile(src / '第二批反馈.zip', 'w') as z:
        z.writestr('李四/建设银行.xlsx', 'b')                   # 包里按人分文件夹
        z.writestr('张三和李四/农业银行.xlsx', 'c')             # 两个人 → 不猜
    out = tmp_path / 'out'
    run(JobOptions([str(src)], str(out), Roster.from_text(ROSTER), intelligent=False,
                   unit_mode='category'))
    assert list((out / f'张三_{ID_A}').rglob('*工商银行.xlsx'))
    assert list((out / f'李四_{ID_B}').rglob('*建设银行.xlsx'))
    assert list((out / '未分类').rglob('*农业银行.xlsx'))


def _messy(tmp_path):
    """之前自己解压、乱放的案件材料。"""
    src = tmp_path / '案件材料'
    (src / '建设银行反馈' / '张三').mkdir(parents=True)
    (src / '张三' / '工商银行').mkdir(parents=True)
    (src / '某某查询结果').mkdir()
    (src / '建设银行反馈' / '张三' / '交易流水.xlsx').write_text('a', encoding='utf-8')
    (src / '张三' / '工商银行' / '查询结果.xlsx').write_text('b', encoding='utf-8')
    (src / '张三_出入境记录.txt').write_text('c', encoding='utf-8')
    (src / '某某查询结果' / '李四_户籍.txt').write_text('d', encoding='utf-8')
    (src / '张三' / 'Thumbs.db').write_text('x', encoding='utf-8')
    with zipfile.ZipFile(src / '某某查询结果.zip', 'w') as z:     # 已经解压过的包
        z.writestr('李四_户籍.txt', 'd')
    return src


def test_messy_extracted_folder_is_tidied_with_backup(tmp_path):
    src = _messy(tmp_path)
    out = src / '分类结果'                      # 默认输出目录就在所选文件夹里
    logs, res = run(JobOptions([str(src)], str(out), Roster.from_text('张三\n李四'),
                               intelligent=False, unit_mode='category', short_names=True))
    zs, ls = out / '张三', out / '李四'
    # 来源单位取自路径里的来源文件夹;人名可以在上层文件夹里
    assert (zs / '银行流水' / '【建设银行反馈】交易流水_张三.xlsx').is_file()
    assert (zs / '银行流水' / '【工商银行】查询结果_张三.xlsx').is_file()
    assert list((ls / '其他数据').glob('【某某查询结果】*户籍*'))
    assert not (out / '未分类').exists()
    # 原文件按原结构备份,原处只剩结果目录和备份
    bk = [d for d in src.iterdir() if d.name.startswith('原文件备份_')]
    assert len(bk) == 1 and res['backups'] == [str(bk[0])]
    assert (bk[0] / '建设银行反馈' / '张三' / '交易流水.xlsx').read_text(encoding='utf-8') == 'a'
    assert (bk[0] / '某某查询结果.zip').is_file()               # 已解压过的包不再解,收进备份
    assert (bk[0] / '张三' / 'Thumbs.db').is_file()
    assert sorted(x.name for x in src.iterdir()) == sorted(['分类结果', bk[0].name])
    # 结果目录在输入文件夹里:再跑一次不会把归档库自己当材料
    logs, res = run(JobOptions([str(src)], str(out), Roster.from_text('张三\n李四'),
                               intelligent=False, unit_mode='category', short_names=True))
    assert not (out / '未分类').exists()
    assert len(list(out.glob('分类日志_*.txt'))) >= 1 and not list(out.rglob('*【*】分类日志*'))


def test_archive_library_as_input_is_refused(tmp_path):
    src = _messy(tmp_path)
    out = tmp_path / 'out'
    run(JobOptions([str(src)], str(out), Roster.from_text('张三\n李四'), intelligent=False,
                   unit_mode='category'))
    logs, _ = run(JobOptions([str(out)], str(tmp_path / 'out2'), Roster.from_text('张三'),
                             intelligent=False, unit_mode='category'))
    assert any('是归档库' in m for m in logs)
    assert (out / '归档记录.jsonl').is_file()


def test_reimport_of_extracted_folder_matches_archive_import(tmp_path):
    """先导入过压缩包,后来又拿到它自己解压的文件夹:单位一致,认得出是同一批,不重复存放。"""
    a = tmp_path / 'a'; a.mkdir()
    with zipfile.ZipFile(a / '建设银行.zip', 'w') as z:
        z.writestr('张三_交易流水.xlsx', 'a')
    out = tmp_path / 'out'
    run(JobOptions([str(a)], str(out), Roster.from_text('张三'), intelligent=False,
                   unit_mode='category'))
    b = tmp_path / 'b'; (b / '建设银行').mkdir(parents=True)
    (b / '建设银行' / '张三_交易流水.xlsx').write_text('a', encoding='utf-8')
    _, res = run(JobOptions([str(b)], str(out), Roster.from_text('张三'), intelligent=False,
                            unit_mode='category'))
    assert res['reimport_skipped'] == 1
    assert len(list((out / '张三').rglob('*交易流水*'))) == 1
    assert not (b / '建设银行').exists()                    # 原处清空,备份里有
