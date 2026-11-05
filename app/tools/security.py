import re, subprocess, ipaddress
from collections import Counter

FAILED = re.compile(r"Failed password .* from (\S+)|Invalid user .* from (\S+)")

def ssh_failures(n_lines=2000) -> dict[str, int]:
    out = subprocess.run(["journalctl","-u","ssh","-n",str(n_lines),"--no-pager"],
                         capture_output=True, text=True).stdout
    c = Counter()
    for m in FAILED.finditer(out):
        ip = m.group(1) or m.group(2)
        try: ipaddress.ip_address(ip); c[ip] += 1
        except ValueError: pass
    return dict(c.most_common(20))
