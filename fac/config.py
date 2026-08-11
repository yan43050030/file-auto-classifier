# -*- coding: utf-8 -*-
"""配置持久化:记住上次的输出目录、选项、人员名单;支持保存/加载任务模板。"""

import json
import os

CONF_DIR = os.path.join(os.path.expanduser('~'), '.file_auto_classifier')
CONF_FILE = os.path.join(CONF_DIR, 'config.json')
TEMPLATE_DIR = os.path.join(CONF_DIR, 'templates')

DEFAULTS = {
    'out_dir': '',
    'roster_text': '',
    'multi_hit': 'first',        # first | each
    'auto_id': True,
    'unit_mode': 'subfolder',    # subfolder | prefix | none
    'preview': False,
    'content_match': False,
    'split_excel': False,
    'dedup': False,
    'auto_pw_txt': True,
    'pw_file': '',
    'delete_ok': False,
    'rules': [],                 # [{'rule_type':...,'value':...,'target':...,'enabled':...},...]
    'intelligent': True,         # 智能识别高频人名 + 姓名-证号关联
    'intelligent_min_freq': 10,  # 同一姓名至少出现在多少个文件中才算候选人名
    'intelligent_exclude': '',   # 用户自定义排除词(逗号分隔,如项目名/专案名)
    # ---- 「文件整理」模式 ----
    'work_mode': 'person',       # person=按人归档 | organize=文件整理
    'org_layout': '{类别}/{年}',
    'org_op_mode': 'move',       # move | copy
    'org_large_mb': 100,
    'org_dup': True,
    'org_versions': True,
    'org_junk': True,
    'org_empty': True,
    'org_large': False,
    'org_preview': True,
    'org_smart_date': True,
    'org_scan_only': False,
    'org_extract': False,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONF_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for k in DEFAULTS:
                if k in saved:
                    cfg[k] = saved[k]
    except Exception:
        pass
    return cfg


def save_config(cfg: dict):
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(CONF_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def template_dir() -> str:
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    return TEMPLATE_DIR


def save_template(path: str, cfg: dict):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_template(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    return d if isinstance(d, dict) else {}
