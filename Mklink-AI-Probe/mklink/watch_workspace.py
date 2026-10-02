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
    if not isinstance(value, dict) or value.get('version') not in (1, 2):
        raise ValueError('Unsupported workspace version')
    def text(v, limit=512):
        if not isinstance(v, str) or len(v) > limit or any(ord(c) < 32 for c in v):
            raise ValueError('Invalid workspace text')
        return v
    def sections(key):
        rows = value.get(key, [])
        if not isinstance(rows, list) or len(rows) > 128:
            raise ValueError('Expected at most 128 sections')
        result=[]; ids=set()
        for row in rows:
            if not isinstance(row, dict): raise ValueError('Invalid section')
            ident=text(row.get('id'))
            if not ident or ident in ids: raise ValueError('Duplicate section id')
            ids.add(ident)
            try: height=float(row.get('height',200))
            except (TypeError,ValueError) as exc: raise ValueError('Invalid height') from exc
            if not math.isfinite(height): raise ValueError('Invalid height')
            result.append({'id':ident,'name':text(row.get('name',''),128),'collapsed':bool(row.get('collapsed',False)),'height':max(100,min(1000,height))})
        return result
    groups=sections('groups'); panes=sections('panes')
    signals=value.get('signals',{})
    if not isinstance(signals,dict) or len(signals)>1024: raise ValueError('Too many signals')
    # Version 1 had independent membership and plots. Explicit group wins;
    # ungrouped signals retain their old plot through a migrated group.
    legacy=value['version']==1
    pane_groups={}
    if legacy:
        if not panes: panes=[{'id':'main','name':'默认分组','collapsed':False,'height':240}]
        used={g['id'] for g in groups}
        for pane in panes:
            ident=pane['id']
            while ident in used: ident='plot:'+ident
            pane_groups[pane['id']]=ident
            used.add(ident)
            groups.append({**pane,'id':ident,'collapsed':False})
    if not groups: groups=[{'id':'main','name':'默认分组','collapsed':False,'height':240}]
    if len(groups)>128: raise ValueError('Too many groups')
    ids={g['id'] for g in groups}
    default=pane_groups.get(panes[0]['id'],groups[0]['id']) if legacy and panes else groups[0]['id']
    requested_default=text(value.get('defaultGroup',''))
    if not legacy and requested_default in ids: default=requested_default
    if legacy:
        groups.sort(key=lambda g: g['id'] != default)
    result={}
    for path,row in signals.items():
        text(path)
        if not path or not isinstance(row,dict): raise ValueError('Invalid signal')
        group=text(row.get('group',''))
        pane=text(row.get('pane',''))
        if group not in ids: group=pane_groups.get(pane,default) if legacy else default
        mode=row.get('renderMode','line')
        if mode not in ('line','points'): raise ValueError('Invalid signal render mode')
        result[path]={'alias':text(row.get('alias',''),128),'emphasis':bool(row.get('emphasis',False)),
                      'group':group,'pane':group,'renderMode':mode}
    # Collapse only affects the signal list, never acquisition or plot visibility.
    return {'version':2,'defaultGroup':default,'groups':groups,'panes':[{**g,'collapsed':False} for g in groups],'signals':result}



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
