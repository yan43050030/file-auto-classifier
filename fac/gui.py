# -*- coding: utf-8 -*-
"""图形界面。

可选增强(缺失时自动降级为原生 tkinter,不影响功能):
  - ttkbootstrap : 现代化主题
  - tkinterdnd2  : 拖拽添加压缩包/文件夹
"""

import os
import sys
import datetime
import threading

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from . import VERSION, APP_NAME
from .util import resource_path
from .roster import Roster
from .pipeline import JobOptions, run_job
from .rules import Rule
from . import config as conf
from . import extract as ex

try:
    import ttkbootstrap as tb
    HAS_TB = True
except Exception:
    HAS_TB = False

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    from tkinterdnd2.TkinterDnD import DnDWrapper
    HAS_DND = True
except Exception:
    HAS_DND = False


def enable_hidpi():
    """让程序在 Windows 高分屏(缩放 125%/150%/200%)下清晰显示。
    必须在创建 Tk() 窗口之前调用。"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_Base = tb.Window if HAS_TB else tk.Tk


class App(_Base):
    def __init__(self):
        if HAS_TB:
            super().__init__(themename='cosmo')
        else:
            super().__init__()
        self.title(f'{APP_NAME}  {VERSION}')
        self._setup_dpi_scaling()
        self._set_icon()
        self.inputs = []
        self.cancel_event = None
        self.build_ui()
        self._enable_dnd()
        self._apply_cfg(conf.load_config())
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    # ---------- 窗口基础 ----------

    def _setup_dpi_scaling(self):
        try:
            dpi = self.winfo_fpixels('1i')
        except Exception:
            dpi = 96.0
        try:
            self.tk.call('tk', 'scaling', dpi / 72.0)
        except Exception:
            pass
        try:
            import tkinter.font as tkfont
            for fname in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont',
                          'TkHeadingFont', 'TkFixedFont'):
                try:
                    f = tkfont.nametofont(fname)
                    f.configure(family='Microsoft YaHei UI', size=10)
                except Exception:
                    pass
        except Exception:
            pass
        scale = dpi / 96.0
        w, h = int(860 * scale), int(760 * scale)
        self.geometry(f'{w}x{h}')
        self.minsize(int(680 * scale), int(600 * scale))

    def _set_icon(self):
        try:
            self.iconbitmap(resource_path('app.ico'))
        except Exception:
            pass

    def _enable_dnd(self):
        """拖拽支持:把压缩包/文件夹直接拖进窗口即可添加。"""
        if not HAS_DND:
            return
        try:
            TkinterDnD._require(self)

            def on_drop(event):
                for p in self.tk.splitlist(event.data):
                    self._add_input(p)
                return 'copy'

            for widget in (self, self.lb_inputs):
                DnDWrapper.drop_target_register(widget, DND_FILES)
                DnDWrapper.dnd_bind(widget, '<<Drop>>', on_drop)
            self.lbl_dnd.configure(text='(可直接把压缩包/文件夹拖进窗口)')
        except Exception:
            pass

    # ---------- 界面搭建 ----------

    def build_ui(self):
        pad = {'padx': 8, 'pady': 4}

        # --- 1. 输入 ---
        f1 = ttk.LabelFrame(self, text='第一步:选择压缩包/文件夹,或直接选非压缩包文件也可分类')
        f1.pack(fill='x', **pad)
        self.lb_inputs = tk.Listbox(f1, height=4)
        self.lb_inputs.pack(side='left', fill='x', expand=True, padx=6, pady=6)
        self.lb_inputs.bind('<Delete>', lambda e: self.remove_selected())
        # 右键菜单
        self._rmenu = tk.Menu(self.lb_inputs, tearoff=0)
        self._rmenu.add_command(label='移除选中', command=self.remove_selected)
        self._rmenu.add_command(label='清空全部', command=self.clear_inputs)
        def _rclick(event):
            try:
                i = self.lb_inputs.nearest(event.y)
                if i not in self.lb_inputs.curselection():
                    self.lb_inputs.selection_clear(0, 'end')
                    self.lb_inputs.selection_set(i)
            except Exception:
                pass
            self._rmenu.post(event.x_root, event.y_root)
        self.lb_inputs.bind('<Button-3>', _rclick)
        b1 = ttk.Frame(f1)
        b1.pack(side='right', padx=6)
        ttk.Button(b1, text='添加压缩包', command=self.add_files).pack(fill='x', pady=2)
        ttk.Button(b1, text='添加文件夹', command=self.add_folder).pack(fill='x', pady=2)
        ttk.Button(b1, text='添加文件', command=self.add_loose_files).pack(fill='x', pady=2)
        ttk.Button(b1, text='移除选中', command=self.remove_selected).pack(fill='x', pady=2)
        ttk.Button(b1, text='清空全部', command=self.clear_inputs).pack(fill='x', pady=2)
        self.lbl_dnd = ttk.Label(b1, text='', foreground='#888')
        self.lbl_dnd.pack()

        # --- 2. 输出目录 ---
        f2 = ttk.LabelFrame(self, text='第二步:选择分类结果保存到哪里')
        f2.pack(fill='x', **pad)
        self.var_out = tk.StringVar()
        ttk.Entry(f2, textvariable=self.var_out).pack(
            side='left', fill='x', expand=True, padx=6, pady=6)
        ttk.Button(f2, text='浏览...', command=self.choose_out).pack(side='right', padx=6)

        # --- 3. 名单 / 选项 / 高级 ---
        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, **pad)

        # 名单页
        tab_r = ttk.Frame(nb)
        nb.add(tab_r, text=' 人员名单 ')
        rb = ttk.Frame(tab_r)
        rb.pack(fill='x', padx=6, pady=(6, 0))
        ttk.Button(rb, text='从 Excel 导入名单...',
                   command=self.import_roster_excel).pack(side='left')
        ttk.Button(rb, text='保存为模板...',
                   command=self.save_template).pack(side='left', padx=6)
        ttk.Button(rb, text='加载模板...',
                   command=self.load_template).pack(side='left')
        self.lbl_roster = ttk.Label(rb, text='', foreground='#888')
        self.lbl_roster.pack(side='right')
        self.txt_kw = scrolledtext.ScrolledText(tab_r, height=8)
        self.txt_kw.pack(fill='both', expand=True, padx=6, pady=6)
        self.txt_kw.insert('1.0',
            '# 每行一个人:姓名,身份证号,曾用名…(证号/曾用名可省略,分隔符逗号或空格)\n'
            '# 同一个人的姓名、证号、曾用名任一命中,文件都归入 TA 的文件夹。\n'
            '# 公司名等普通关键字也直接写一行即可。示例(去掉开头的#即生效):\n'
            '# 张三\n'
            '# 李四,110101199003078515\n'
            '# 王五,王小五,老王\n')

        # 选项页
        tab_o = ttk.Frame(nb)
        nb.add(tab_o, text=' 分类选项 ')
        self.var_multi = tk.StringVar(value='first')
        ttk.Radiobutton(tab_o, text='一个文件命中多个人 → 只归入最匹配的一个(最长关键字优先)',
                        variable=self.var_multi, value='first').pack(anchor='w', padx=8, pady=(8, 0))
        ttk.Radiobutton(tab_o, text='一个文件命中多个人 → 复制到每个命中的文件夹',
                        variable=self.var_multi, value='each').pack(anchor='w', padx=8)
        self.var_autoid = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab_o, text='自动识别身份证号:未命中名单的文件,按文件名中的身份证号'
                                    '(18/15位,带校验)自动分类',
                        variable=self.var_autoid).pack(anchor='w', padx=8, pady=4)
        ttk.Separator(tab_o).pack(fill='x', padx=8, pady=4)
        ttk.Label(tab_o, text='来源单位标注(来源单位=压缩包文件名):').pack(anchor='w', padx=8)
        self.var_unit = tk.StringVar(value='subfolder')
        ttk.Radiobutton(tab_o, text='人员文件夹下按单位建子文件夹(推荐)',
                        variable=self.var_unit, value='subfolder').pack(anchor='w', padx=24)
        ttk.Radiobutton(tab_o, text='文件名前加【单位】前缀',
                        variable=self.var_unit, value='prefix').pack(anchor='w', padx=24)
        ttk.Radiobutton(tab_o, text='不标注来源',
                        variable=self.var_unit, value='none').pack(anchor='w', padx=24)
        ttk.Separator(tab_o).pack(fill='x', padx=8, pady=4)
        self.var_preview = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab_o, text='试运行预览:先列出"哪个文件→哪个文件夹"的清单,确认后再执行',
                        variable=self.var_preview).pack(anchor='w', padx=8, pady=2)

        # 高级页
        tab_a = ttk.Frame(nb)
        nb.add(tab_a, text=' 高级功能 ')
        self.var_content = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab_a, text='内容匹配:文件名未命中时,读取 Excel/Word/PDF/文本内容查找名单中的人',
                        variable=self.var_content).pack(anchor='w', padx=8, pady=(8, 0))
        try:
            from .content_match import SUPPORTED_EXTS
            ttk.Label(tab_a, text='    当前支持: ' + ' '.join(SUPPORTED_EXTS),
                      foreground='#888').pack(anchor='w', padx=8)
        except Exception:
            pass
        self.var_split = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab_a, text='Excel 按人拆分:一个表里有多个人的行时,按行拆成每人一份'
                                    '(原表保留在「原始反馈」)',
                        variable=self.var_split).pack(anchor='w', padx=8, pady=2)
        self.var_dedup = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab_a, text='内容去重:同一人员文件夹内,多个单位反馈的相同文件只留一份',
                        variable=self.var_dedup).pack(anchor='w', padx=8, pady=2)
        ttk.Separator(tab_a).pack(fill='x', padx=8, pady=4)

        # 高级分类规则
        rf = ttk.LabelFrame(tab_a, text='高级分类规则(名单未命中时按规则匹配:文件类型/大小/时间/自定义)')
        rf.pack(fill='both', padx=8, pady=(4, 4), expand=True)
        rtop = ttk.Frame(rf); rtop.pack(fill='x', padx=6, pady=(6, 2))
        ttk.Button(rtop, text='+ 添加规则', command=self.add_rule).pack(side='left')
        ttk.Button(rtop, text='移除此规则', command=self.del_rule).pack(side='left', padx=4)
        self._rule_frame = ttk.Frame(rf)
        self._rule_frame.pack(fill='both', expand=True, padx=6, pady=(2, 6))
        # 规则面板用 canvas+scrollbar 防溢出
        self._rule_canvas = tk.Canvas(self._rule_frame, height=120, highlightthickness=0)
        self._rule_scroll = ttk.Scrollbar(self._rule_frame, orient='vertical',
                                           command=self._rule_canvas.yview)
        self._rule_inner = ttk.Frame(self._rule_canvas)
        self._rule_canvas.configure(yscrollcommand=self._rule_scroll.set)
        self._rule_canvas.pack(side='left', fill='both', expand=True)
        self._rule_scroll.pack(side='right', fill='y')
        self._rule_canvas.create_window((0, 0), window=self._rule_inner,
                                        anchor='nw', tags='inner')
        self._rule_inner.bind('<Configure>',
            lambda e: self._rule_canvas.configure(scrollregion=self._rule_canvas.bbox('all')))
        self._rule_canvas.bind('<Configure>',
            lambda e: self._rule_canvas.itemconfig('inner', width=e.width))
        self._rule_rows = []   # 每行的 widget 字典

        ttk.Separator(tab_a).pack(fill='x', padx=8, pady=4)
        self.var_pwtxt = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab_a, text='自动把输入文件夹里的 .txt 当密码本:加密包先自动尝试,失败再弹框',
                        variable=self.var_pwtxt).pack(anchor='w', padx=8, pady=2)
        pf = ttk.Frame(tab_a)
        pf.pack(fill='x', padx=8, pady=2)
        ttk.Label(pf, text='额外密码本(可选):').pack(side='left')
        self.var_pwfile = tk.StringVar()
        ttk.Entry(pf, textvariable=self.var_pwfile).pack(
            side='left', fill='x', expand=True, padx=4)
        ttk.Button(pf, text='选择...', command=self.choose_pwfile).pack(side='left')
        self.var_delok = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab_a, text='⚠ 分类完成后,删除已成功解压的压缩包(移入回收站;失败的不删)',
                        variable=self.var_delok).pack(anchor='w', padx=8, pady=(2, 6))

        # --- 4. 运行 + 进度 ---
        f5 = ttk.Frame(self)
        f5.pack(fill='x', **pad)
        self.btn_run = ttk.Button(f5, text='开始分类', command=self.start)
        self.btn_run.pack(side='left')
        self.btn_cancel = ttk.Button(f5, text='取消', command=self.cancel,
                                     state='disabled')
        self.btn_cancel.pack(side='left', padx=6)
        ttk.Button(f5, text='打开结果文件夹', command=self.open_out).pack(side='left', padx=6)
        fmt = 'zip√' + ('(AES√)' if ex.HAS_AES else '(AES✗)') + '  ' \
            + ('7z√  ' if ex.HAS_7Z else '7z✗  ') \
            + ('rar√(内置UnRAR)' if ex.HAS_RAR else 'rar✗') + '  tar/gz√'
        ttk.Label(f5, text='支持: ' + fmt, foreground='#666').pack(side='right')

        fp = ttk.Frame(self)
        fp.pack(fill='x', padx=8)
        self.progress = ttk.Progressbar(fp, maximum=100)
        self.progress.pack(side='left', fill='x', expand=True)
        self.lbl_prog = ttk.Label(fp, text='', width=18, anchor='e')
        self.lbl_prog.pack(side='right', padx=4)

        self.log_box = scrolledtext.ScrolledText(self, height=8, state='disabled')
        self.log_box.pack(fill='both', expand=True, **pad)

    # ---------- 界面操作 ----------

    def _add_input(self, path):
        path = path.strip()
        if not path or path in self.inputs:
            return
        if os.path.isdir(path):
            self.inputs.append(path)
            self.lb_inputs.insert('end', path + '  (文件夹)')
        elif os.path.isfile(path):
            self.inputs.append(path)
            self.lb_inputs.insert('end', path)
        # 首次添加输入时自动预填输出目录
        if len(self.inputs) == 1 and not self.var_out.get().strip():
            base = path if os.path.isdir(path) else os.path.dirname(path)
            dft = os.path.join(base, f'分类结果_{datetime.datetime.now():%Y%m%d}')
            self.var_out.set(dft)

    def add_files(self):
        files = filedialog.askopenfilenames(
            title='选择压缩包',
            filetypes=[('压缩包', '*.zip *.7z *.rar *.tar *.gz *.tgz *.001'),
                       ('所有文件', '*.*')])
        for f in files:
            self._add_input(f)

    def add_folder(self):
        d = filedialog.askdirectory(title='选择含压缩包的文件夹')
        if d:
            self._add_input(d)

    def add_loose_files(self):
        files = filedialog.askopenfilenames(
            title='选择要直接分类的文件(非压缩包也可以)',
            filetypes=[('所有文件', '*.*')])
        for f in files:
            self._add_input(f)

    def remove_selected(self):
        sel = list(self.lb_inputs.curselection())
        for i in sorted(sel, reverse=True):
            if i < len(self.inputs):
                del self.inputs[i]
            self.lb_inputs.delete(i)

    def clear_inputs(self):
        self.inputs = []
        self.lb_inputs.delete(0, 'end')

    def choose_out(self):
        d = filedialog.askdirectory(title='选择输出目录')
        if d:
            self.var_out.set(d)

    def choose_pwfile(self):
        f = filedialog.askopenfilename(
            title='选择密码本 txt',
            filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')])
        if f:
            self.var_pwfile.set(f)

    # ---------- 高级分类规则 UI ----------

    def add_rule(self):
        """添加一条新规则(默认按扩展名匹配)."""
        row = {'rule_type': tk.StringVar(value='ext'),
               'value': tk.StringVar(), 'target': tk.StringVar(),
               'enabled': tk.BooleanVar(value=True)}
        self._rule_rows.append(row)
        self._build_rule_row(len(self._rule_rows) - 1, row)

    def del_rule(self):
        for i, row in enumerate(self._rule_rows):
            try:
                if row.get('_cb_sel') and row['_cb_sel'].get():
                    del self._rule_rows[i]
                    self._rebuild_rule_ui()
                    return
            except Exception:
                pass

    def _build_rule_row(self, idx, row):
        f = ttk.Frame(self._rule_inner)
        f.pack(fill='x', pady=1)
        cb = ttk.Checkbutton(f, variable=row['enabled'], width=2)
        cb.pack(side='left'); row['_cb_sel'] = tk.BooleanVar(value=False)
        # 保留下划线以绑定变量到行
        ttk.Checkbutton(f, variable=row['_cb_sel'], text='').pack(side='left')
        ttk.Combobox(f, textvariable=row['rule_type'], width=10, state='readonly',
                     values=['ext','size_gt','size_lt','date_before','date_after',
                             'contains','regex']).pack(side='left', padx=2)
        # 中文标签映射
        ttk.Label(f, text='值:', font=('', 8)).pack(side='left')
        ttk.Entry(f, textvariable=row['value'], width=18).pack(side='left', padx=2)
        ttk.Label(f, text='归入:', font=('', 8)).pack(side='left')
        ttk.Entry(f, textvariable=row['target'], width=14).pack(side='left', padx=2)
        # 规则类型提示
        hints = {'ext':'扩展名如 pdf','size_gt':'大于如 10MB','size_lt':'小于',
                 'date_before':'日期前如 2024','date_after':'日期后',
                 'contains':'包含文字','regex':'正则如 \\d{4}年'}
        lbl_h = ttk.Label(f, text='', foreground='#999', font=('', 7), width=18, anchor='w')
        def _update_hint(*a, r=row, h=lbl_h):
            h.configure(text=hints.get(r['rule_type'].get(), ''))
        row['rule_type'].trace_add('write', _update_hint)
        _update_hint()
        lbl_h.pack(side='left', padx=4)

    def _rebuild_rule_ui(self):
        for w in self._rule_inner.winfo_children():
            w.destroy()
        for i, row in enumerate(self._rule_rows):
            self._build_rule_row(i, row)

    def _get_rules(self):
        rlist = []
        for row in self._rule_rows:
            t = row['rule_type'].get()
            if t and row['value'].get().strip():
                rlist.append(Rule(t, row['value'].get(), row['target'].get(),
                                  row['enabled'].get()))
        return rlist

    def _load_rules(self, rules_data):
        self._rule_rows.clear()
        for d in (rules_data or []):
            row = {'rule_type': tk.StringVar(value=d.get('rule_type','ext')),
                   'value': tk.StringVar(value=d.get('value','')),
                   'target': tk.StringVar(value=d.get('target','')),
                   'enabled': tk.BooleanVar(value=bool(d.get('enabled', True)))}
            self._rule_rows.append(row)
        self._rebuild_rule_ui()

    def open_out(self):
        out = self.var_out.get().strip()
        if out and os.path.isdir(out):
            try:
                os.startfile(out)  # 仅 Windows
            except Exception:
                messagebox.showinfo('提示', f'结果目录:\n{out}')
        else:
            messagebox.showwarning('提示', '请先选择有效的输出目录。')

    def import_roster_excel(self):
        f = filedialog.askopenfilename(
            title='选择名单 Excel(列:姓名/身份证号/曾用名,或第1列姓名第2列证号)',
            filetypes=[('Excel', '*.xlsx *.xlsm'), ('所有文件', '*.*')])
        if not f:
            return
        try:
            roster = Roster.from_excel(f)
        except ImportError:
            messagebox.showerror('缺少依赖', '导入 Excel 需要安装 openpyxl:\n'
                                             'pip install openpyxl')
            return
        except Exception as e:
            messagebox.showerror('导入失败', f'无法读取该 Excel:\n{e}')
            return
        if not roster.persons:
            messagebox.showwarning('提示', '该 Excel 中没有识别到人员。')
            return
        lines = []
        for p in roster.persons:
            parts = [p.name] + p.ids + p.aliases
            lines.append(','.join(parts))
        self.txt_kw.insert('end', '\n' + '\n'.join(lines) + '\n')
        self.lbl_roster.configure(text=f'已导入 {len(roster.persons)} 人')

    # ---------- 模板 ----------

    def _gather_cfg(self):
        return {
            'out_dir': self.var_out.get().strip(),
            'roster_text': self.txt_kw.get('1.0', 'end').rstrip('\n'),
            'multi_hit': self.var_multi.get(),
            'auto_id': self.var_autoid.get(),
            'unit_mode': self.var_unit.get(),
            'preview': self.var_preview.get(),
            'content_match': self.var_content.get(),
            'split_excel': self.var_split.get(),
            'dedup': self.var_dedup.get(),
            'auto_pw_txt': self.var_pwtxt.get(),
            'pw_file': self.var_pwfile.get().strip(),
            'delete_ok': self.var_delok.get(),
            'rules': [r.to_dict() for r in self._get_rules()],
        }

    def _apply_cfg(self, cfg):
        try:
            if cfg.get('out_dir'):
                self.var_out.set(cfg['out_dir'])
            if cfg.get('roster_text'):
                self.txt_kw.delete('1.0', 'end')
                self.txt_kw.insert('1.0', cfg['roster_text'] + '\n')
            self.var_multi.set(cfg.get('multi_hit', 'first'))
            self.var_autoid.set(bool(cfg.get('auto_id', True)))
            self.var_unit.set(cfg.get('unit_mode', 'subfolder'))
            self.var_preview.set(bool(cfg.get('preview', False)))
            self.var_content.set(bool(cfg.get('content_match', False)))
            self.var_split.set(bool(cfg.get('split_excel', False)))
            self.var_dedup.set(bool(cfg.get('dedup', False)))
            self.var_pwtxt.set(bool(cfg.get('auto_pw_txt', True)))
            self.var_pwfile.set(cfg.get('pw_file', ''))
            self.var_delok.set(bool(cfg.get('delete_ok', False)))
            self._load_rules(cfg.get('rules', []))
        except Exception:
            pass

    def save_template(self):
        f = filedialog.asksaveasfilename(
            title='保存任务模板', initialdir=conf.template_dir(),
            defaultextension='.json', filetypes=[('任务模板', '*.json')])
        if not f:
            return
        try:
            conf.save_template(f, self._gather_cfg())
            self.log(f'模板已保存: {f}')
        except Exception as e:
            messagebox.showerror('保存失败', str(e))

    def load_template(self):
        f = filedialog.askopenfilename(
            title='加载任务模板', initialdir=conf.template_dir(),
            filetypes=[('任务模板', '*.json'), ('所有文件', '*.*')])
        if not f:
            return
        try:
            self._apply_cfg(conf.load_template(f))
            self.log(f'模板已加载: {f}')
        except Exception as e:
            messagebox.showerror('加载失败', str(e))

    def _on_close(self):
        conf.save_config(self._gather_cfg())
        self.destroy()

    # ---------- 日志 / 进度 ----------

    def log(self, msg):
        def _append():
            self.log_box.configure(state='normal')
            self.log_box.insert('end', msg + '\n')
            self.log_box.see('end')
            self.log_box.configure(state='disabled')
        self.after(0, _append)

    _PHASES = {'extract': ('解压', 0.0, 0.5),
               'classify': ('匹配', 0.5, 0.2),
               'place': ('归档', 0.7, 0.3)}

    def on_progress(self, phase, cur, total):
        name, base, span = self._PHASES.get(phase, (phase, 0, 1))
        frac = cur / total if total else 1.0
        val = (base + frac * span) * 100

        def _set():
            self.progress.configure(value=val)
            self.lbl_prog.configure(text=f'{name} {cur}/{total}')
        self.after(0, _set)

    # ---------- 后台线程与主线程的交互 ----------

    def ask_password(self, archive_name, attempt):
        """在主线程弹出密码输入框,供后台线程调用(阻塞等待用户输入)。
        取消或留空 → 压缩包放入「暂未解压」文件夹,不影响其他分类。"""
        result = {}
        ev = threading.Event()

        def _prompt():
            from tkinter import simpledialog
            if attempt > 1:
                msg = (f'密码错误,请重新输入。\n\n'
                       f'压缩包「{archive_name}」需要解压密码:\n'
                       f'(取消 → 放入「暂未解压」文件夹,可稍后再处理)')
            else:
                msg = (f'该压缩包有密码。\n\n'
                       f'压缩包「{archive_name}」需要解压密码:\n'
                       f'(取消或留空 → 放入「暂未解压」文件夹,可稍后再处理)')
            result['pwd'] = simpledialog.askstring(
                '需要解压密码', msg, show='*', parent=self)
            ev.set()

        self.after(0, _prompt)
        ev.wait()
        return result.get('pwd')

    def confirm_plan(self, plan):
        """预览窗口:列出归档计划,等待用户确认(阻塞后台线程)。"""
        result = {}
        ev = threading.Event()

        def _show():
            win = tk.Toplevel(self)
            win.title(f'预览归档计划(共 {len(plan)} 个文件)')
            win.transient(self)
            win.geometry('760x480')
            cols = ('file', 'unit', 'target', 'via')
            tree = ttk.Treeview(win, columns=cols, show='headings')
            for c, txt, w in (('file', '文件名', 300), ('unit', '来源单位', 140),
                              ('target', '归入文件夹', 200), ('via', '命中方式', 80)):
                tree.heading(c, text=txt)
                tree.column(c, width=w, anchor='w')
            vsb = ttk.Scrollbar(win, orient='vertical', command=tree.yview)
            tree.configure(yscrollcommand=vsb.set)
            for item in plan:
                tree.insert('', 'end', values=(
                    item.fname, item.unit, item.display_target(), item.via))
            btns = ttk.Frame(win)
            btns.pack(side='bottom', fill='x', padx=8, pady=8)

            def _done(ok):
                result['ok'] = ok
                ev.set()
                win.destroy()

            ttk.Button(btns, text='确认执行', command=lambda: _done(True)).pack(side='right')
            ttk.Button(btns, text='取消', command=lambda: _done(False)).pack(side='right', padx=8)
            n_un = sum(1 for i in plan if i.targets == ['未分类'])
            ttk.Label(btns, text=f'未分类: {n_un} 个').pack(side='left')
            vsb.pack(side='right', fill='y')
            tree.pack(fill='both', expand=True, padx=8, pady=(8, 0))
            win.protocol('WM_DELETE_WINDOW', lambda: _done(False))
            win.grab_set()

        self.after(0, _show)
        ev.wait()
        return result.get('ok', False)

    # ---------- 运行 ----------

    def cancel(self):
        if self.cancel_event is not None:
            self.cancel_event.set()
            self.btn_cancel.configure(state='disabled', text='正在取消...')

    def start(self):
        if not self.inputs:
            messagebox.showwarning('提示', '请先添加压缩包或文件夹。')
            return
        out = self.var_out.get().strip()
        if not out:
            messagebox.showwarning('提示', '请先选择输出目录。')
            return
        roster = Roster.from_text(self.txt_kw.get('1.0', 'end'))
        auto_id = self.var_autoid.get()
        if len(roster) == 0 and not auto_id:
            messagebox.showwarning('提示', '请至少输入名单/关键字,或勾选"自动识别身份证号"。')
            return

        pw_files = []
        pwf = self.var_pwfile.get().strip()
        if pwf:
            if os.path.isfile(pwf):
                pw_files.append(pwf)
            else:
                messagebox.showwarning('提示', '指定的密码本文件不存在,已忽略。')
        delete_ok = self.var_delok.get()
        if delete_ok:
            if not messagebox.askyesno(
                    '确认删除',
                    '分类完成后,将把【已成功解压】的原始压缩包移入回收站。\n'
                    '解压失败的压缩包不会删除。\n\n确定要继续吗?'):
                return

        conf.save_config(self._gather_cfg())

        opts = JobOptions(
            inputs=list(self.inputs), out_dir=out, roster=roster,
            copy_to_each=(self.var_multi.get() == 'each'),
            auto_id=auto_id,
            unit_mode=self.var_unit.get(),
            preview=self.var_preview.get(),
            content_match=self.var_content.get(),
            split_excel=self.var_split.get(),
            dedup=self.var_dedup.get(),
            auto_pw_txt=self.var_pwtxt.get(),
            pw_files=pw_files,
            delete_ok=delete_ok,
            rules=self._get_rules())

        self.btn_run.configure(state='disabled', text='正在处理...')
        self.btn_cancel.configure(state='normal', text='取消')
        self.progress.configure(value=0)
        self.log_box.configure(state='normal')
        self.log_box.delete('1.0', 'end')
        self.log_box.configure(state='disabled')
        self.cancel_event = threading.Event()

        def done(summary):
            def _ui():
                self.btn_run.configure(state='normal', text='开始分类')
                self.btn_cancel.configure(state='disabled', text='取消')
                self.progress.configure(value=0 if summary['cancelled'] else 100)
                self.lbl_prog.configure(text='')
                if summary['cancelled']:
                    return
                msg = f'分类完成!共处理 {summary["files"]} 个文件。'
                if summary.get('skipped_pw'):
                    msg += f'\n{summary["skipped_pw"]} 个加密包未解压,见「暂未解压」文件夹。'
                if summary['failed']:
                    msg += f'\n{summary["failed"]} 个压缩包解压失败,见「解压失败」文件夹。'
                if summary['reports']:
                    msg += '\n已生成反馈核对表(人员×单位)。'
                messagebox.showinfo('完成', msg)
            self.after(0, _ui)

        t = threading.Thread(
            target=run_job,
            args=(opts, self.log, self.on_progress, self.ask_password,
                  self.confirm_plan, self.cancel_event, done),
            daemon=True)
        t.start()


def main():
    enable_hidpi()
    App().mainloop()


if __name__ == '__main__':
    main()
