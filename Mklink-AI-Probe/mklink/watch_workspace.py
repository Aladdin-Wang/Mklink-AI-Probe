"""Project display preferences; no sampling addresses or acquisition mutations."""
from __future__ import annotations
import hashlib
import json
import math
import os
import secrets
from pathlib import Path
from .watch_preferences import _LOCK, PreferencesConflict


def normalize_workspace(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Unsupported workspace version')
    def text(v, limit=512):
        if not isinstance(v, str) or len(v) > limit or any(ord(c) < 32 for c in v):
            raise ValueError('Invalid workspace text')
        return v
    def sections(key):
        rows = value.get(key, [])
        if not isinstance(rows, list) or len(rows) > 64:
            raise ValueError('Expected at most 64 sections')
        result=[]; ids=set()
        for row in rows:
            if not isinstance(row, dict): raise ValueError('Invalid section')
            ident=text(row.get('id'))
            if not ident or ident in ids: raise ValueError('Duplicate section id')
            ids.add(ident)
            result.append({'id':ident,'name':text(row.get('name',''),128),'collapsed':bool(row.get('collapsed',False)),'height':max(100,min(1000,float(row.get('height',200))))})
            if not math.isfinite(result[-1]['height']): raise ValueError('Invalid height')
        return result
    groups=sections('groups'); panes=sections('panes')
    if not panes: panes=[{'id':'main','name':'波形区 1','collapsed':False,'height':240}]
    signals=value.get('signals',{})
    if not isinstance(signals,dict) or len(signals)>1024: raise ValueError('Too many signals')
    result={}
    for path,row in signals.items():
        text(path)
        if not path or not isinstance(row,dict): raise ValueError('Invalid signal')
        result[path]={'alias':text(row.get('alias',''),128),'emphasis':bool(row.get('emphasis',False)),
                      'group':row.get('group','') if row.get('group','') in {g['id'] for g in groups} else '',
                      'pane':row.get('pane') if row.get('pane') in {p['id'] for p in panes} else panes[0]['id']}
    return {'version':1,'groups':groups,'panes':panes,'signals':result}


def _path(root):
    path=Path(root).resolve()/'.mklink'/'superwatch_workspace.json'
    for part in (path.parent,path):
        if part.is_symlink() or getattr(part,'is_junction',lambda:False)(): raise ValueError('Workspace path must not redirect')
    return path


def load_workspace(root):
    with _LOCK:
        try:
            with _path(root).open('rb') as f: raw=f.read(1024*1024+1)
        except FileNotFoundError: raw=b''
        if len(raw)>1024*1024: raise ValueError('Workspace is too large')
        return {'workspace':normalize_workspace(json.loads(raw.decode('utf-8-sig')) if raw else {'version':1}), 'revision':hashlib.sha256(raw).hexdigest()}


def save_workspace(root, workspace, revision):
    workspace=normalize_workspace(workspace)
    with _LOCK:
        if load_workspace(root)['revision']!=revision: raise PreferencesConflict('Workspace changed in another window; reload and retry')
        path=_path(root);path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.parent/f'.{path.name}.{secrets.token_hex(8)}.tmp'
        try:
            with temporary.open('x',encoding='utf-8') as f:
                json.dump(workspace,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
            _path(root);os.replace(temporary,path)
        finally: temporary.unlink(missing_ok=True)
        return load_workspace(root)
