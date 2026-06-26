"""Временный helper: выполнить команду на боевом сервере по SSH (пароль из env SSH_PASS)."""
import os
import sys

import paramiko

host = "185.228.72.118"
user = "root"
password = os.environ["SSH_PASS"]
cmd = sys.argv[1]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=password, timeout=30)
stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
out = stdout.read().decode("utf-8", "replace")
err = stderr.read().decode("utf-8", "replace")
sys.stdout.write(out)
if err.strip():
    sys.stdout.write("\n--- STDERR ---\n" + err)
client.close()
