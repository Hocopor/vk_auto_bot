"""Временный деплой: залить app/ + миграцию на сервер (пароль в env SSH_PASS)."""
import os
import posixpath

import paramiko

LOCAL = "A:/DevAI/Zakazi/vk_auto_bot"
REMOTE = "/opt/vk_auto_bot"
EXTS = (".py", ".html", ".css", ".js")
ROOTS = ["app", "alembic/versions"]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("185.228.72.118", username="root", password=os.environ["SSH_PASS"], timeout=30)
sftp = c.open_sftp()


def ensure(d):
    parts = d.split("/")
    cur = ""
    for p in parts:
        if not p:
            cur = "/"
            continue
        cur = posixpath.join(cur, p)
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)


count = 0
for root in ROOTS:
    for dirpath, dirs, files in os.walk(os.path.join(LOCAL, root)):
        if "__pycache__" in dirpath:
            continue
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(EXTS):
                continue
            lp = os.path.join(dirpath, f)
            rel = os.path.relpath(lp, LOCAL).replace(os.sep, "/")
            rp = posixpath.join(REMOTE, rel)
            ensure(posixpath.dirname(rp))
            sftp.put(lp, rp)
            count += 1
print("uploaded files:", count)
sftp.close()
c.close()
