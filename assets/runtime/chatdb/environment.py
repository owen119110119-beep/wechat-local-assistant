"""Bounded local discovery of WeChat 4 data; no message reads or disk-wide search."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
from itertools import islice


def local_directory(value):
    text=os.path.expandvars(str(value).strip().strip('\"\''))
    p=Path(text).expanduser()
    if not p.is_absolute() or str(p).startswith(('\\\\','//')):
        raise ValueError('CHATDB_LOCAL_ABSOLUTE_PATH_REQUIRED')
    if any(q.is_symlink() or getattr(q,'is_junction',lambda:False)() for q in [p,*p.parents]):
        raise ValueError('CHATDB_DATA_LINK_FORBIDDEN')
    if not p.is_dir():raise ValueError('CHATDB_DIRECTORY_MISSING')
    return p.resolve()


def documents_locations():
    home=Path(os.environ.get('USERPROFILE') or Path.home())
    locations=[home/'Documents',home]
    for name in ['OneDrive','OneDriveConsumer','OneDriveCommercial']:
        if os.environ.get(name):locations.append(Path(os.environ[name])/'Documents')
    try:
        import winreg
        for branch in ['User Shell Folders','Shell Folders']:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,chr(92).join(['Software','Microsoft','Windows','CurrentVersion','Explorer',branch])) as key:
                value,_=winreg.QueryValueEx(key,'Personal');locations.insert(0,Path(os.path.expandvars(value)))
    except (ImportError,OSError):pass
    return locations


def configured_locations():
    bases=[]
    for variable in ['APPDATA','LOCALAPPDATA']:
        if os.environ.get(variable):bases.append(Path(os.environ[variable])/'Tencent')
    values=[]
    for base in bases:
        for folder in [base/'xwechat/config',base/'xwechat',base/'WeChat/All Users/config']:
            try:files=list(islice(folder.iterdir(),128))
            except OSError:continue
            for f in files:
                try:
                    if f.suffix.lower() not in {'.ini','.json','.cfg'} or f.is_symlink() or not f.is_file() or f.stat().st_size>16384:continue
                    raw=f.read_bytes()
                except OSError:continue
                for encoding in ['utf-8-sig','utf-16','utf-16-le','gbk']:
                    try:text=raw.decode(encoding).strip().strip('\x00')
                    except UnicodeError:continue
                    strings=[]
                    def collect(value):
                        if isinstance(value,str):strings.append(value)
                        elif isinstance(value,dict):
                            for item in value.values():collect(item)
                        elif isinstance(value,list):
                            for item in value[:128]:collect(item)
                    try:collect(json.loads(text))
                    except (ValueError,RecursionError):pass
                    for line in text.splitlines():
                        strings.append(line.strip())
                        if '=' in line:strings.append(line.split('=',1)[1].strip())
                    for value in strings:
                        value=value.strip().strip('\"\'').rstrip('\x00')
                        if re.match(r'^[A-Za-z]:[/\\]',value) or value.startswith('%'):
                            values.append((value,'wechat-config'))
    return values


def discover_accounts(hints=(),saved=None):
    """Accept a root, account directory or db_storage path; return metadata only."""
    bases=[]
    if saved:bases.append((saved,'remembered'))
    bases.extend((h,'provided') for h in hints if h)
    bases.extend(configured_locations())
    bases.extend((p,'documents') for p in documents_locations())
    accounts={};visited=set();issues=[]
    def inspect(value,origin,depth=0):
        if len(visited)>=512:return
        try:p=local_directory(value)
        except (OSError,ValueError) as error:
            if origin in {'provided','remembered'}:issues.append({'source':origin,'reason':str(error) if isinstance(error,ValueError) else 'CHATDB_DIRECTORY_UNREADABLE'})
            return
        key=str(p).casefold()
        if key in visited:return
        visited.add(key)
        try:
            if p.name=='db_storage':inspect(p.parent,origin);return
            if (p/'db_storage/contact/contact.db').is_file():
                contact=p/'db_storage/contact/contact.db'
                if any(q.is_symlink() or getattr(q,'is_junction',lambda:False)() for q in [contact,contact.parent,contact.parent.parent]):return
                accounts[key]={'accountPath':str(p),'dataRoot':str(p.parent),'source':origin}
                return
            if depth>=2:return
            named=[p/'xwechat_files',p/'WeChat Files']
            children=[]
            if p.name.lower() in {'xwechat_files','wechat files'} or origin in {'provided','remembered','wechat-config'}:
                children=list(islice(p.iterdir(),256))
            for child in [*named,*children]:
                if child.is_dir():inspect(child,origin,depth+1)
        except OSError:issues.append({'source':origin,'reason':'CHATDB_DIRECTORY_UNREADABLE'})
    for value,origin in bases:inspect(value,origin)
    rows=list(accounts.values())
    for index,row in enumerate(rows,1):
        parent=Path(row['dataRoot']);location=parent.parent.name if parent.name.lower() in {'xwechat_files','wechat files'} else parent.name
        row['displayName']=f'{parent.drive} {location or "微信数据"}中的账号 {index}'
    return {'accounts':rows,'issues':issues,'bounded':True}


def data_root():
    roots={row['dataRoot'] for row in discover_accounts()['accounts']}
    if len(roots)!=1:raise RuntimeError('CHATDB_DATA_ROOT_NOT_UNIQUE')
    return Path(next(iter(roots)))
