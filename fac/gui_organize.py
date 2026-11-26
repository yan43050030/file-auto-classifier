# -*- coding: utf-8 -*-
"""「文件整理」模式相关的界面逻辑(整理、查历史、一键清理、撤销)。

以 Mixin 形式并入 MainWindow,依赖主窗口提供的控件与 _log / _begin_job /
_ui_call / _on_done 等公共方法;从 gui.py 拆出以便维护。
"""

import os
import threading

from PySide6.QtWidgets import (
    QMessageBox, QInputDialog, QDialog, QVBoxLayout, QTreeWidget,
    QTreeWidgetItem, QDialogButtonBox,
)

from .organize import OrganizeOptions, run_organize
from . import undo as undo_mod
from . import config as conf


class OrganizeMixin:
    def _organize_opts(self, out):
        layout = (self.cmb_layout.currentData()
                  if self.cmb_layout.currentIndex() >= 0 and
                  '—' in self.cmb_layout.currentText() else None)
        if not layout:
            # 用户手动编辑过:取输入框里 — 之前的部分
            layout = self.cmb_layout.currentText().split('—')[0].strip()
        return OrganizeOptions(
            inputs=list(self.inputs), out_dir=out,
            layout=layout or '{类别}/{年}',
            op_mode='copy' if self._rg_op.checkedId() == 1 else 'move',
            preview=self._ckg['org_preview'].isChecked(),
            rules=self._get_rules(),
            find_dup=self._ckg['org_dup'].isChecked(),
            find_versions=self._ckg['org_versions'].isChecked(),
            find_junk=self._ckg['org_junk'].isChecked(),
            separate_large=self._ckg['org_large'].isChecked(),
            large_threshold=self.spin_large.value() * 1024 * 1024,
            clean_empty_dirs=self._ckg['org_empty'].isChecked(),
            date_source=('auto' if self._ckg['org_smart_date'].isChecked()
                         else 'mtime'),
            scan_only=self._ckg['org_scan_only'].isChecked(),
            extract_archives=self._ckg['org_extract'].isChecked(),
            keep_projects=self._ckg['org_keep_proj'].isChecked(),
            skip_hidden=not self._ckg['org_hidden'].isChecked(),
            min_dup_size=self.spin_mindup.value() * 1024)

    def _start_organize(self, out):
        opts = self._organize_opts(out)
        if opts.op_mode == 'move':
            r = QMessageBox.question(
                self, '确认整理',
                f'将把所选位置的文件【移动】到:\n{out}\n\n'
                f'目录布局: {opts.layout}\n\n'
                f'全过程会记入撤销台账,整理后可随时点「撤销上次整理」还原。\n'
                f'确定继续吗?',
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        conf.save_config(self._gather_cfg())
        self._begin_job()

        def done(summary):
            self._ui_call(lambda: self._on_done(summary))

        threading.Thread(
            target=run_organize,
            args=(opts, self._log, self._on_progress,
                  self._confirm_plan, self._cancel, done,
                  self._ask_password),
            daemon=True).start()

    def _search_history(self):
        """按文件名查历次整理:这个文件当初在哪、被整理到哪去了。"""
        from . import history
        out = self.txt_out.text().strip()
        if not out or not os.path.isdir(out):
            QMessageBox.warning(self, '提示', '请先选择整理结果所在的目录。')
            return
        if not os.path.isfile(history.db_path(out)):
            QMessageBox.information(
                self, '提示',
                f'该目录还没有整理历史(整理过一次后才会有):\n{out}')
            return
        kw, ok = QInputDialog.getText(self, '查整理历史',
                                      '输入文件名的一部分:')
        if not ok or not kw.strip():
            return
        rows = history.search(out, kw)
        if not rows:
            QMessageBox.information(self, '未找到',
                                    f'历史记录里没有匹配「{kw}」的文件。')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f'整理历史 — 匹配「{kw}」({len(rows)} 条)')
        dlg.resize(900, 460)
        lay = QVBoxLayout(dlg)
        tree = QTreeWidget()
        tree.setHeaderLabels(['整理时间', '文件名', '整理前位置', '整理后位置'])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        for run_at, fname, src, dst, _cat in rows:
            QTreeWidgetItem(tree, [run_at.replace('T', ' '), fname, src, dst])
        for i, w in enumerate([140, 200, 270, 270]):
            tree.header().resizeSection(i, w)
        lay.addWidget(tree)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(dlg.reject)
        box.accepted.connect(dlg.accept)
        lay.addWidget(box)
        dlg.exec()
        dlg.deleteLater()

    def _purge_now(self):
        """把整理结果里的「可清理/重复文件/旧版本」删到回收站。

        只删整理台账里记录过、由本工具放进这些文件夹的文件;
        每删一个都补记台账,日后撤销会提示去回收站找回。"""
        from . import purge as pg
        from .health import human_size
        out = self.txt_out.text().strip()
        if not out or not os.path.isdir(out):
            QMessageBox.warning(self, '提示', '请先选择整理结果所在的目录。')
            return
        found = pg.summarize(pg.collect_candidates(out, pg.BUCKETS))
        if not found:
            QMessageBox.information(
                self, '提示',
                f'该目录里没有由本工具整理出的「可清理 / 重复文件 / 旧版本」可删:\n{out}')
            return

        names = [f'{b}({n} 个,{human_size(sz)})' for b, n, sz in found]
        picked, ok = QInputDialog.getItem(
            self, '选择要清理的内容',
            '把下列文件夹里的文件删到回收站(可先自行核对内容):',
            names + ['全部'], len(names), False)
        if not ok:
            return
        targets = ([b for b, _n, _s in found] if picked == '全部'
                   else [found[names.index(picked)][0]])
        total = sum(n for b, n, _s in found if b in targets)
        saved = sum(sz for b, _n, sz in found if b in targets)
        r = QMessageBox.question(
            self, '确认清理',
            f'将把 {total} 个文件移入回收站,腾出约 {human_size(saved)}。\n'
            f'涉及: {"、".join(targets)}\n\n'
            f'只删除本工具整理进这些文件夹的文件,你自己放进去的不受影响。\n'
            f'清理会记入整理台账,日后撤销时会提示这些文件需从回收站还原。\n'
            f'确定继续吗?',
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return

        self._begin_job()

        def work():
            n, freed = pg.purge(out, targets, self._log, self._cancel)
            self._ui_call(lambda: self._on_purge_done(n, freed))

        threading.Thread(target=work, daemon=True).start()

    def _on_purge_done(self, n, saved):
        from .health import human_size
        self.btn_run.setEnabled(True)
        self._on_mode_changed()
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self.lbl_prog.setVisible(False)
        QMessageBox.information(
            self, '清理完成',
            f'已把 {n} 个文件移入回收站,腾出约 {human_size(saved)}。')

    def _undo_last(self):
        out = self.txt_out.text().strip()
        if not out or not os.path.isdir(out):
            QMessageBox.warning(self, '提示', '请先选择整理结果所在的目录。')
            return
        journals = undo_mod.find_journals(out)
        if not journals:
            QMessageBox.information(
                self, '提示',
                f'该目录里没有找到整理台账(整理台账_*.jsonl):\n{out}')
            return
        names = [os.path.basename(j) for j in journals]
        pick, ok = QInputDialog.getItem(
            self, '撤销整理', '选择要撤销的那次整理(最新的在最前):',
            names, 0, False)
        if not ok:
            return
        journal = journals[names.index(pick)]
        meta, ops = undo_mod.read_journal(journal)
        r = QMessageBox.question(
            self, '确认撤销',
            f'将按台账把 {len(ops)} 项操作全部还原:\n{pick}\n'
            f'整理时间: {meta.get("time", "?")}   方式: {meta.get("op_mode", "?")}\n\n'
            f'文件会被移回整理前的原始位置。确定吗?',
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self._begin_job()

        def work():
            stats = undo_mod.undo(journal, log=self._log, cancel=self._cancel)
            self._ui_call(lambda: self._on_undo_done(stats))

        threading.Thread(target=work, daemon=True).start()

    def _on_undo_done(self, stats):
        self.btn_run.setEnabled(True)
        self._on_mode_changed()
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self.lbl_prog.setVisible(False)
        QMessageBox.information(
            self, '撤销完成',
            f'已还原 {stats.get("restored", 0)} 项,'
            f'删除副本 {stats.get("removed", 0)} 个。\n'
            f'找不到 {stats.get("missing", 0)} 个,失败 {stats.get("failed", 0)} 个。'
            + (f'\n另有 {stats["trashed"]} 个文件之前已清理到回收站,'
               f'需从回收站手动还原(详见日志)。'
               if stats.get('trashed') else ''))

    def _on_organize_done(self, summary):
        from .health import human_size
        hs = summary.get('health', {})
        if summary.get('scan_only'):
            lines = ['体检完成(未移动任何文件):',
                     f'· 文件总数 {len(summary.get("stats", {})) or ""}'.rstrip(),
                     f'· 重复文件 {hs.get("dup_extra", 0)} 个,'
                     f'删除可省出 {human_size(hs.get("dup_bytes", 0))}',
                     f'· 垃圾/临时文件 {hs.get("junk", 0)} 个,'
                     f'占用 {human_size(hs.get("junk_bytes", 0))}',
                     f'· 旧版本 {hs.get("old_versions", 0)} 个',
                     '\n详见输出目录里的「整理报告」。'
                     '去掉「只体检」勾选后再运行,即可真正整理。']
            QMessageBox.information(self, '体检完成', '\n'.join(lines))
            return
        lines = [f'整理完成!共处理 {summary.get("files", 0)} 个文件。']
        if hs.get('dup_extra'):
            lines.append(f'· 重复文件 {hs["dup_extra"]} 个 → 「重复文件」,'
                         f'确认后删除可省出 {human_size(hs.get("dup_bytes", 0))}')
        if hs.get('junk'):
            lines.append(f'· 垃圾/临时文件 {hs["junk"]} 个 → 「可清理」,'
                         f'占用 {human_size(hs.get("junk_bytes", 0))}')
        if hs.get('old_versions'):
            lines.append(f'· 旧版本 {hs["old_versions"]} 个 → 「旧版本」')
        if summary.get('projects'):
            lines.append(f'· {summary["projects"]} 个代码/工程目录已整体保留,'
                         f'内部结构未打散')
        if summary.get('empty_dirs'):
            lines.append(f'· 清理空文件夹 {summary["empty_dirs"]} 个')
        if summary.get('failed'):
            lines.append(f'· 失败 {summary["failed"]} 个(见日志)')
        if summary.get('reports'):
            lines.append('· 已生成整理报告(类型/年份/占用/最大文件)')
        lines.append('\n如果结果不满意,点「文件整理」页的'
                     '「撤销上次整理」即可全部还原。')
        QMessageBox.information(self, '完成', '\n'.join(lines))
